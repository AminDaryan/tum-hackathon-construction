"""The sandwich review: reading the bill, parts, the three prompt layers, checking answers,
sending parts at the same time, ranking."""

from __future__ import annotations

import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from app.agents.bill_review import (
    DEFAULT_FOCUS,
    Bill,
    Issue,
    Part,
    PartResult,
    Position,
    Review,
    Titel,
    build_prompt,
    context_layer,
    facts_from,
    load_issue_types,
    parse_answer,
    partition,
    question_layer,
    rank,
    review_bill,
)
from app.evaluation.llm_review import load

FAULTY = (
    Path(__file__).resolve().parents[4]
    / "Sample BoQ Dataset"
    / "Faulty Data By Claude AI"
    / "boq-StBALV23040-PLANTED-FAULTS.xlsx"
)
TYPES = {"018": ("Decimal point error", "quantity"), "080": ("Unusually low unit price", "pricing")}


def _position(oz: str, row: int, titel: str, **values: object) -> Position:
    fields: dict[str, object] = {
        "short_text": f"Rohr verlegen {oz}",
        "long_text": "Rohrleitung DN 150 verlegen, einschl. Formstücke.",
        "item_type": "Normalposition",
        "quantity": Decimal("10"),
        "unit": "m",
        "unit_price": Decimal("635.00"),
        "line_total": Decimal("6350.00"),
        "currency": "Eur",
    }
    fields.update(values)
    return Position(oz=oz, row_number=row, titel=titel, **fields)  # type: ignore[arg-type]


def _bill() -> Bill:
    first = Titel("01.01", "Rohrleitungen", 2, 3, "01", notes=["Hinweis: Grundwasser bei 2 m"])
    first.positions = [_position(f"01.01.000{n}", 3 + n, "01.01") for n in range(1, 6)]
    first.stated_sum, first.sum_row_number = Decimal("31750.00"), 9
    second = Titel("01.02", "Schächte", 2, 10, "01")
    second.positions = [_position("01.02.0001", 11, "01.02", unit="St")]
    top = Titel("01", "Leitungsbau", 1, 2, None, notes=["Hinweis: Baustelle im Klinikgelände"])
    return Bill(
        name="test.xlsx",
        titels=[top, first, second],
        positions=[*first.positions, *second.positions],
    )


def _part(bill: Bill, number: int = 1) -> Part:
    return partition(bill, 3)[number - 1]  # part 1: 01.01.0001-0003, part 2: the rest


def test_the_bill_is_split_by_section_and_a_long_section_between_its_titel() -> None:
    whole = partition(_bill())
    assert [(p.label, [t.code for t in p.titels], len(p.positions)) for p in whole] == [
        ("01", ["01.01", "01.02"], 6)
    ]
    parts = partition(_bill(), 3)  # 01.01 alone is too long: chunks of 3 and 2
    assert [(p.label, [t.code for t in p.titels], len(p.positions)) for p in parts] == [
        ("01 (1 of 2)", ["01.01"], 3),
        ("01 (2 of 2)", ["01.01", "01.02"], 3),
    ]
    assert [p.number for p in parts] == [1, 2]
    with pytest.raises(ValueError, match="at least 1"):
        partition(_bill(), 0)


def test_the_whole_bill_can_be_one_part_with_every_section_and_its_stated_sum() -> None:
    bill = _bill()
    bill.titels[0].stated_sum = Decimal("38100.00")
    other = Titel("02", "Erdbau", 1, 20, None)
    other.positions = [_position("02.0001", 21, "02", unit="m3")]
    bill.titels.append(other)
    bill.positions.append(other.positions[0])
    assert [p.label for p in partition(bill, 3)] == ["01 (1 of 2)", "01 (2 of 2)", "02"]

    (whole,) = partition(bill, 3, whole=True)
    assert [t.code for t in whole.titels] == ["01.01", "01.02", "02"]
    assert [p.oz for p in whole.positions] == [p.oz for p in bill.positions]
    types = load_issue_types(["018"])
    prompt = build_prompt(bill, whole, context_layer(bill, types), issue_types=types)
    assert "THE PART TO CHECK: the whole bill" in prompt
    assert "Stated sum of section 01: " in prompt
    assert "check the whole bill above, every position from 01.01.0001 to 02.0001" in prompt

    seen: list[str] = []
    review = review_bill(
        bill,
        lambda prompt: seen.append(prompt) or '{"issues": []}',
        issue_types=types,
        one_part=True,
    )
    assert len(seen) == 1 and [p.section for p in review.parts] == [whole.label]


def test_the_prompt_is_context_then_part_then_question_with_one_shared_context() -> None:
    bill = _bill()
    context = context_layer(bill, TYPES)
    prompts = [build_prompt(bill, part, context) for part in partition(bill, 3)]
    assert all(prompt.startswith(context) for prompt in prompts)
    first = prompts[0]
    assert first.index("<bill>") < first.index("<part>") < first.index("YOUR TASK")
    assert "ISSUE TYPES TO LOOK FOR (number and name; 2 of the 135" in context
    # the whole bill: every position in one line, the Titel with their stated sums
    assert "01.02.0001 | Rohr verlegen 01.02.0001 | 10 St | 635.00" in context
    assert "01.01 Rohrleitungen (5 positions, stated sum 31750.00)" in context
    assert "080 Unusually low unit price" in context
    # the part: its positions in full, the notes of its Titel and of the Titel above
    part = first[first.index("<part>") : first.index("</part>")]
    assert "THE PART TO CHECK: section 01 Leitungsbau (part 1 of 2)" in part
    assert "Position 01.01.0003" in part
    assert "Position 01.01.0004" not in part
    assert "Grundwasser bei 2 m" in part  # the notes of the Titel
    assert "Klinikgelände" in part  # and of the section
    assert "Stated sum" not in part  # a sum shows where its Titel ends
    second = prompts[1][prompts[1].index("<part>") :]
    assert second.index("Stated sum of Titel 01.01: 31750.00") < second.index("Titel 01.02")


def test_a_few_issue_types_are_asked_one_by_one_with_a_hint() -> None:
    part = _part(_bill())
    focused = question_layer(part, load_issue_types(DEFAULT_FOCUS))
    assert "section 01, positions 01.01.0001 to 01.01.0003" in focused
    assert "- 081 Unusually high unit price: the unit price is far above" in focused
    assert "Report only issues of these types." in focused
    assert "For every position ask" not in focused
    assert "For every position ask" in question_layer(part, load_issue_types())
    assert list(load_issue_types(["R18", " 080"])) == ["018", "080"]
    with pytest.raises(ValueError, match="not in the catalogue: 999"):
        load_issue_types(["999"])


def test_the_context_can_leave_out_the_position_index() -> None:
    context = context_layer(_bill(), TYPES, whole_bill=False)
    assert "01.01 Rohrleitungen" in context
    assert "All positions" not in context
    assert "01.02.0001 |" not in context


def _answer(*issues: dict[str, object]) -> str:
    return json.dumps({"issues": list(issues)})


def test_an_issue_on_a_position_of_the_part_is_kept_and_checked_against_the_bill() -> None:
    bill = _bill()
    raw = _answer(
        {
            "oz": "01.01.0002",
            "issue_type": "80",
            "category": "Risk",
            "certainty": "High",
            "quote": "635,00",
            "why": "Far dearer than the other pipe positions.",
            "related_oz": ["01.01.0001"],
        },
        {
            "oz": "01.01.0003",
            "issue_type": "R018",
            "category": "error",
            "quote": "10",
            "why": "Quantity looks one digit short.",
        },
        {
            "oz": "01.01.0001",
            "issue_type": "999",
            "category": "unclear",
            "quote": "words the position does not contain",
            "why": "Something.",
        },
    )
    kept, rejected = parse_answer(raw, _part(bill), bill, TYPES)
    assert rejected == []
    price, text, loose = kept
    assert (price.oz, price.row_numbers, price.certainty) == ("01.01.0002", (5,), "high")
    assert (price.issue_type, price.issue_name, price.category) == (
        "080",
        "Unusually low unit price",
        "risk",
    )
    assert price.grounded  # 635,00 is the unit price in German notation
    assert price.related_oz == ("01.01.0001",)
    assert text.issue_type == "018"
    assert text.grounded  # 10 is the quantity
    assert (loose.issue_type, loose.category, loose.grounded) == (None, None, False)
    assert loose.certainty is None


def test_a_price_issue_is_grounded_only_by_the_number_it_is_about() -> None:
    bill = _bill()
    raw = _answer(
        {"oz": "01.01.0001", "issue_type": "080", "quote": "6350.00", "why": "Quotes the total."},
        {"oz": "01.01.0002", "issue_type": "080", "quote": "635.00", "why": "Quotes the EP."},
        {"oz": "01.01.0003", "issue_type": "018", "quote": "Formstücke", "why": "A word."},
        {"oz": "01.01.0003", "quote": "Formstücke", "why": "No type, a word of the text."},
    )
    kept, _ = parse_answer(raw, _part(bill), bill, TYPES)
    assert [i.grounded for i in kept] == [False, True, False, True]


def test_sums_are_left_to_the_app_s_checks() -> None:
    bill = _bill()
    raw = _answer(
        {"oz": "01.01", "quote": "31750.00", "why": "The sum differs."},
        {"oz": "01", "quote": "Leitungsbau", "why": "The section has no sum."},
    )
    kept, rejected = parse_answer(raw, _part(bill, 2), bill, TYPES)
    assert kept == []
    assert [r.reason for r in rejected] == [
        "names 01.01: a Titel (sums are left to the app's checks)",
        "names 01: a Titel (sums are left to the app's checks)",
    ]
    question = question_layer(_part(bill), TYPES)
    assert "Titel number" not in question
    assert "the sums of Titel and sections, units and empty prices itself" in question


def test_the_findings_of_the_app_s_checks_stand_under_their_position_and_sum() -> None:
    bill = _bill()
    findings = [
        ((5,), "Line total 6350 does not match"),
        ((5, 6, 99), "Vague wording in 2 positions"),
        ((9,), "Subtotal 31750 does not match the sum of its items"),
        ((5,), "Line total 6350 does not match"),  # the same title once
    ]
    facts = facts_from(bill, findings)
    assert facts == {
        "01.01.0002": ["Line total 6350 does not match", "Vague wording in 2 positions"],
        "01.01.0003": ["Vague wording in 2 positions"],
        "01.01": ["Subtotal 31750 does not match the sum of its items"],
    }
    context = context_layer(bill, TYPES)
    first, second = (build_prompt(bill, part, context, facts=facts) for part in partition(bill, 3))
    line = (
        "  Already found by the app's checks: Line total 6350 does not match; "
        "Vague wording in 2 positions"
    )
    assert line in first
    assert (
        first.index("Position 01.01.0002") < first.index(line) < first.index("Position 01.01.0003")
    )
    assert (
        "Stated sum of Titel 01.01: 31750.00\n  Already found by the app's checks: Subtotal"
        in second
    )
    assert "Already found by the app's checks:" not in build_prompt(
        bill, partition(bill, 3)[0], context
    )


def test_answers_outside_the_part_or_without_reason_are_rejected_with_a_reason() -> None:
    bill = _bill()
    raw = _answer(
        {"oz": "01.01.0004", "why": "x"},
        {"oz": "99.99.9999", "why": "x"},
        {"oz": "01.01.0001", "why": ""},
        {"oz": "01.01.0001", "why": "Twice.", "issue_type": "018"},
        {"oz": "01.01.0001", "why": "Twice.", "issue_type": "018"},
        "not an object",
    )
    kept, rejected = parse_answer(raw, _part(bill), bill, TYPES)
    assert len(kept) == 1
    assert [r.reason for r in rejected] == [
        "names 01.01.0004: another part of the bill",
        "names 99.99.9999: no position of the bill",
        "no reason given",
        "repeats an issue already kept",
        "an issue is not an object",
    ]
    assert parse_answer("no json", _part(bill), bill, TYPES)[1][0].reason == (
        "the answer is not JSON"
    )
    assert parse_answer('{"x": 1}', _part(bill), bill, TYPES)[1][0].reason == (
        "the answer has no list of issues"
    )


def test_at_most_three_issues_are_kept_per_position() -> None:
    bill = _bill()
    raw = _answer(*({"oz": "01.01.0001", "why": f"Reason {n}."} for n in range(5)))
    kept, rejected = parse_answer(raw, _part(bill), bill, TYPES)
    assert len(kept) == 3
    assert {r.reason for r in rejected} == {"more than three issues on one position"}


def test_a_failed_request_is_recorded_and_the_other_parts_still_run() -> None:
    bill = _bill()
    calls: list[str] = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 2:
            raise TimeoutError("timed out")
        return _answer({"oz": "01.02.0001", "why": "Unit St for a pipe.", "quote": "St"})

    ticks = iter(range(100))
    review = review_bill(
        bill,
        generate,
        part_size=2,  # parts: 01.01.0001-2, 01.01.0003-4, 01.01.0005 with 01.02.0001
        issue_types=TYPES,
        usage=lambda: (100, 20),
        clock=lambda: float(next(ticks)),
    )
    assert [p.error for p in review.parts] == [None, "TimeoutError: timed out", None]
    assert [len(p.rejected) for p in review.parts] == [1, 0, 0]  # 01.02.0001 is not in part 1
    assert [(i.part, i.oz, i.grounded) for i in review.issues] == [(3, "01.02.0001", True)]
    assert review.parts[0].prompt_tokens == 100
    assert review.parts[0].seconds == 1.0
    only = review_bill(bill, generate, part_size=2, issue_types=TYPES, only_parts=[3])
    assert [p.part for p in only.parts] == [3]


def test_parts_sent_at_the_same_time_come_back_in_bill_order_after_the_first_alone() -> None:
    bill = _bill()
    finished: list[str] = []
    finished_before: list[int] = []  # requests finished when each request started
    lock = threading.Lock()
    reported: list[int] = []

    def generate(prompt: str) -> str:
        with lock:
            finished_before.append(len(finished))
        first = prompt[prompt.index("YOUR TASK") :].split("positions ")[1].split(" ")[0]
        with lock:
            finished.append(first)
        return _answer({"oz": first, "why": "The first position."})

    review = review_bill(
        bill,
        generate,
        part_size=2,
        issue_types=TYPES,
        workers=3,
        on_part=lambda result: reported.append(result.part),
    )
    assert [p.part for p in review.parts] == [1, 2, 3]
    assert [i.oz for i in review.issues] == ["01.01.0001", "01.01.0003", "01.01.0005"]
    assert finished_before[0] == 0 and min(finished_before[1:]) >= 1  # part 1 went alone
    assert sorted(reported) == [1, 2, 3]


def _issue(oz: str, row: int, certainty: str | None, grounded: bool = True) -> Issue:
    return Issue(
        part=1,
        oz=oz,
        row_numbers=(row,),
        issue_type=None,
        issue_name=None,
        category=None,
        quote="",
        grounded=grounded,
        why="x",
        related_oz=(),
        certainty=certainty,
    )


def test_the_suggestions_are_merged_by_position_and_ranked() -> None:
    def part(focus: str, *issues: Issue) -> PartResult:
        result = PartResult(
            part=1, section="01", positions=[], prompt_chars=1, seconds=0, focus=focus
        )
        result.issues = list(issues)
        return result

    review = Review(
        "test",
        "bill",
        [
            part(
                "numbers", _issue("A", 10, "low"), _issue("B", 20, "high"), _issue("C", 30, "high")
            ),
            part("text", _issue("A", 10, "medium"), _issue("A", 10, "high", grounded=False)),
            part("risk", _issue("D", 5, None), _issue("E", 40, "high")),
        ],
        1,
    )
    ranked = rank(review, checked={"E"})
    # A: numbers 1 + text max(2, 3 x 0.5) = 3; B, C and E 3 each, in bill order; D 1
    assert [(s.oz, s.score) for s in ranked] == [
        ("A", 3.0),
        ("B", 3.0),
        ("C", 3.0),
        ("E", 3.0),
        ("D", 1.0),
    ]
    first = ranked[0]
    assert (first.passes, first.certainty, first.grounded, len(first.issues)) == (
        ("numbers", "text"),
        "high",
        True,
        3,
    )
    assert [s.checked for s in ranked] == [False, False, False, True, False]  # marked, not moved


def test_the_issue_types_are_the_135_of_the_challenge_catalogue() -> None:
    types = load_issue_types()
    assert len(types) == 135
    assert types["018"] == ("Decimal point error", "quantity")


def test_the_faulty_test_bill_is_read_with_its_titel_notes_and_sums() -> None:
    bill, checked = load(FAULTY)
    assert len(bill.positions) == 248
    # the app's own checks ran on it: the planted wrong line total of 08.01.0001 (row 292)
    total = next(f for f in checked.findings if f.rule_id == "line_total_mismatch")
    assert 292 in total.rows
    assert "9938.4" in total.title
    assert "08.01.0001" in facts_from(bill, ((f.rows, f.title) for f in checked.findings))
    assert len(bill.titels) == 34
    sums = {t.code: t.stated_sum for t in bill.titels}
    assert sums["04.01"] == Decimal("14517.10")  # the planted wrong sum, as stated
    unit = {p.oz: p.unit for p in bill.positions}
    assert unit["03.03.0002"] == "m§"  # the planted unknown unit, as written
    position = bill.position("03.02.0011")
    assert position is not None
    assert (position.row_number, position.quantity) == (91, Decimal("2650"))
    titel = bill.titel("03.02")
    assert titel is not None
    assert any("Baugrundverhältnisse" in note for note in titel.notes)
    assert any("[Unterbeschreibung]" in p.long_text for p in bill.positions)
    parts = partition(bill)
    assert [p.label for p in parts] == [
        "01",
        "02",
        "03 (1 of 3)",
        "03 (2 of 3)",
        "03 (3 of 3)",
        "04",
        "05 (1 of 2)",
        "05 (2 of 2)",
        "06",
        "07",
        "08",
        "09",
        "10",
    ]
    assert sum(len(p.positions) for p in parts) == 248
    assert max(len(p.positions) for p in parts) == 32


def test_the_judge_gets_the_part_and_the_disputed_claims_and_its_verdicts_are_checked() -> None:
    from app.agents.bill_review import Claim, judge_claims

    bill = _bill()
    claims = [
        Claim("C1", "01.01.0002", "model", "Unit price far too high for laying a pipe."),
        Claim("C2", "01.02.0001", "checks", "Unit St for a pipe."),
        Claim("C3", "01.01.0005", "model", "Something."),
        Claim("C4", "", "checks", "A sum on no position."),
    ]
    asked: list[str] = []

    def answer(prompt: str) -> str:
        asked.append(prompt)
        if "C1 [" in prompt:
            return json.dumps(
                {
                    "verdicts": [
                        {"claim": "C1", "verdict": "Confirmed", "quote": "635.00", "why": "x"},
                        {"claim": "c3", "verdict": "rejected", "why": "normal"},
                    ]
                }
            )
        return "not json"

    parts = judge_claims(bill, claims, answer, part_size=3)
    assert [(p.part, p.claims) for p in parts] == [(1, ["C1"]), (2, ["C2", "C3"])]
    first = asked[0]
    assert first.index("<bill>") < first.index("<part>") < first.index("CLAIMS TO VERIFY")
    assert "C1 [position 01.01.0002, from a model reviewer] Unit price far too high" in first
    assert "Already found by the app's checks" not in first  # the judge reads the bill itself
    assert "a short text cut at about" in first  # the calibration
    verdicts = {v.cid: v for p in parts for v in p.verdicts}
    assert (verdicts["C1"].verdict, verdicts["C1"].grounded) == ("confirmed", True)
    assert verdicts["C2"].verdict == "unsure"  # no JSON: unsure
    assert "C4" not in verdicts  # a claim on no position is not sent


def test_the_basis_pass_asks_about_the_price_basis() -> None:
    from app.agents.bill_review import PASSES

    question = question_layer(_part(_bill()), load_issue_types(PASSES["basis"]))
    assert "- 085 Inconsistent price basis: the quantity, the unit price" in question
    assert "- 083 Incorrect tax treatment: the tax treatment of a price differs" in question
    assert "Give every issue a certainty." in question
