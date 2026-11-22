"""Unit vocabulary lookups derived from a profile.

Unit text is matched through a normalization key: Unicode NFKC (so ``m²`` becomes ``m2``),
case folding, multiplication signs folded to ``x`` (``m² · Wo`` and ``m2 × Wo`` both become
``m2xwo``), and removal of spaces, dots and ``^`` (``lfd. m`` -> ``lfdm``, ``l.s.`` -> ``ls``).
The original cell text is never changed; normalization only produces ``Cell.normalized_value``.

A leading numeric multiplier ("100 St", "1000 kg": the price is per 100 pieces) is recognized
by :meth:`UnitCatalog.lookup` and reported separately, so checks that multiply quantity by price
can abstain instead of reporting a hundredfold "error".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.errors import ProfileError
from app.models.profile import DomainProfile, UnitDefinition

_MULTIPLICATION_SIGNS = str.maketrans({"·": "x", "×": "x", "*": "x", "⋅": "x"})
_REMOVED = (" ", ".", " ", "^")
_MULTIPLIER = re.compile(r"^\s*(\d{1,7}(?:[.,]\d{1,3})?)\s*([^\d\s.,].{0,40})$")
_MAX_UNIT_CHARS = 64


def unit_key(text: str) -> str:
    """Normalization key used for alias matching."""
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    normalized = normalized.translate(_MULTIPLICATION_SIGNS)
    for char in _REMOVED:
        normalized = normalized.replace(char, "")
    return normalized


@dataclass(frozen=True, slots=True)
class UnitLookup:
    """A resolved unit. ``multiplier`` is the leading number of texts such as "100 St"
    (``None`` when the unit text has none)."""

    unit: UnitDefinition
    multiplier: Decimal | None = None


class UnitCatalog:
    """Maps unit aliases to canonical :class:`UnitDefinition` entries."""

    def __init__(self, units: list[UnitDefinition]) -> None:
        self._units = {u.unit_id: u for u in units}
        self._by_key: dict[str, UnitDefinition] = {}
        for unit in units:
            for alias in {unit.unit_id, *unit.aliases}:
                key = unit_key(alias)
                if not key:
                    continue
                existing = self._by_key.get(key)
                if existing is not None and existing.unit_id != unit.unit_id:
                    raise ProfileError(
                        f"Unit alias {alias!r} maps to both {existing.unit_id!r} "
                        f"and {unit.unit_id!r}"
                    )
                self._by_key[key] = unit

    @classmethod
    def from_profile(cls, profile: DomainProfile) -> UnitCatalog:
        return cls(profile.units)

    @property
    def is_empty(self) -> bool:
        return not self._units

    def resolve(self, text: str | None) -> UnitDefinition | None:
        """Canonical unit for ``text`` (without a numeric multiplier), or ``None`` when the
        text is not in the vocabulary."""
        if not text or len(text) > _MAX_UNIT_CHARS:
            return None
        return self._by_key.get(unit_key(text))

    def lookup(self, text: str | None) -> UnitLookup | None:
        """Like :meth:`resolve`, but also accepts a leading multiplier ("100 St")."""
        unit = self.resolve(text)
        if unit is not None:
            return UnitLookup(unit)
        if not text or len(text) > _MAX_UNIT_CHARS:
            return None
        found = _MULTIPLIER.match(unicodedata.normalize("NFKC", text))
        if not found:
            return None
        base = self.resolve(found.group(2))
        if base is None:
            return None
        try:
            multiplier = Decimal(found.group(1).replace(",", "."))
        except InvalidOperation:  # pragma: no cover - the pattern only admits digits
            return None
        return UnitLookup(base, multiplier if multiplier > 0 else None)

    def get(self, unit_id: str) -> UnitDefinition | None:
        return self._units.get(unit_id)

    def units(self) -> list[UnitDefinition]:
        return list(self._units.values())
