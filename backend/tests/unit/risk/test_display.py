"""The three display orders of a finished risk report (priority, price impact, evidence
certainty), on reminders with given tiers: nothing is regraded here.

The expected orders are worked out by hand from the policy (grading.yaml's sort keys for the
default; the price and certainty rules of app.risk.display), not read from the function.
"""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Any

from app.models.issue import EvidenceClass, Severity
from app.risk.display import arrange
from app.risk.grading import order, sort_values
from app.risk.models import (
    Certainty,
    Direction,
    Factors,
    Harm,
    Method,
    Money,
    MoneyKind,
    Priority,
    ProjectContext,
    ReferenceAmount,
    Risk,
    RiskReport,
    SizeClass,
    State,
)
from app.risk.triage import _ranked
from tests.unit.risk.test_risk_checks import TABLES

EVIDENCE = {
    Certainty.CONFIRMED: EvidenceClass.CONFIRMED_RULE_VIOLATION,
    Certainty.SUSPECTED: EvidenceClass.SUSPECTED_ANOMALY,
    Certainty.SEMANTIC: EvidenceClass.SEMANTIC_WARNING,
    Certainty.UNCLEAR: EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
}


def _unknown(**extra: Any) -> Money:
    return Money(kind=MoneyKind.UNKNOWN, basis="no price in the bill", **extra)


def _exact(amount: str, currency: str = "EUR") -> Money:
    return Money(
        kind=MoneyKind.EXACT,
        amount=Decimal(amount),
        currency=currency,
        basis="the difference the workbench computed",
        size_class=SizeClass.MEDIUM,
    )


def _estimate(low: str, high: str) -> Money:
    return Money(
        kind=MoneyKind.ESTIMATE,
        low=Decimal(low),
        high=Decimal(high),
        quantity=Decimal("100"),
        reference_price=Decimal("50"),
        comparable="01.0010, 01.0020 (median unit price)",
        currency="EUR",
        basis="quantity x reference price of comparable positions",
        size_class=SizeClass.MEDIUM,
    )


def _risk(name: str, tier: Severity, certainty: Certainty, money: Money) -> Risk:
    return Risk(
        risk_id=f"risk_{name}",
        rank=1,
        tier=tier,
        tier_rule="given",
        tier_reason="given by the test",
        title=f"Reminder {name}",
        risk_type="other",
        risk_name="Other",
        category="other",
        direction=Direction.COST_RISK,
        state=State.RISK,
        evidence_class=EVIDENCE[certainty],
        methods=[Method.GUIDED_LLM if certainty is Certainty.SEMANTIC else Method.INVARIANT],
        rules=["T1"],
        positions_total=1,
        why_risk_here="given by the test",
        money=money,
        factors=Factors(
            harm=Harm.MONEY,
            certainty=certainty,
            challenge_priority=Priority.MEDIUM,
            independent_signals=1,
        ),
        suggested_action="Look at it.",
    )


A = _risk("a", Severity.CRITICAL, Certainty.UNCLEAR, _unknown())
B = _risk("b", Severity.HIGH, Certainty.SUSPECTED, _exact("5000"))
C = _risk("c", Severity.MEDIUM, Certainty.CONFIRMED, _exact("100"))
D = _risk("d", Severity.MEDIUM, Certainty.SEMANTIC, _estimate("2000", "8000"))


def _default(risks: list[Risk], currency: str | None = "EUR") -> list[Risk]:
    """``risks`` in the default order of the real policy (grading.yaml), ranked like triage."""
    keyed = [
        (
            r,
            sort_values(
                tier=r.tier,
                state=r.state,
                certainty=r.factors.certainty,
                money=r.money,
                currency=currency,
                priority=r.factors.challenge_priority,
                kinds=1,
                risk_id=r.risk_id,
                tables=TABLES,
            ),
        )
        for r in risks
    ]
    return _ranked(order(keyed, TABLES))


def _report(risks: list[Risk], record: list[Risk] | None = None, currency: str | None = "EUR"):  # type: ignore[no-untyped-def]
    from app.risk.models import Funnel, ModelReview

    return RiskReport(
        run_id="run_1",
        profile_id="boq",
        tables_version={},
        context=ProjectContext(positions=4, priced=True, currency=currency),
        counts={"reminders": len(risks)},
        risks=_default(risks, currency),
        record=_default(record or [], currency),
        funnel=Funnel(
            raw_doubts=0,
            explained_automatically=0,
            below_size_threshold=0,
            open_after_search=0,
            after_merging=0,
            main_list=0,
            kept_in_record=0,
            open_question_groups=0,
        ),
        coverage=[],
        model_review=ModelReview(status="not_requested", detail="not asked"),
    )


def _names(risks: list[Risk]) -> list[str]:
    return [r.risk_id.removeprefix("risk_").upper() for r in risks]


def test_the_three_orders_differ_as_the_policy_says() -> None:
    report = _report([A, B, C, D])
    assert _names(arrange(report, "priority", "desc").risks) == ["A", "B", "D", "C"]
    assert _names(arrange(report, "price_impact", "desc").risks) == ["D", "B", "C", "A"]
    assert _names(arrange(report, "confidence", "desc").risks) == ["C", "B", "D", "A"]
    assert _names(arrange(report, "priority", "asc").risks) == ["C", "D", "B", "A"]  # reversed
    assert _names(arrange(report, "price_impact", "asc").risks) == ["C", "B", "D", "A"]
    assert _names(arrange(report, "confidence", "asc").risks) == ["A", "D", "B", "C"]


def test_sorting_changes_ranks_only() -> None:
    report = _report([A, B, C, D])
    for by in ("priority", "price_impact", "confidence"):
        for direction in ("desc", "asc"):
            shown = arrange(report, by, direction)
            assert [r.rank for r in shown.risks] == [1, 2, 3, 4]
            before = {
                r.risk_id: r.model_copy(update={"rank": 0, "sort_note": None}) for r in report.risks
            }
            after = {
                r.risk_id: r.model_copy(update={"rank": 0, "sort_note": None}) for r in shown.risks
            }
            assert after == before  # tier, state, evidence, money, priority_rank unchanged
            assert shown.display.sort_by == by and shown.display.policy_version == "display-1"
            assert shown.model_copy(update={"risks": [], "display": report.display}) == (
                report.model_copy(update={"risks": []})
            )
    priority = {r.risk_id: r.priority_rank for r in report.risks}
    assert priority == {"risk_a": 1, "risk_b": 2, "risk_d": 3, "risk_c": 4}


def test_unknown_money_goes_last_both_ways_and_a_known_zero_is_an_amount() -> None:
    zero = _risk("e", Severity.LOW, Certainty.CONFIRMED, _exact("0"))
    report = _report([A, B, C, D, zero])
    assert _names(arrange(report, "price_impact", "desc").risks) == ["D", "B", "C", "E", "A"]
    asc = arrange(report, "price_impact", "asc").risks
    assert _names(asc) == ["E", "C", "B", "D", "A"]
    assert asc[0].sort_note is None and "money unknown" in (asc[-1].sort_note or "")


def test_an_estimate_is_ordered_by_its_range_and_stays_an_estimate() -> None:
    exact = _risk("f", Severity.MEDIUM, Certainty.CONFIRMED, _exact("100"))
    estimate = _risk("g", Severity.MEDIUM, Certainty.SEMANTIC, _estimate("80", "120"))
    shown = arrange(_report([exact, estimate]), "price_impact", "desc").risks
    assert _names(shown) == ["G", "F"]  # the larger end of 80-120 is above 100
    assert shown[0].money == estimate.money and shown[0].money.kind is MoneyKind.ESTIMATE
    assert shown[0].evidence_class is EvidenceClass.SEMANTIC_WARNING  # never a confirmed loss


def test_amounts_compare_as_exact_decimals_and_stay_decimal_strings() -> None:
    higher = _risk("h", Severity.MEDIUM, Certainty.CONFIRMED, _exact("100.10"))
    lower = _risk("i", Severity.MEDIUM, Certainty.CONFIRMED, _exact("100.09"))
    three = _risk("j", Severity.MEDIUM, Certainty.CONFIRMED, _exact("0.3"))
    thirds = _risk("k", Severity.MEDIUM, Certainty.CONFIRMED, _exact("0.30000000000000004"))
    shown = arrange(_report([lower, higher, three, thirds]), "price_impact", "desc")
    assert _names(shown.risks) == ["H", "I", "K", "J"]  # floats would tie 0.3 and 0.3...04
    dumped = shown.model_dump(mode="json")["risks"]
    assert [r["money"]["amount"] for r in dumped] == [
        "100.10",
        "100.09",
        "0.30000000000000004",
        "0.3",
    ]


def test_other_or_unknown_currencies_are_not_compared_or_converted() -> None:
    dollars = _risk("l", Severity.HIGH, Certainty.CONFIRMED, _exact("9000", "USD"))
    shown = arrange(_report([A, B, dollars, C]), "price_impact", "desc").risks
    assert _names(shown) == ["B", "C", "L", "A"]
    note = shown[2].sort_note or ""
    assert "USD" in note and "no conversion" in note and shown[2].money.amount == Decimal("9000")
    unknown = arrange(_report([B, C], currency=None), "price_impact", "desc").risks
    assert all("unknown currency" in (r.sort_note or "") for r in unknown)  # never taken as EUR
    assert _names(unknown) == _names(_report([B, C], currency=None).risks)  # default order kept


def test_a_negative_difference_counts_by_its_size_and_keeps_its_sign() -> None:
    minus = _risk("m", Severity.MEDIUM, Certainty.CONFIRMED, _exact("-6000"))
    shown = arrange(_report([B, minus]), "price_impact", "desc").risks
    assert _names(shown) == ["M", "B"] and shown[0].money.amount == Decimal("-6000")


def test_equal_keys_keep_the_default_order_whatever_the_input_order() -> None:
    twins = [
        _risk(name, Severity.MEDIUM, Certainty.SUSPECTED, _exact("500")) for name in ("n", "o", "p")
    ]
    report = _report(twins)
    expected = _names(report.risks)
    for seed in range(5):
        shuffled = report.risks[:]
        random.Random(seed).shuffle(shuffled)
        again = report.model_copy(update={"risks": shuffled})
        for by in ("price_impact", "confidence"):
            for direction in ("desc", "asc"):
                assert _names(arrange(again, by, direction).risks) == expected


def test_least_certain_first_keeps_every_tier() -> None:
    shown = arrange(_report([A, B, C, D]), "confidence", "asc").risks
    assert [r.factors.certainty for r in shown] == [
        Certainty.UNCLEAR,
        Certainty.SEMANTIC,
        Certainty.SUSPECTED,
        Certainty.CONFIRMED,
    ]
    assert {r.risk_id: r.tier for r in shown} == {r.risk_id: r.tier for r in [A, B, C, D]}


def test_an_unknown_evidence_level_is_never_raised() -> None:
    report = _report([A, B, C])
    odd = [
        r.model_copy(update={"factors": r.factors.model_copy(update={"certainty": "sure"})})
        if r.risk_id == "risk_c"
        else r
        for r in report.risks
    ]  # a level outside the four, as a model or an old file might state it
    for direction in ("desc", "asc"):
        shown = arrange(report.model_copy(update={"risks": odd}), "confidence", direction).risks
        assert shown[-1].risk_id == "risk_c" and "never raised" in (shown[-1].sort_note or "")


def test_a_comparison_amount_is_not_a_loss_and_not_used() -> None:
    reference = ReferenceAmount(
        amount=Decimal("50000"),
        currency="EUR",
        basis="quantity x difference to the median unit price",
        kind="reference_deviation",
        source_issue_id="iss_1",
        detector_id="peer_price",
    )
    compared = _risk("r", Severity.HIGH, Certainty.SUSPECTED, _unknown(reference=reference))
    shown = arrange(_report([C, compared]), "price_impact", "desc").risks
    assert _names(shown) == ["C", "R"] and "not a loss" in (shown[-1].sort_note or "")


def test_each_list_is_sorted_on_its_own() -> None:
    e = _risk("e", Severity.MEDIUM, Certainty.SUSPECTED, _estimate("2000", "8000"))
    report = _report([A, B], record=[C, e])
    shown = arrange(report, "price_impact", "desc")
    assert _names(shown.risks) == ["B", "A"] and _names(shown.record) == ["E", "C"]
    assert shown.open_questions == report.open_questions
    assert {r.risk_id for r in shown.record} == {r.risk_id for r in report.record}


def test_experimental_supplements_stay_after_the_checks_in_every_order() -> None:
    """D is made of model hypotheses only: whatever the order, it never moves into the base
    queue, and the base reminders keep the order they would have without it."""
    e = _risk("e", Severity.MEDIUM, Certainty.SUSPECTED, _estimate("2000", "8000"))
    with_model = _report([A, B], record=[C, e, D])
    without = _report([A, B], record=[C, e])
    for sort_by in ("priority", "price_impact", "confidence"):
        for direction in ("desc", "asc"):
            shown = arrange(with_model, sort_by, direction).record  # type: ignore[arg-type]
            base = arrange(without, sort_by, direction).record  # type: ignore[arg-type]
            assert _names(shown)[-1] == "D" and _names(shown)[:-1] == _names(base)
            assert [r.rank for r in shown] == [1, 2, 3]


def test_empty_single_and_unpriced_lists() -> None:
    empty = _report([])
    assert arrange(empty, "price_impact", "asc").risks == []
    [only] = arrange(_report([B]), "confidence", "desc").risks
    assert only.rank == 1 and only.priority_rank == 1
    unpriced = [
        _risk(n, t, Certainty.SUSPECTED, _unknown())
        for n, t in (("s", Severity.HIGH), ("t", Severity.MEDIUM))
    ]
    report = _report(unpriced)
    for direction in ("desc", "asc"):
        shown = arrange(report, "price_impact", direction).risks
        assert _names(shown) == _names(report.risks)  # all unknown: the default order


def test_the_default_request_keeps_the_order_from_before_the_sorts() -> None:
    report = _report([A, B, C, D])
    shown = arrange(report)
    assert shown.risks == report.risks and shown.record == report.record
    assert shown.display.sort_by == "priority" and shown.display.sort_order == "desc"


def test_a_long_list_is_sorted_whole() -> None:
    many = [
        _risk(f"z{n:02d}", Severity.MEDIUM, Certainty.SUSPECTED, _exact(str(n))) for n in range(60)
    ]
    shown = arrange(_report([], record=many), "price_impact", "desc").record
    assert len(shown) == 60 and [r.rank for r in shown] == list(range(1, 61))
    assert shown[0].money.amount == Decimal(59) and shown[-1].money.amount == Decimal(0)
