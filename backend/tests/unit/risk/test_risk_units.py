"""Risk grading parts in isolation: tables, text matching, linking, grading, the model step."""

from __future__ import annotations

import http.server
import json
import threading
import time
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.agents.ollama import ServerError
from app.core import patterns
from app.core.config import LLMSettings
from app.core.errors import InvalidInputError
from app.risk.bill import Bill, Position, link, make_position
from app.risk.grading import grade
from app.risk.model_review import OllamaGenerator, review
from app.risk.models import (
    Candidate,
    Certainty,
    CoverageRow,
    Harm,
    LinkKind,
    Method,
    Money,
    MoneyKind,
    Quote,
    Risk,
    SizeClass,
    State,
    TrackRecord,
)
from app.risk.tables import RiskTables, load_tables
from app.risk.text import clause, find_all, fold, original_text, quote
from app.risk.triage import funnel

TABLES = load_tables("boq")


def _position(
    code: str, short: str, long: str = "", total: str | None = None, **kw: Any
) -> Position:
    return make_position(
        table_id="t1",
        row_id=f"r{code}",
        item_code=code,
        short_text=short,
        long_text=long,
        line_total=Decimal(total) if total else None,
        currency="EUR" if total else None,
        components=TABLES.components,
        **kw,
    )


def _bill(*positions: Position, total: str | None = None) -> Bill:
    return Bill(
        positions=positions,
        currency="EUR" if total else None,
        counted_total=Decimal(total) if total else None,
    )


def _candidate(position: Position, **kw: Any) -> Candidate:
    values: dict[str, Any] = {
        "rule_id": "X01",
        "risk_type": "R031",
        "method": Method.VAGUENESS,
        "state": State.RISK,
        "certainty": Certainty.SEMANTIC,
        "title": "test risk",
        "positions": (position.ref(),),
        "question": "Which value applies for {positions}?",
        "explanation": "Found for {positions}.",
        "evidence_keys": frozenset({f"X01@{position.key}"}),
        "stable_key": f"X01|{position.key}",
    }
    values.update(kw)
    return Candidate(**values)


# ----------------------------------------------------------------------------- tables
def test_the_tables_load_and_check_themselves() -> None:
    TABLES.check()
    assert TABLES.versions["grading"] and len(TABLES.catalogue.risk_types) == 135
    assert TABLES.risk_type("other").id == "other"
    assert not TABLES.grading.thresholds_validated  # the 1 % / 5 % thresholds are defaults


def test_a_profile_without_risk_tables_is_refused() -> None:
    with pytest.raises(InvalidInputError):
        load_tables("generic")


def _configured_patterns(tables: RiskTables) -> list[str]:
    found = [k.pattern for k in tables.components.keys] + list(tables.components.references)
    for rule in tables.dependencies.rules:
        found += [p for p in (rule.if_pattern, rule.expect_pattern, rule.depth_pattern) if p]
        found += [p for p in (rule.weight_pattern, rule.open_pattern) if p]
    for kind in tables.attributes.item_kinds:
        found += list(kind.required.values()) + ([kind.near_word] if kind.near_word else [])
    for group in tables.wording.groups:
        found += group.fine_if
    found += [r.pattern for r in tables.consistency.rules]
    return [*found, tables.grading.position_words.fire_rated_pattern]


@pytest.mark.parametrize(
    "text",
    [
        "a" * 500,
        "1" * 500,
        "1,1 " * 125,
        "dn " * 166,
        "c30/37 " * 71,
        "haus a " * 71,
        "pos. 01.02." * 45,
        "x" * 499 + "!",
        "tiefe 1" * 70,
    ],
)
def test_risk_patterns_stay_fast_on_hostile_text(text: str) -> None:
    for pattern in _configured_patterns(TABLES):
        started = time.perf_counter()
        patterns.search(pattern, text[:500])
        assert time.perf_counter() - started < 0.1, pattern


# ----------------------------------------------------------------------------- text
def test_folding_quotes_and_clauses_keep_the_original_words() -> None:
    original = "Abdich- tung der Kellerwände inkl. Hohlkehle. Danach Größe prüfen"
    folded = fold(original)
    assert folded.startswith("abdichtung der kellerwaende inkl. hohlkehle.")
    start = folded.index("kellerwaende")
    assert original_text(original, start, start + len("kellerwaende"), "?") == "Kellerwände"
    assert "Kellerwände" in quote(original, start, start + 5, chars=20)
    piece = clause(folded, start, start + 5, ["inkl."])
    assert "hohlkehle" in piece and "groesse" not in piece  # "inkl." does not end a sentence


def test_matches_beyond_the_first_window_report_their_place_in_the_whole_text() -> None:
    text = "x " * 400 + "dn 150"
    [(start, end, match)] = find_all(r"\bdn\s?(\d{2,4})\b", text)
    assert text[start:end] == "dn 150" and match.group(1) == "150"


# ----------------------------------------------------------------------------- links
def test_links_follow_components_locations_and_references() -> None:
    wall_a = _position("02.0010", "Kellerwand Haus A")
    seal_a = _position("02.0030", "Abdichtung Kellerwand Haus A")
    seal_b = _position("02.0031", "Abdichtung Kellerwand Haus B")
    seal_any = _position("02.0032", "Abdichtung Kellerwände")
    ref = _position("02.0040", "Hohlkehle wie Pos. 02.0010")
    assert link(wall_a, seal_a, "kellerwand")[0] is LinkKind.SHARED_KEY
    assert link(wall_a, seal_a)[0] is LinkKind.NOT_LINKED  # one building alone ties nothing
    assert link(wall_a, seal_b, "kellerwand")[0] is LinkKind.DIFFERENT
    assert link(wall_a, seal_any, "kellerwand")[0] is LinkKind.NOT_LINKED  # Haus A not named
    assert link(wall_a, ref)[0] is LinkKind.EXPLICIT_REFERENCE
    slab, rebar = _position("1", "Stahlbetondecke D3"), _position("2", "Betonstahl für Decke D3")
    assert link(slab, rebar)[0] is LinkKind.SHARED_KEY
    assert link(_position("3", "Kellerwand"), seal_any, "kellerwand")[0] is LinkKind.SHARED_KEY


# ----------------------------------------------------------------------------- grading
def test_the_same_evidence_found_twice_is_one_signal_and_its_money_is_not_summed() -> None:
    p = _position("01.0010", "Mauerwerk", total="100.00")
    shared = frozenset({"cell:t1/r1/c5"})
    first = _candidate(
        p,
        rule_id="A",
        risk_type="R076",
        method=Method.INVARIANT,
        certainty=Certainty.CONFIRMED,
        keywords_only=False,
        evidence_keys=shared,
        money=Money(kind=MoneyKind.EXACT, amount=Decimal(100), currency="EUR", basis="recomputed"),
    )
    second = _candidate(
        p,
        rule_id="B",
        risk_type="R081",
        method=Method.PEER_COMPARISON,
        certainty=Certainty.SUSPECTED,
        keywords_only=False,
        evidence_keys=shared,
        money=Money(kind=MoneyKind.EXACT, amount=Decimal(80), currency="EUR", basis="peers"),
    )
    [risk] = grade([first, second], _bill(p, total="10000.00"), TABLES)
    assert risk.rules == ["A", "B"] and risk.factors.independent_signals == 1
    assert (
        risk.money.amount == Decimal(100)
        and risk.evidence_class.value == "confirmed_rule_violation"
    )


def test_a_finding_about_many_positions_does_not_absorb_one_about_a_single_position() -> None:
    # A bill-wide wording finding lists the text cells of every item it names; a misspelling
    # in one of those cells is a different issue and stays its own risk.
    a, b, c = (_position(code, "Rohrleitung") for code in ("01.0010", "01.0020", "01.0030"))
    cell = "cell:t1/r01.0020/text"
    wide = _candidate(
        a,
        rule_id="WIDE",
        positions=(a.ref(), b.ref(), c.ref()),
        evidence_keys=frozenset({"cell:t1/r01.0010/text", cell, "cell:t1/r01.0030/text"}),
        stable_key="WIDE|all",
    )
    typo = _candidate(
        b, rule_id="TYPO", risk_type="R081", evidence_keys=frozenset({cell}), stable_key="TYPO|b"
    )
    same_scope = _candidate(
        a,
        rule_id="WIDE2",
        positions=(c.ref(), b.ref(), a.ref()),
        evidence_keys=frozenset({cell}),
        stable_key="WIDE2|all",
    )
    risks = grade([wide, typo, same_scope], _bill(a, b, c), TABLES)
    assert sorted(r.rules for r in risks) == [["TYPO"], ["WIDE", "WIDE2"]]
    assert all("Found by" not in r.why_risk_here for r in risks)


def test_independent_evidence_raises_the_tier_once() -> None:
    p = _position("01.0010", "Mauerwerk")
    found = [
        _candidate(
            p,
            rule_id="A",
            method=Method.INVARIANT,
            certainty=Certainty.SEMANTIC,
            keywords_only=False,
        ),
        _candidate(
            p,
            rule_id="B",
            method=Method.DEPENDENCY,
            certainty=Certainty.SEMANTIC,
            keywords_only=False,
            evidence_keys=frozenset({"B@x"}),
        ),
    ]
    [risk] = grade(found, _bill(p), TABLES)
    assert risk.factors.independent_signals == 2 and risk.tier.value == "high"
    assert "independent signals" in risk.tier_reason


def test_a_confirmed_large_difference_is_critical_and_its_threshold_is_marked_a_guess() -> None:
    p = _position("01.0010", "Mauerwerk", total="600.00")
    money = Money(
        kind=MoneyKind.EXACT,
        amount=Decimal(600),
        currency="EUR",
        basis="recomputed",
        share_of_total=Decimal("0.06"),
    )
    [risk] = grade(
        [_candidate(p, certainty=Certainty.CONFIRMED, keywords_only=False, money=money)],
        _bill(p, total="10000"),
        TABLES,
    )
    assert risk.tier.value == "critical" and risk.tier_rule == "T02"
    assert "first guesses, not measured" in risk.tier_reason


def test_safety_from_keywords_is_reviewed_first_but_not_called_a_hazard() -> None:
    p = _position("01.0010", "Graben ausheben, Tiefe 2,0 m")
    [risk] = grade(
        [_candidate(p, state=State.CANNOT_TELL, certainty=Certainty.UNCLEAR, harm=Harm.SAFETY)],
        _bill(p),
        TABLES,
    )
    assert risk.tier.value == "high" and "Not a confirmed hazard" in risk.tier_reason
    assert risk.state is State.CANNOT_TELL and risk.money.kind is MoneyKind.UNKNOWN


def test_a_structural_word_inside_another_word_does_not_raise_the_tier() -> None:
    utility = _position("01.0010", "Leitungen sichern", "nach Vorgabe des Versorgungsträgers")
    beam = _position("01.0020", "Stahlträger HEB 200 liefern")
    found = [_candidate(p, position_texts=(p.folded,)) for p in (utility, beam)]
    risks = grade(found, _bill(utility, beam), TABLES)
    tiers = {r.positions[0].label: r.tier.value for r in risks}
    assert tiers == {"01.0010": "medium", "01.0020": "high"}


def test_unknown_money_gets_a_size_class_but_no_amount() -> None:
    p = _position("01.0010", "Pauschale Baustelleneinrichtung", total="500.00")
    [risk] = grade([_candidate(p)], _bill(p, total="10000.00"), TABLES)
    assert risk.money.kind is MoneyKind.UNKNOWN and risk.money.amount is None
    assert risk.money.size_class is SizeClass.LARGE and "not an amount" in risk.money.basis


def test_a_check_reviewers_mostly_rejected_is_lowered() -> None:
    p = _position("01.0010", "Mauerwerk")
    record = TrackRecord(reviewed=6, confirmed=1, rejected=5)
    [risk] = grade([_candidate(p, track_record=record)], _bill(p), TABLES)
    assert risk.tier.value == "low" and "confirmed 1 of 6" in risk.tier_reason


def test_positions_of_one_rule_and_scope_become_one_reminder() -> None:
    a, b = _position("01.0010", "Wand A"), _position("01.0020", "Wand B")
    found = [
        _candidate(p, group="X01|s1|missing", evidence_keys=frozenset({p.key})) for p in (a, b)
    ]
    [risk] = grade(found, _bill(a, b), TABLES)
    assert (
        risk.positions_total == 2
        and risk.question == "Which value applies for 01.0010 and 01.0020?"
    )


# ----------------------------------------------------------------------------- local model
def _open_question() -> tuple[list[Risk], Bill]:
    p = _position("01.0010", "Kellerwand Haus A", long="Abdichtung mit KMB ist einzurechnen")
    bill = _bill(p)
    return grade(
        [
            _candidate(
                p,
                state=State.CANNOT_TELL,
                certainty=Certainty.UNCLEAR,
                quotes=(Quote(position=p.label, source="s", text="Kellerwand"),),
            )
        ],
        bill,
        TABLES,
    ), bill


OLLAMA = LLMSettings(provider="ollama", model="test-model")


def test_without_a_request_or_a_model_nothing_is_asked() -> None:
    risks, bill = _open_question()
    assert review(risks, bill, OLLAMA, requested=False)[1].status == "not_requested"
    assert review(risks, bill, LLMSettings(), requested=True)[1].status == "not_configured"
    assert (
        review([], bill, OLLAMA, requested=True, generator=lambda _: "{}")[1].status == "not_needed"
    )


def test_an_unreachable_model_leaves_every_result_as_it_was() -> None:
    risks, bill = _open_question()

    def down(prompt: str) -> str:
        raise OSError("connection refused")

    kept, status = review(risks, bill, OLLAMA, requested=True, generator=down)
    assert kept == risks and status.status == "unavailable" and status.failures == 1


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        json.dumps(
            {
                "answer": "covered",
                "cited_positions": ["99.9999"],
                "quote": "Abdichtung mit KMB ist einzurechnen",
            }
        ),
        json.dumps(
            {
                "answer": "covered",
                "cited_positions": ["01.0010"],
                "quote": "Abdichtung nach DIN 18533 W2.1-E",
            }
        ),
        json.dumps(
            {
                "answer": "maybe",
                "cited_positions": ["01.0010"],
                "quote": "Abdichtung mit KMB ist einzurechnen",
            }
        ),
    ],
)
def test_invented_positions_quotes_or_answers_are_dropped(answer: str) -> None:
    risks, bill = _open_question()
    kept, status = review(risks, bill, OLLAMA, requested=True, generator=lambda _: answer)
    assert kept == risks and status.hints_dropped == 1 and status.status == "completed"


def test_a_verified_hint_is_shown_but_changes_nothing() -> None:
    risks, bill = _open_question()
    answer = {
        "answer": "covered",
        "cited_positions": ["01.0010"],
        "quote": "Abdichtung mit  KMB ist einzurechnen",
    }
    [risk], status = review(
        risks, bill, OLLAMA, requested=True, generator=lambda _: json.dumps(answer)
    )
    assert status.hints_kept == 1 and risk.counter_evidence[-1].link is LinkKind.MODEL_HINT
    assert (
        risk.state is risks[0].state and risk.tier is risks[0].tier and risk.money == risks[0].money
    )


@pytest.fixture
def ollama() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    seen: list[dict[str, Any]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            status = 500 if seen[-1]["prompt"] == "fail" else 200
            payload: dict[str, Any] = {"response": '{"answer": "unclear"}'}
            if seen[-1]["prompt"] != "legacy":
                payload["done_reason"] = "length" if seen[-1]["prompt"] == "cut" else "stop"
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()


def test_the_ollama_generator_posts_a_json_request(
    ollama: tuple[str, list[dict[str, Any]]],
) -> None:
    url, seen = ollama
    generator = OllamaGenerator(LLMSettings(provider="ollama", model="m1", base_url=url))
    assert generator("hello") == '{"answer": "unclear"}'
    assert generator.last_stop == "stop"
    assert seen[0]["model"] == "m1" and seen[0]["format"] == "json" and seen[0]["stream"] is False
    generator("cut")
    assert generator.last_stop == "length"
    generator("legacy")
    assert generator.last_stop is None
    generator("hello")
    with pytest.raises(ServerError):
        generator("fail")
    assert generator.last_stop is None


def test_the_funnel_separates_a_check_without_data_from_a_type_without_check() -> None:
    def row(risk_type: str, state: State, rules: list[str]) -> CoverageRow:
        return CoverageRow(
            risk_type=risk_type, name="n", category="c", state=state, reason="r", rules=rules
        )

    rows = [
        row("R001", State.NOT_CHECKABLE, ["detector_x"]),
        row("R002", State.NOT_CHECKABLE, []),
        row("R003", State.COVERED, ["D01"]),
    ]
    assert funnel([], 0, 0, [], [], [], rows).checks_missing_information == [
        "1 risk type has a check that could not run on this data (R001)",
        "1 risk type of the catalogue has no check in this version (taxonomy entry only)",
    ]
