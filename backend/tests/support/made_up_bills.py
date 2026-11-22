"""Invented bills of quantities that the evaluation tests write themselves, with answer keys.

Nothing here comes from a real bill: the works, quantities and prices are made up. The bills
are semicolon CSV files in the column layout of a GAEB export (OZ, Kurztext, Positionsart,
Menge, Einheit, EP, Nachlass %, GP, Währung, Langtext), so the app reads them as it reads an
uploaded bill: section rows ("01", "01.01") and positions, one line per row, the header on
row 1.

* :func:`long_bill` writes a clean bill in 13 sections and a faulty copy with three planted
  faults. Section 03 holds 120 positions in three Titel, so the sandwich review's default part
  size (40) splits it into parts 3 to 5; sections 04 to 13 are parts 6 to 15.
* :func:`practice_folder` lays out a practice benchmark as ``llm_review --practice`` reads it:
  four clean bills in ``input/``, two faulty copies of each in ``out/``, and one answer key per
  faulty copy next to it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

HEADER = "OZ;Kurztext;Positionsart;Menge;Einheit;EP;Nachlass %;GP;Währung;Langtext"

# Invented works: a short text, a unit and a unit price, cycled through for the positions.
WORKS = (
    ("Oberboden abtragen", "m2", Decimal("3.50")),
    ("Graben ausheben", "m3", Decimal("28.00")),
    ("Graben verfüllen", "m3", Decimal("18.00")),
    ("Boden abfahren", "m3", Decimal("35.00")),
    ("PE-Rohr verlegen", "m", Decimal("45.00")),
    ("Formstück einbauen", "St", Decimal("60.00")),
    ("Schieber einbauen", "St", Decimal("850.00")),
    ("Druckprüfung", "m", Decimal("2.50")),
    ("Pflaster aufnehmen", "m2", Decimal("12.00")),
    ("Pflaster verlegen", "m2", Decimal("38.00")),
    ("Bordstein setzen", "m", Decimal("24.00")),
    ("Schacht setzen", "St", Decimal("1200.00")),
)


@dataclass(frozen=True, slots=True)
class Position:
    oz: str
    text: str
    quantity: Decimal | None
    unit: str
    price: Decimal
    total: Decimal | None = None  # the line total as written; quantity times price when None
    long_text: str = ""

    def line(self) -> str:
        quantity = "" if self.quantity is None else f"{self.quantity:.3f}"
        if self.total is not None:
            total = f"{self.total:.2f}"
        else:
            total = "" if self.quantity is None else f"{self.quantity * self.price:.2f}"
        fields = [
            self.oz,
            self.text,
            "Normalposition",
            quantity,
            self.unit,
            f"{self.price:.2f}",
            "",
            total,
            "Eur",
            self.long_text or f"{self.text}.",
        ]
        return ";".join(fields)


Section = tuple[str, str]  # a section row: its number and its title
Row = Position | Section


def positions(titel: str, count: int, start: int = 0) -> list[Position]:
    """``count`` positions of Titel ``titel`` (``titel.0001`` on), each with its own quantity."""
    made = []
    for n in range(count):
        text, unit, price = WORKS[(start + n) % len(WORKS)]
        quantity = Decimal(10 + (start + n) * 7 % 90)
        made.append(Position(f"{titel}.{n + 1:04d}", f"{text} Los {n + 1}", quantity, unit, price))
    return made


def write(path: Path, rows: list[Row]) -> dict[str, int]:
    """Write the bill and return the row number of every position and section, by its OZ."""
    lines = [HEADER]
    numbers: dict[str, int] = {}
    for row in rows:
        if isinstance(row, Position):
            lines.append(row.line())
            numbers[row.oz] = len(lines)
        else:
            code, title = row
            lines.append(f"{code};{title};;;;;;;;")
            numbers[code] = len(lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return numbers


def changed(rows: list[Row], oz: str, **fields: Any) -> list[Row]:
    """The rows with the position ``oz`` changed as ``fields`` say."""
    return [replace(r, **fields) if isinstance(r, Position) and r.oz == oz else r for r in rows]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fault(
    error_id: str, oz: str, rows: dict[str, int], kind: str, category: str, difficulty: str
) -> dict[str, Any]:
    return {
        "error_id": error_id,
        "oz": oz,
        "row": rows[oz],
        "rows": [rows[oz]],
        "kind": kind,
        "finding_category": category,
        "difficulty": difficulty,
    }


# ----------------------------------------------------------------------------- one long bill


def _long_rows() -> list[Row]:
    rows: list[Row] = [("01", "Baustelleneinrichtung"), ("01.01", "Einrichten")]
    rows += positions("01.01", 5)
    rows += [("02", "Erdarbeiten"), ("02.01", "Aushub")]
    rows += positions("02.01", 5, start=1)
    rows.append(("03", "Rohrleitung"))
    for titel in ("03.01", "03.02", "03.03"):
        rows.append((titel, f"Leitungsabschnitt {titel[-1]}"))
        rows += positions(titel, 40, start=int(titel[-1]))
    for section in range(4, 14):
        code = f"{section:02d}"
        rows += [(code, f"Nebenarbeiten {code}"), (f"{code}.01", "Einzelleistungen")]
        rows += positions(f"{code}.01", 3, start=section)
    return rows


def long_bill(folder: Path) -> tuple[Path, Path, Path]:
    """The faulty long bill, its clean original and its answer key, written to ``folder``.

    The three faults: a wrong line total (02.01.0003), a quantity ten times too high whose line
    total follows (03.02.0011) and an unknown unit (05.01.0002). Position 02.01.0002 is right and
    must not be flagged."""
    folder.mkdir(parents=True, exist_ok=True)
    clean_rows = _long_rows()
    clean = folder / "long-clean.csv"
    write(clean, clean_rows)
    faulty_rows = changed(clean_rows, "02.01.0003", total=Decimal("999.00"))
    slip = next(r for r in faulty_rows if isinstance(r, Position) and r.oz == "03.02.0011")
    assert slip.quantity is not None
    faulty_rows = changed(faulty_rows, "03.02.0011", quantity=slip.quantity * 10)
    faulty_rows = changed(faulty_rows, "05.01.0002", unit="Stckx")
    faulty = folder / "long-faulty.csv"
    rows = write(faulty, faulty_rows)
    key = {
        "file": faulty.name,
        "file_sha256": _sha256(faulty),
        "planted": [
            _fault("pf-01", "02.01.0003", rows, "line_total_mismatch", "error", "easy"),
            _fault("pf-05", "03.02.0011", rows, "quantity_decimal_slip", "error", "medium"),
            _fault("pf-09", "05.01.0002", rows, "unknown_unit", "error", "easy"),
        ],
        "not_planted": [],
        "must_not_flag": [
            {"id": "ok-1", "rows": [rows["02.01.0002"]], "positions": ["02.01.0002"]}
        ],
    }
    key_path = folder / "long-faulty-answer-key.json"
    key_path.write_text(json.dumps(key, indent=1), encoding="utf-8")
    return faulty, clean, key_path


# ----------------------------------------------------------------------------- practice set

BASES = ("alpha", "bravo", "charlie", "delta")


def _practice_rows(base: int) -> list[Row]:
    rows: list[Row] = []
    for section in (1, 2):
        code = f"{section:02d}"
        rows += [(code, f"Abschnitt {code}"), (f"{code}.01", "Leistungen")]
        rows += positions(f"{code}.01", 8, start=base * 3 + section)
    return rows


def _variant(rows: list[Row], number: int) -> tuple[list[Row], list[tuple[str, str, str, str]]]:
    """A faulty copy: (rows, faults as (OZ, kind, category, difficulty))."""
    if number == 1:
        faults = [
            ("01.01.0002", "line_total_mismatch", "error", "easy"),
            ("02.01.0004", "unknown_unit", "error", "medium"),
            ("02.01.0007", "quantity_decimal_slip", "error", "hard"),
        ]
        rows = changed(rows, "01.01.0002", total=Decimal("1.00"))
        rows = changed(rows, "02.01.0004", unit="Stckx")
    else:
        faults = [
            ("01.01.0005", "missing_quantity", "omission", "easy"),
            ("02.01.0002", "line_total_mismatch", "error", "easy"),
            ("01.01.0007", "price_decimal_slip", "error", "hard"),
        ]
        rows = changed(rows, "01.01.0005", quantity=None, total=Decimal("100.00"))
        rows = changed(rows, "02.01.0002", total=Decimal("2.00"))
    slipped = faults[2][0]
    position = next(r for r in rows if isinstance(r, Position) and r.oz == slipped)
    if number == 1:
        assert position.quantity is not None
        rows = changed(rows, slipped, quantity=position.quantity * 10)
    else:
        rows = changed(rows, slipped, price=position.price * 10)
    return rows, faults


def practice_folder(folder: Path) -> Path:
    """A practice benchmark of 4 clean bills and 8 faulty copies with their keys in ``folder``."""
    (folder / "input").mkdir(parents=True, exist_ok=True)
    (folder / "out").mkdir(exist_ok=True)
    for index, base in enumerate(BASES):
        rows = _practice_rows(index)
        write(folder / "input" / f"{base}-clean.csv", rows)
        for number in (1, 2):
            faulty_rows, faults = _variant(rows, number)
            faulty = folder / "out" / f"{base}-v{number}.csv"
            numbers = write(faulty, faulty_rows)
            key = {
                "file": faulty.name,
                "clean_file": f"../input/{base}-clean.csv",
                "file_sha256": _sha256(faulty),
                "planted": [
                    _fault(f"{base}-{number}-{n}", oz, numbers, kind, category, difficulty)
                    for n, (oz, kind, category, difficulty) in enumerate(faults, 1)
                ],
                "not_planted": [],
                "must_not_flag": [{"control_id": "ok-1", "rows": [numbers["01.01.0001"]]}],
            }
            path = folder / "out" / f"{base}-v{number}-answer-key.json"
            path.write_text(json.dumps(key, indent=1), encoding="utf-8")
    return folder
