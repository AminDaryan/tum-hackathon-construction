"""The bid risk report of a project (issue #112): the positions that drive price and risk, one
row each, to print and hand over.

It is read from the risk reports of the project's bills, with no score of its own:

* A row is a position that a reminder of its bill's main list names. A reminder that names more
  positions than ``combination.max_positions`` of ``grading.yaml``, none, or a row that is not a
  position (a total, a heading) is listed once below the rows, its money not spread over them.
* Rows are ordered by the position's size class first (its share of its bill's counted total:
  large, medium, small; a position without a line total last), so a large position comes before
  a small one whatever their tiers. Within a size class the sort keys of ``grading.yaml`` read
  for a position decide: the highest tier, state and challenge priority of its reminders, their
  largest weighted exposure (:func:`app.risk.grading.weighted_exposure`, never shown) and the
  number of its reminders; ties go to the larger line total, then to the bills' order.
* When fewer than ``limit`` positions have reminders and the bills are priced in one currency,
  the positions with the largest line totals fill the list, marked ``largest``.

Two kinds of money stay apart: the position's line total and its share of its bill's counted
total, and each reminder's own money (exact, an estimate, or unknown with its basis).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.models.base import FrozenModel
from app.models.issue import SEVERITY_RANK, Severity
from app.models.values import ExactDecimal
from app.risk.bill import Bill, Position
from app.risk.explain import count_of
from app.risk.grading import order, share_of_total, size_class, weighted_exposure
from app.risk.models import PRIORITY_RANK, SIZE_RANK, STATE_STRENGTH, Money, Risk, State
from app.risk.tables import RiskTables

FORMAT_VERSION = "bid-1"
MAX_LABELS = 10
ORDER_BASIS = (
    "Positions with reminders come first, ordered by size: those at 1 % or more of their "
    "bill's total, then 0.1 % to 1 %, then below 0.1 %, and positions without a price last. "
    "Positions of the same size follow the highest priority of their reminders, then whether a "
    "problem was found or only could not be ruled out, then the money at stake weighed by how "
    "solid its evidence is (used for the order only, not shown), then how serious the kind of "
    "risk is and how many reminders there are; then the larger line total and the order of the "
    "bills. Positions added only for their size come last, the largest first."
)


class BidReminder(FrozenModel):
    """A reminder of a bill's risk report, as the bid report lists it."""

    risk_id: str
    tier: Severity
    state: State
    title: str
    risk_name: str
    positions_total: int = Field(ge=0)
    money: Money  # the reminder's own money: exact, an estimate, or unknown with its basis
    question: str | None = None
    suggested_action: str


class BidPosition(FrozenModel):
    """One row: a position of a bill, its line total and the reminders that name it."""

    rank: int = Field(ge=1)
    kind: Literal["reminders", "largest"]  # largest: in the list for its line total alone
    document_id: str
    document_name: str
    run_id: str
    label: str
    item_code: str | None = None
    table_id: str
    row_id: str
    short_text: str
    quantity: ExactDecimal | None = None
    unit: str | None = None
    unit_price: ExactDecimal | None = None
    line_total: ExactDecimal | None = None
    currency: str | None = None
    share_of_total: ExactDecimal | None = None  # of its bill's counted total
    reminders: list[BidReminder] = Field(default_factory=list)


class BidOtherReminder(FrozenModel):
    """A reminder no row holds, listed once; its money is not spread over positions."""

    reason: Literal["many_positions", "no_position", "not_a_position"]
    document_id: str
    document_name: str
    run_id: str
    positions: list[str] = Field(default_factory=list)  # labels, capped
    reminder: BidReminder


class BidBill(FrozenModel):
    document_id: str
    document_name: str
    run_id: str
    run_status: str
    positions: int = Field(ge=0)
    priced: bool
    currency: str | None = None
    counted_total: ExactDecimal | None = None
    reminders: int = Field(ge=0)  # of its main list, without the rejected ones
    rejected: int = Field(ge=0)  # reminders reviewers rejected, left out


class BidSkipped(FrozenModel):
    """A file of the project with no part in the report, and why."""

    document_id: str
    document_name: str
    reason: str


class BidReport(FrozenModel):
    """The ranked positions of a project's bills that drive price and risk, computed on request
    from the bills' risk reports; nothing is stored and no model is called."""

    format_version: str = FORMAT_VERSION
    project_id: str
    project_name: str
    generated_at: datetime
    limit: int = Field(ge=1)
    positions: list[BidPosition]
    positions_with_reminders: int = Field(ge=0)  # before the cut to ``limit``
    other_reminders: list[BidOtherReminder] = Field(default_factory=list)
    bills: list[BidBill] = Field(default_factory=list)
    skipped: list[BidSkipped] = Field(default_factory=list)
    largest_share: ExactDecimal | None = None  # share of the largest line totals, see notes
    order_basis: str = ORDER_BASIS
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BillPart:
    """One bill of the project: its run, its bill and its main list in the default order."""

    document_id: str
    document_name: str
    run_id: str
    run_status: str
    bill: Bill
    tables: RiskTables
    reminders: Sequence[Risk]  # without the ones reviewers rejected
    rejected: int = 0


@dataclass(slots=True)
class _Row:
    part: int  # its bill's place in the parts
    index: int  # its place in the bill
    position: Position
    reminders: list[Risk] = field(default_factory=list)


def build(
    *,
    project_id: str,
    project_name: str,
    generated_at: datetime,
    parts: Sequence[BillPart],
    limit: int = 20,
    skipped: Sequence[BidSkipped] = (),
    notes: Sequence[str] = (),
) -> BidReport:
    currencies = sorted({p.bill.currency for p in parts if p.bill.currency})
    currency = currencies[0] if len(currencies) == 1 else None
    rows, others = _rows(parts)
    # Ties on every sort key keep this order: the larger line total, then the bills' order.
    rows.sort(key=lambda r: (-_size(r.position, currency), r.part, r.index))
    # shortcut: the first bill's grading.yaml orders all rows; only the boq profile has risk
    # tables today, give each profile its own order if another one gets them.
    ranked = (
        order([(r, _values(r, parts, currency)) for r in rows], parts[0].tables) if parts else []
    )
    # The report lists what drives the price: size class before tier (stable, so the grading
    # order stays within a class).
    ranked.sort(key=lambda r: -_size_rank(r, parts))
    shown = [(r.part, r.position, r.reminders) for r in ranked[:limit]]
    taken = {(r.part, r.position.key) for r in rows}
    added = _largest(parts, taken, currency, limit - len(shown))
    positions = [
        _position(rank, parts[part], position, reminders)
        for rank, (part, position, reminders) in enumerate([*shown, *added], start=1)
    ]
    share, counted = _largest_share(parts, currency, limit)
    explained = [
        "From each bill's risk list only the main reminders are here: those with concrete "
        "evidence, a priority of medium or higher and a next step. What was checked and the open "
        "questions are not in this report.",
        *notes,
    ]
    if len(ranked) > limit:
        explained.append(f"{len(ranked)} positions have reminders; the first {limit} are shown.")
    if added:
        explained.append(
            f"{count_of(len(added), 'position')} without a reminder "
            f"{'was' if len(added) == 1 else 'were'} added for their line totals, the "
            "largest of the priced bills: they are listed for their size, not for a finding."
        )
    if share is not None:
        explained.append(
            f"The {counted} largest positions make up {share * 100:.1f} % of the counted total "
            "of the priced bills."
        )
    if len(currencies) > 1:
        explained.append(
            f"The bills are priced in several currencies ({', '.join(currencies)}): amounts are "
            "not compared across them (no conversion), so money does not order the list and no "
            "position is added for its size."
        )
    for part in parts:
        if not part.bill.priced:
            explained.append(
                f"{part.document_name} has no prices: its positions have no line total and the "
                "money of its reminders is unknown."
            )
        if part.run_status != "completed":
            explained.append(
                f"The validation of {part.document_name} ended as {part.run_status}: findings of "
                "detectors that did not finish are missing."
            )
    rejected = sum(p.rejected for p in parts)
    if rejected:
        explained.append(
            f"{count_of(rejected, 'reminder')} that reviewers rejected "
            f"{'is' if rejected == 1 else 'are'} left out."
        )
    return BidReport(
        project_id=project_id,
        project_name=project_name,
        generated_at=generated_at,
        limit=limit,
        positions=positions,
        positions_with_reminders=len(ranked),
        other_reminders=sorted(others, key=lambda o: -SEVERITY_RANK[o.reminder.tier]),
        bills=[_bill(p) for p in parts],
        skipped=list(skipped),
        largest_share=share,
        notes=explained,
    )


def _rows(parts: Sequence[BillPart]) -> tuple[list[_Row], list[BidOtherReminder]]:
    rows: dict[tuple[int, str], _Row] = {}
    others: list[BidOtherReminder] = []
    for number, part in enumerate(parts):
        places = {(p.table_id, p.row_id): (i, p) for i, p in enumerate(part.bill.positions)}
        most = part.tables.grading.combination.max_positions
        for risk in part.reminders:
            hits = [
                places[k] for k in ((r.table_id, r.row_id) for r in risk.positions) if k in places
            ]
            reason: Literal["many_positions", "no_position", "not_a_position"] | None = None
            if not risk.positions:
                reason = "no_position"
            elif risk.positions_total > most:
                reason = "many_positions"
            elif len(hits) < len(risk.positions):
                reason = "not_a_position"
            if reason is not None:
                others.append(
                    BidOtherReminder(
                        reason=reason,
                        document_id=part.document_id,
                        document_name=part.document_name,
                        run_id=part.run_id,
                        positions=[r.label for r in risk.positions][:MAX_LABELS],
                        reminder=_reminder(risk),
                    )
                )
                continue
            for index, position in hits:
                row = rows.setdefault((number, position.key), _Row(number, index, position))
                row.reminders.append(risk)
    return list(rows.values()), others


def _values(row: _Row, parts: Sequence[BillPart], currency: str | None) -> dict[str, Decimal | str]:
    """The sort keys of ``grading.yaml``, read for one position."""
    tables = parts[0].tables
    risks = row.reminders
    return {
        "tier": Decimal(max(SEVERITY_RANK[r.tier] for r in risks)),
        "state": Decimal(max(STATE_STRENGTH[r.state] for r in risks)),
        "weighted_exposure_eur": max(
            weighted_exposure(r.money, r.factors.certainty, currency, tables) for r in risks
        ),
        "unknown_money_size_class": Decimal(_size_rank(row, parts)),
        "challenge_priority": Decimal(
            max(PRIORITY_RANK[r.factors.challenge_priority] for r in risks)
        ),
        "distinct_signal_kinds": Decimal(len(risks)),  # for a position: its reminders
        "risk_id": "",  # the same for every row, so the order the rows came in breaks ties
    }


def _size_rank(row: _Row, parts: Sequence[BillPart]) -> int:
    """The position's size class as a rank; 0 without a line total."""
    share = _share(row.position, parts[row.part].bill)
    return SIZE_RANK[size_class(abs(share), parts[0].tables)] if share is not None else 0


def _largest(
    parts: Sequence[BillPart], taken: set[tuple[int, str]], currency: str | None, room: int
) -> list[tuple[int, Position, list[Risk]]]:
    """Positions with the largest line totals in ``currency`` that no row holds."""
    if room <= 0 or currency is None:
        return []
    found = [
        (number, index, position)
        for number, part in enumerate(parts)
        for index, position in enumerate(part.bill.positions)
        if (number, position.key) not in taken and _counted(position, currency)
    ]
    found.sort(key=lambda f: (-_size(f[2], currency), f[0], f[1]))
    return [(number, position, []) for number, _, position in found[:room]]


def _largest_share(
    parts: Sequence[BillPart], currency: str | None, limit: int
) -> tuple[Decimal | None, int]:
    """(the share of the counted total that the ``limit`` largest line totals make up, how many
    positions that is), over the bills priced in ``currency``."""
    bills = [p.bill for p in parts if currency and p.bill.currency == currency]
    total = sum((abs(b.counted_total or Decimal(0)) for b in bills), Decimal(0))
    sizes = sorted(
        (_size(p, currency) for b in bills for p in b.positions if _counted(p, currency)),
        reverse=True,
    )[:limit]
    if not total or not sizes:
        return None, 0
    return sum(sizes, Decimal(0)) / total, len(sizes)


def _counted(position: Position, currency: str | None) -> bool:
    return bool(
        position.counts_toward_totals is True
        and position.line_total
        and position.currency == currency
    )


def _size(position: Position, currency: str | None) -> Decimal:
    """The absolute line total in ``currency``; 0 in another currency or without one."""
    if position.line_total is None or position.currency != currency:
        return Decimal(0)
    return abs(position.line_total)


def _share(position: Position, bill: Bill) -> Decimal | None:
    if position.line_total is None:
        return None
    return share_of_total(position.line_total, position.currency, bill)


def _reminder(risk: Risk) -> BidReminder:
    return BidReminder(
        risk_id=risk.risk_id,
        tier=risk.tier,
        state=risk.state,
        title=risk.title,
        risk_name=risk.risk_name,
        positions_total=risk.positions_total,
        money=risk.money,
        question=risk.question,
        suggested_action=risk.suggested_action,
    )


def _position(rank: int, part: BillPart, position: Position, reminders: list[Risk]) -> BidPosition:
    return BidPosition(
        rank=rank,
        kind="reminders" if reminders else "largest",
        document_id=part.document_id,
        document_name=part.document_name,
        run_id=part.run_id,
        label=position.label,
        item_code=position.item_code,
        table_id=position.table_id,
        row_id=position.row_id,
        short_text=position.short_text,
        quantity=position.quantity,
        unit=position.unit,
        unit_price=position.unit_price,
        line_total=position.line_total,
        currency=position.currency,
        share_of_total=_share(position, part.bill),
        reminders=[_reminder(r) for r in reminders],
    )


def _bill(part: BillPart) -> BidBill:
    return BidBill(
        document_id=part.document_id,
        document_name=part.document_name,
        run_id=part.run_id,
        run_status=part.run_status,
        positions=len(part.bill.positions),
        priced=part.bill.priced,
        currency=part.bill.currency,
        counted_total=part.bill.counted_total,
        reminders=len(part.reminders),
        rejected=part.rejected,
    )
