"""Write the small bill of quantities that the browser end-to-end test uploads.

Run with the backend's Python (openpyxl is a backend dependency):

    python make_bill.py <output.xlsx>

Three priced items with German headers that the ``boq`` profile maps. The line total of the
third item is wrong on purpose: 2.5 t x 1,450.00 = 3,625.00, the bill says 3,725.00. Every other
value is consistent, so a baseline run reports exactly one finding (deterministic.line_total).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

HEADER = ("Pos.", "Kurztext", "Menge", "Einheit", "Einheitspreis", "Gesamtpreis")
ITEMS = (
    (
        "01.0010",
        "Mauerwerk aus Kalksandstein, 17,5 cm",
        Decimal(120),
        "m2",
        Decimal("45.50"),
    ),
    ("01.0020", "Beton C25/30 für Fundamente", Decimal(18), "m3", Decimal("165.00")),
    (
        "01.0030",
        "Betonstahl B500B liefern und einbauen",
        Decimal("2.5"),
        "t",
        Decimal("1450.00"),
    ),
)
PLANTED_TOTAL = Decimal("3725.00")  # quantity x unit price of the third item is 3625.00


def write_bill(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "LV"
    sheet.append(HEADER)
    for index, (code, text, quantity, unit, price) in enumerate(ITEMS):
        total = PLANTED_TOTAL if index == len(ITEMS) - 1 else quantity * price
        sheet.append((code, text, float(quantity), unit, float(price), float(total)))
    workbook.save(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_bill.py <output.xlsx>")
    write_bill(Path(sys.argv[1]))
