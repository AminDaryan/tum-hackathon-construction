"""Display orders of a finished risk report: by priority (the default), by price impact or by
evidence certainty.

Each list (``risks``, ``record``) is sorted on its own, after detection, discovery, merging,
tiers and triage: no reminder moves between the lists, and no reminder, count, tier, state,
money, evidence or id changes. ``priority_rank`` keeps each reminder's default position,
``rank`` is its displayed one. Sorting reads nothing and calls no model.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.risk.models import (
    Certainty,
    DisplayOrder,
    MoneyKind,
    Risk,
    RiskReport,
    SortBy,
    SortOrder,
)
from app.risk.triage import is_supplement

LEVEL = {
    Certainty.CONFIRMED: 4,
    Certainty.SUSPECTED: 3,
    Certainty.SEMANTIC: 2,
    Certainty.UNCLEAR: 1,
}
_BASIS = {
    "price_impact": (
        "price impact: the evidenced amount (exact: the absolute difference; estimate: the larger "
        "absolute end of its range), in the bill's currency"
    ),
    "confidence": (
        "evidence certainty: confirmed > suspected > semantic > unclear (desc); asc shows the "
        "least certain first; the tier is unchanged"
    ),
}
_LAST = {
    "price_impact": "amounts in another or no currency, then unknown money, in both directions",
    "confidence": "an unknown evidence level, in both directions",
}

_Keyed = tuple[Risk, int, Decimal, str | None]  # (reminder, group, main key, note)


def arrange(
    report: RiskReport, sort_by: SortBy = "priority", sort_order: SortOrder = "desc"
) -> RiskReport:
    """The report with ``risks`` and ``record`` in the asked display order. ``priority`` and
    ``desc`` give the default order unchanged; ``priority`` and ``asc`` its exact reverse."""
    currency = report.context.currency
    display = DisplayOrder(sort_by=sort_by, sort_order=sort_order)
    if sort_by in _BASIS:
        display = display.model_copy(
            update={"basis": _BASIS[sort_by], "always_last": _LAST[sort_by]}
        )
    return report.model_copy(
        update={
            "risks": _sorted(report.risks, sort_by, sort_order, currency),
            # Experimental supplements (unconfirmed model hypotheses) stay after the reminders
            # of the checks in every order: sorting never moves them into the base queue.
            "record": [
                *(
                    base := _sorted(
                        [r for r in report.record if not is_supplement(r)],
                        sort_by,
                        sort_order,
                        currency,
                    )
                ),
                *_sorted(
                    [r for r in report.record if is_supplement(r)],
                    sort_by,
                    sort_order,
                    currency,
                    start=len(base) + 1,
                ),
            ],
            "display": display,
        }
    )


def _sorted(
    risks: Sequence[Risk],
    sort_by: SortBy,
    sort_order: SortOrder,
    currency: str | None,
    *,
    start: int = 1,
) -> list[Risk]:
    # The lists arrive in the default order; priority_rank keeps that position.
    base = [
        r if r.priority_rank is not None else r.model_copy(update={"priority_rank": index})
        for index, r in enumerate(risks, start=start)
    ]
    if sort_by == "priority":
        keyed: list[_Keyed] = [(r, 0, Decimal(0), None) for r in base]
        if sort_order == "asc":
            keyed.reverse()
    else:
        keyed = [_key(r, sort_by, currency) for r in base]
        keyed.sort(key=lambda k: (k[0].priority_rank or 0, k[0].risk_id))
        compared = [k for k in keyed if k[1] == 0]
        # A stable sort: equal keys keep the default order in both directions.
        compared.sort(key=lambda k: k[2], reverse=sort_order == "desc")
        keyed = compared + sorted((k for k in keyed if k[1] != 0), key=lambda k: k[1])
    return [
        r.model_copy(update={"rank": rank, "sort_note": note})
        for rank, (r, _, _, note) in enumerate(keyed, start=start)
    ]


def _key(risk: Risk, sort_by: SortBy, currency: str | None) -> _Keyed:
    if sort_by == "confidence":
        level = LEVEL.get(risk.factors.certainty)
        if level is None:
            return risk, 1, Decimal(0), "evidence level unknown: placed last, never raised"
        return risk, 0, Decimal(level), None
    money = risk.money
    if money.kind is MoneyKind.UNKNOWN:
        note = "money unknown: placed after the amounts"
        if money.reference is not None:
            note += " (its comparison amount is not a loss and is not used)"
        return risk, 2, Decimal(0), note
    if money.kind is MoneyKind.EXACT:
        value, shown = abs(money.amount or Decimal(0)), f"{money.amount}"
    else:
        value = max(abs(money.low or Decimal(0)), abs(money.high or Decimal(0)))
        shown = f"{money.low} to {money.high} (estimate)"
    if currency is None or money.currency != currency:
        where = f"the bill's {currency}" if currency else "a bill of unknown currency"
        note = (
            f"{shown} {money.currency or '(no currency)'}: not compared with amounts in {where} "
            "(no conversion); placed after the compared amounts"
        )
        return risk, 1, Decimal(0), note
    return risk, 0, value, None
