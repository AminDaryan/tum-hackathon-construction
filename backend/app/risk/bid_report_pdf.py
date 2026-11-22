"""The bid risk report of a project as a PDF to hand over (issue #112,
``GET /projects/{project_id}/risk-report/pdf``): the same content as the JSON report, in its
order. The bills, the ranked positions with their line totals and the money of each reminder,
the reminders about several positions, and how the list was made.

One table row per reminder: a position with several reminders keeps its rank on each of its rows
and its details on the first, so a row never splits and a page break between them still shows
which position a reminder belongs to. Deterministic: the same report gives the same bytes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.exporters.pdf_writer import Cell, Column, PdfDocument
from app.risk.bid_report import BidOtherReminder, BidPosition, BidReminder, BidReport
from app.risk.models import Money, MoneyKind, SizeClass

# A4 landscape leaves 762 points between the margins.
POSITION_COLUMNS = (
    Column("#", 26),
    Column("Position", 190),
    Column("Line total", 96),
    Column("Priority", 52),
    Column("Reminder", 300),
    Column("Money at stake", 98),
)
OTHER_COLUMNS = (
    Column("Priority", 52),
    Column("Reminder", 330),
    Column("About", 250),
    Column("Money at stake", 130),
)
LARGE_SHARE = "The positions concerned are a large share of the bill"


def render(report: BidReport) -> bytes:
    pdf = PdfDocument(f"Bid risk report: {report.project_name}", report.generated_at)
    pdf.heading(f"Bid risk report: {report.project_name}", 16)
    pdf.paragraph(f"Made {_when(report.generated_at)} from the last validation of the project.")
    for bill in report.bills:
        size = (
            f"total {_amount(bill.counted_total, bill.currency)}"
            if bill.priced and bill.counted_total is not None
            else "no prices"
        )
        pdf.paragraph(f"{bill.document_name}: {_positions(bill.positions)}, {size}.")
    for skipped in report.skipped:
        pdf.paragraph(f"Not in this report: {skipped.document_name} ({skipped.reason})")

    pdf.space(6)
    pdf.heading("Positions that drive price and risk")
    named = sum(p.kind == "reminders" for p in report.positions)
    added = len(report.positions) - named
    line = f"{named} of {_positions(report.positions_with_reminders)} with reminders"
    pdf.paragraph(line + (f"; {added} more listed for their size." if added else "."))
    if report.positions:
        pdf.table(POSITION_COLUMNS, [row for p in report.positions for row in _position_rows(p)])

    if report.other_reminders:
        pdf.heading("Reminders about several positions")
        pdf.table(OTHER_COLUMNS, [_other_row(o) for o in report.other_reminders])

    pdf.heading("How this list was made")
    for note in report.notes:
        pdf.paragraph(note)
    pdf.paragraph(report.order_basis)
    return pdf.render()


def _position_rows(position: BidPosition) -> list[tuple[Cell, ...]]:
    details = [position.short_text]
    if position.quantity is not None:
        details.append(f"{_number(position.quantity)} {position.unit or ''}".strip())
    details.append(position.document_name)
    first = (
        Cell(str(position.rank)),
        Cell(position.label, bold_first_line=True, detail="\n".join(details)),
        _line_total(position),
    )
    if not position.reminders:
        return [(*first, Cell(""), Cell("No reminder: listed for its size"), Cell(""))]
    rows: list[tuple[Cell, ...]] = []
    for index, reminder in enumerate(position.reminders):
        lead = first if index == 0 else (Cell(str(position.rank)), Cell(""), Cell(""))
        rows.append((*lead, *_reminder_cells(reminder, in_row=True)))
    return rows


def _other_row(other: BidOtherReminder) -> tuple[Cell, ...]:
    labels = ", ".join(other.positions)
    if other.reason == "many_positions":
        more = " …" if len(other.positions) < other.reminder.positions_total else ""
        about = f"Concerns {other.reminder.positions_total} positions: {labels}{more}"
    elif other.reason == "no_position":
        about = "Concerns the whole bill"
    else:
        about = f"Concerns a total or heading row: {labels}"
    priority, reminder, money = _reminder_cells(other.reminder, in_row=False)
    return (priority, reminder, Cell(about, detail=other.document_name), money)


def _reminder_cells(reminder: BidReminder, *, in_row: bool) -> tuple[Cell, Cell, Cell]:
    return (
        Cell(reminder.tier.value.capitalize()),
        Cell(
            reminder.title,
            bold_first_line=True,
            detail=reminder.question or reminder.suggested_action,
        ),
        _money(reminder.money, in_row=in_row),
    )


def _line_total(position: BidPosition) -> Cell:
    if position.line_total is None:
        return Cell("No price")
    share = position.share_of_total
    return Cell(
        _amount(position.line_total, position.currency),
        detail=f"{share * 100:.1f} % of the bill" if share is not None else "",
    )


def _money(money: Money, *, in_row: bool) -> Cell:
    """As the web shows it: an amount, an estimated range, a comparison (never a loss), or
    "Not known". An unknown amount's size class is the share of all the positions the reminder
    concerns together; under a position row (which shows its own share) it would read as that
    position's size, so it is said only outside the rows, and only when large."""
    if money.kind is MoneyKind.EXACT and money.amount is not None:
        return Cell(_amount(money.amount, money.currency))
    if money.kind is MoneyKind.ESTIMATE and money.low is not None and money.high is not None:
        return Cell(f"{money.low:,.2f} to {_amount(money.high, money.currency)} (estimate)")
    if money.reference is not None:
        return Cell(
            f"Comparison: {_amount(money.reference.amount, money.reference.currency)}",
            detail="Not a loss: the price may be right.",
        )
    large = not in_row and money.size_class is SizeClass.LARGE
    return Cell("Not known", detail=LARGE_SHARE if large else "")


def _positions(count: int) -> str:
    return f"{count} position" if count == 1 else f"{count} positions"


def _amount(value: Decimal, currency: str | None) -> str:
    return f"{value:,.2f} {currency or ''}".strip()


def _number(value: Decimal) -> str:
    """A quantity as written, without trailing zeros: 4,000 or 2.5."""
    return f"{value.normalize():,f}"


def _when(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")
