"""The tender a bid answers: an unpriced bill in the bid's project whose positions match it.

``domain.boq_tender_comparison`` compares the bid with it (``ValidationContext.tender``). A
tender is a bill with no unit price on any item row (X81, X83, D83, or a spreadsheet or PDF
without prices). Item numbers repeat between trades, so a candidate is taken only when at least
half of the bid's positions have the same item number there with the same quantity or short
text (a bid that states neither, a bare GAEB 90 price list, matches by item number); of several
candidates, the one with the most such positions wins, the first in the
project's file order on a tie. Files a person put among the supporting documents are left out,
and a bill without prices gets no tender: it is one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.dataset import Dataset, RowKind
from app.models.model_takeoff import code_key, same_text
from app.models.tender import Tender
from app.models.values import NumberValue, TextValue
from app.services.workbench import Workbench


@dataclass(frozen=True, slots=True)
class _Position:
    quantity: Decimal | None
    short_text: str | None
    priced: bool


def tender_for(wb: Workbench, dataset: Dataset) -> Tender | None:
    """The tender of ``dataset`` in the projects it belongs to, or ``None``."""
    bid = _positions(dataset)
    if not any(position.priced for position in bid.values()):
        return None
    best: Tender | None = None
    best_matches = 0
    with wb.uow() as uow:
        for project in uow.projects.list():
            if all(file.document_id != dataset.document_id for file in project.files):
                continue
            for file in project.files:
                if file.document_id == dataset.document_id or file.group == "support":
                    continue
                document = uow.documents.get(file.document_id)
                candidate = uow.datasets.latest_for_document(file.document_id)
                if document is None or candidate is None:
                    continue
                matches = _matching(bid, _positions(candidate))
                if matches > best_matches:
                    best, best_matches = Tender(document.original_filename, candidate), matches
    return best


def _positions(dataset: Dataset) -> dict[tuple[object, ...], _Position]:
    """The item rows of ``dataset`` by item number. A number that repeats keeps its first row:
    matching only needs most positions, and the comparison check skips repeats itself."""
    found: dict[tuple[object, ...], _Position] = {}
    for table in dataset.tables:
        columns = {
            field: table.column_for_field(field)
            for field in ("item_code", "quantity", "description", "unit_price")
        }
        if columns["item_code"] is None:
            continue
        for row in table.rows:
            if row.excluded or row.kind is not RowKind.ITEM:
                continue
            cells = {
                field: cell
                for field, column in columns.items()
                if column is not None and (cell := row.cells.get(column.column_id)) is not None
            }
            values = {field: cell.normalized_value for field, cell in cells.items()}
            code = values.get("item_code")
            # An item code typed as a number (a spreadsheet's 1.1) is compared as written.
            written = code.value if isinstance(code, TextValue) else None
            if written is None and "item_code" in cells:
                written = (cells["item_code"].raw_value or "").strip()
            key = code_key(written) if written else ()
            if not key or key in found:
                continue
            quantity, text = values.get("quantity"), values.get("description")
            found[key] = _Position(
                quantity=quantity.value if isinstance(quantity, NumberValue) else None,
                short_text=text.value if isinstance(text, TextValue) and text.value else None,
                priced=isinstance(values.get("unit_price"), NumberValue),
            )
    return found


def _matching(
    bid: dict[tuple[object, ...], _Position], candidate: dict[tuple[object, ...], _Position]
) -> int:
    """How many of the bid's positions ``candidate`` holds with the same quantity or short
    text; 0 when the candidate is priced (not a tender) or matches fewer than half."""
    if not candidate or any(position.priced for position in candidate.values()):
        return 0
    matches = sum(1 for key, position in bid.items() if _same(position, candidate.get(key)))
    return matches if bid and 2 * matches >= len(bid) else 0


def _same(bid: _Position, tender: _Position | None) -> bool:
    if tender is None:
        return False
    if bid.quantity is None and bid.short_text is None:
        return True  # a bare price list (a GAEB 90 D84) has only its item numbers to match
    if bid.quantity is not None and bid.quantity == tender.quantity:
        return True
    return bool(
        bid.short_text and tender.short_text and same_text(bid.short_text, tender.short_text)
    )
