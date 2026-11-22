"""The bid risk report of a project (issue #112), on reminders with given tiers and money.

The expected orders are worked out by hand: the position's size class first, then grading.yaml's
sort keys read for a position (tier, state, weighted exposure, challenge priority, reminders),
then the larger line total and the bills' order; they are not read from the function.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models.issue import EvidenceClass, Severity
from app.risk.bid_report import BidReport, BidSkipped, BillPart, build
from app.risk.bill import Bill, Position, make_position
from app.risk.models import (
    Certainty,
    Direction,
    Factors,
    Harm,
    Method,
    Money,
    MoneyKind,
    PositionRef,
    Priority,
    Risk,
    State,
)
from tests.unit.risk.test_risk_checks import TABLES

NOW = datetime(2026, 11, 21, tzinfo=UTC)
UNKNOWN = Money(kind=MoneyKind.UNKNOWN, basis="No amount can be derived from the bill.")


def _pos(code: str, total: str | None = None, currency: str = "EUR") -> Position:
    amount = Decimal(total) if total else None
    return make_position(
        table_id="t1",
        row_id=f"r{code}",
        item_code=code,
        short_text=f"Position {code}",
        unit="St",
        quantity=Decimal(1),
        unit_price=amount,
        line_total=amount,
        currency=currency if total else None,
        components=TABLES.components,
    )


def _bill(*positions: Position, currency: str = "EUR") -> Bill:
    totals = [p.line_total for p in positions if p.line_total is not None]
    return Bill(
        positions=positions,
        currency=currency if totals else None,
        counted_total=sum(totals, Decimal(0)) if totals else None,
    )


def _exact(amount: str) -> Money:
    return Money(kind=MoneyKind.EXACT, amount=Decimal(amount), currency="EUR", basis="computed")


def _risk(
    name: str,
    tier: Severity,
    *on: Position,
    money: Money = UNKNOWN,
    refs: list[PositionRef] | None = None,
) -> Risk:
    positions = refs or [
        PositionRef(label=p.label, item_code=p.item_code, table_id=p.table_id, row_id=p.row_id)
        for p in on
    ]
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
        evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
        methods=[Method.INVARIANT],
        rules=["T1"],
        positions=positions,
        positions_total=len(positions),
        why_risk_here="given by the test",
        money=money,
        factors=Factors(
            harm=Harm.MONEY,
            certainty=Certainty.CONFIRMED,
            challenge_priority=Priority.MEDIUM,
            independent_signals=1,
        ),
        question=f"Question {name}?",
        suggested_action="Look at it.",
    )


def _part(name: str, bill: Bill, *reminders: Risk, **extra: object) -> BillPart:
    fields: dict[str, object] = {
        "document_id": f"doc_{name}",
        "document_name": f"{name}.x83",
        "run_id": f"run_{name}",
        "run_status": "completed",
        "bill": bill,
        "tables": TABLES,
        "reminders": list(reminders),
        **extra,
    }
    return BillPart(**fields)  # type: ignore[arg-type]


def _report(*parts: BillPart, limit: int = 20) -> BidReport:
    return build(
        project_id="prj_1", project_name="Tender", generated_at=NOW, parts=parts, limit=limit
    )


def test_positions_follow_the_sort_keys_and_the_largest_fill_the_list() -> None:
    a, b, c, d = _pos("A", "5000"), _pos("B", "3000"), _pos("C", "1000"), _pos("D", "500")
    e, f = _pos("E", "200"), _pos("F", "100")
    report = _report(
        _part(
            "lv",
            _bill(a, b, c, d, e, f),
            _risk("wide", Severity.HIGH, a, b, c, d),  # four positions: listed below the rows
            _risk("high", Severity.HIGH, c),
            _risk("exact", Severity.MEDIUM, d, money=_exact("400")),
            _risk("two", Severity.MEDIUM, b, a),
            _risk("also", Severity.MEDIUM, d),
        ),
        limit=6,
    )
    # C: high. D: medium with 400 EUR of exact money. A and B: medium, money unknown, both in
    # the large size class: the larger line total first. E and F fill the list by line total.
    assert [p.label for p in report.positions] == ["C", "D", "A", "B", "E", "F"]
    assert [p.rank for p in report.positions] == [1, 2, 3, 4, 5, 6]
    assert [p.kind for p in report.positions] == ["reminders"] * 4 + ["largest"] * 2
    assert report.positions_with_reminders == 4
    row = report.positions[1]
    assert [r.risk_id for r in row.reminders] == ["risk_exact", "risk_also"]
    assert row.reminders[0].money.amount == Decimal("400")
    assert row.reminders[1].money.kind is MoneyKind.UNKNOWN
    assert row.line_total == Decimal("500") and row.share_of_total == Decimal(500) / 9800
    assert report.positions[4].reminders == []
    (other,) = report.other_reminders
    assert other.reason == "many_positions" and other.positions == ["A", "B", "C", "D"]
    assert other.reminder.risk_id == "risk_wide"
    assert report.largest_share == 1
    assert any("The 6 largest positions make up 100.0 %" in n for n in report.notes)
    assert any("2 positions without a reminder were added" in n for n in report.notes)


def test_a_large_position_comes_before_a_higher_tier_on_a_small_one() -> None:
    big, mid, small = _pos("BIG", "90000"), _pos("MID", "500"), _pos("SMALL", "50")
    report = _report(
        _part(
            "priced",
            _bill(big, mid, small),
            _risk("small", Severity.HIGH, small),
            _risk("mid", Severity.HIGH, mid),
            _risk("big", Severity.MEDIUM, big),
        ),
        _part("unpriced", _bill(_pos("U")), _risk("u", Severity.HIGH, _pos("U"))),
    )
    # Of 90,550: BIG 99.4 % (large), MID 0.55 % (medium), SMALL 0.06 % (small); U has no line
    # total. Size class before tier, so the medium BIG leads and the high U comes last.
    assert [p.label for p in report.positions] == ["BIG", "MID", "SMALL", "U"]


def test_an_unpriced_bill_is_cut_to_the_limit_and_not_filled() -> None:
    p1, p2, p3, p4 = _pos("01"), _pos("02"), _pos("03"), _pos("04")
    report = _report(
        _part(
            "lv",
            _bill(p1, p2, p3, p4),
            _risk("one", Severity.MEDIUM, p1),
            _risk("two", Severity.MEDIUM, p2),
            _risk("three", Severity.HIGH, p3),
        ),
        limit=2,
    )
    # 03 is high; 01 and 02 tie on every key and have no line total: the bill's order.
    assert [p.label for p in report.positions] == ["03", "01"]
    assert report.positions_with_reminders == 3
    assert report.largest_share is None
    assert all(p.line_total is None and p.share_of_total is None for p in report.positions)
    assert "3 positions have reminders; the first 2 are shown." in report.notes
    assert any("lv.x83 has no prices" in n for n in report.notes)
    assert not report.bills[0].priced


def test_bills_are_ranked_together_and_a_total_row_is_listed_apart() -> None:
    x, y = _pos("X", "1000"), _pos("Y", "4000")
    total_row = PositionRef(label="Summe Titel 01", table_id="t1", row_id="r_total")
    report = _report(
        _part("first", _bill(x), _risk("x", Severity.MEDIUM, x, money=_exact("50"))),
        _part(
            "second",
            _bill(y),
            _risk("y", Severity.MEDIUM, y),
            _risk("sum", Severity.HIGH, refs=[total_row]),
            rejected=1,
            run_status="completed_with_errors",
        ),
        limit=5,
    )
    # Both medium: X has 50 EUR of exact money, Y's money is unknown although Y is larger.
    assert [(p.document_name, p.label) for p in report.positions] == [
        ("first.x83", "X"),
        ("second.x83", "Y"),
    ]
    (other,) = report.other_reminders
    assert (other.reason, other.document_id, other.positions) == (
        "not_a_position",
        "doc_second",
        ["Summe Titel 01"],
    )
    assert [b.rejected for b in report.bills] == [0, 1]
    assert "1 reminder that reviewers rejected is left out." in report.notes
    assert any("second.x83 ended as completed_with_errors" in n for n in report.notes)
    assert report.largest_share == 1


def test_bills_in_two_currencies_are_not_compared() -> None:
    x, z = _pos("X", "1000"), _pos("Z", "9000", currency="CHF")
    report = _report(
        _part("eur", _bill(x), _risk("x", Severity.MEDIUM, x, money=_exact("900"))),
        _part("chf", _bill(z, currency="CHF"), _risk("z", Severity.MEDIUM, z)),
        _part("spare", _bill(_pos("S", "50000"))),
    )
    assert [p.kind for p in report.positions] == ["reminders", "reminders"]
    assert report.largest_share is None
    assert any("several currencies (CHF, EUR)" in n for n in report.notes)


def test_a_project_without_bills_gives_an_empty_report() -> None:
    report = build(
        project_id="prj_1",
        project_name="Tender",
        generated_at=NOW,
        parts=[],
        skipped=[BidSkipped(document_id="doc_ref", document_name="ref.x83", reason="Reference")],
    )
    assert report.positions == [] and report.bills == []
    assert [(s.document_name, s.reason) for s in report.skipped] == [("ref.x83", "Reference")]
