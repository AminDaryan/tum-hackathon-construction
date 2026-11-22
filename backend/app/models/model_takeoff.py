"""Quantities of a building or infrastructure model (IFC), per bill position.

A model links its elements to bill positions the way 5D tools do: an element carries a
classification reference whose identification is the position's item number (OZ). The takeoff
sums the base quantities (IfcElementQuantity) of the elements linked to each item number, in
SI base units: metres, square metres, cubic metres, kilograms and pieces. Built by
:func:`app.ingestion.ifc.read_takeoff`; checks read it through
``ValidationContext.model`` and never see the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PositionTakeoff:
    """The model elements linked to one item number, and their summed quantities.

    A dimension is in ``quantities`` only when every linked element states it, so a partial
    sum is never compared. ``count`` is the summed IfcQuantityCount when every element states
    one, else the number of elements."""

    item_code: str
    elements: int
    global_ids: tuple[str, ...]
    entity_types: tuple[str, ...]
    names: tuple[str, ...]
    quantities: dict[str, Decimal]
    # The position's short text as the link names it (IfcClassificationReference.Name).
    reference_name: str | None = None


@dataclass(frozen=True, slots=True)
class ModelTakeoff:
    sha256: str
    filename: str
    schema: str  # FILE_SCHEMA, e.g. IFC4X3_ADD2
    project: str | None
    elements: int  # elements with quantities or a position link
    unlinked_elements: int  # elements without a position link
    positions: dict[str, PositionTakeoff]  # by item code as the model writes it

    def summary(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "filename": self.filename,
            "schema": self.schema,
            "project": self.project,
            "elements": self.elements,
            "unlinked_elements": self.unlinked_elements,
            "linked_positions": len(self.positions),
        }


def text_key(text: str) -> str:
    """A short text compared case- and space-insensitively."""
    return " ".join(text.casefold().split())


def same_text(a: str, b: str) -> bool:
    """Equal short texts; a text cut off at a field width matches its full form when at least
    30 characters remain."""
    a, b = text_key(a), text_key(b)
    shorter, longer = sorted((a, b), key=len)
    return a == b or (len(shorter) >= 30 and longer.startswith(shorter))


def code_key(code: str) -> tuple[object, ...]:
    """Item numbers compared by their parts, so 03.02.0009, 3.2.9 and "03 02 0009" match."""
    parts = [p for p in code.replace(" ", ".").split(".") if p]
    return tuple(int(p) if p.isdigit() else p.upper() for p in parts)
