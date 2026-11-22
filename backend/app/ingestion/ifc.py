"""Read a model's quantities per bill position from an IFC file (ISO 10303-21, any schema).

Only what the takeoff needs is read, without a schema library: the project's SI units, the
elements' base quantities (IfcRelDefinesByProperties -> IfcElementQuantity -> IfcQuantity*)
and their links to bill positions (IfcRelAssociatesClassification ->
IfcClassificationReference, whose identification is the item number). The attribute positions
used are the same in IFC2X3, IFC4 and IFC4X3. Geometry is not read: a quantity the model does
not state is not computed from shapes.

Which quantity counts, when an element states several of one kind: net before plain before
gross (NetVolume, then Volume, then GrossVolume). Lengths are taken only from quantities named
like a length (Length, NetLength, GrossLength), never from Width or Height.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.errors import InvalidInputError
from app.models.model_takeoff import ModelTakeoff, PositionTakeoff

_HEADER = b"ISO-10303-21;"
_SCHEMA = re.compile(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'")
_RECORD = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(", re.S)

_PREFIX = {
    "EXA": Decimal("1e18"),
    "PETA": Decimal("1e15"),
    "TERA": Decimal("1e12"),
    "GIGA": Decimal("1e9"),
    "MEGA": Decimal("1e6"),
    "KILO": Decimal("1e3"),
    "HECTO": Decimal("1e2"),
    "DECA": Decimal("1e1"),
    "DECI": Decimal("1e-1"),
    "CENTI": Decimal("1e-2"),
    "MILLI": Decimal("1e-3"),
    "MICRO": Decimal("1e-6"),
}
# IfcSIUnit unit type -> (takeoff dimension, power of the prefix)
_UNIT_TYPES = {"LENGTHUNIT": ("length", 1), "AREAUNIT": ("area", 2), "VOLUMEUNIT": ("volume", 3)}
_QUANTITY_KIND = {
    "IFCQUANTITYLENGTH": "length",
    "IFCQUANTITYAREA": "area",
    "IFCQUANTITYVOLUME": "volume",
    "IFCQUANTITYWEIGHT": "mass",
    "IFCQUANTITYCOUNT": "count",
}
_PREFERRED = {
    "length": ("NETLENGTH", "LENGTH", "GROSSLENGTH"),
    "area": ("NETAREA", "NETSURFACEAREA", "AREA", "GROSSAREA", "GROSSSURFACEAREA"),
    "volume": ("NETVOLUME", "VOLUME", "GROSSVOLUME"),
    "mass": ("NETWEIGHT", "WEIGHT", "GROSSWEIGHT"),
}


@dataclass(frozen=True, slots=True)
class _Ref:
    id: int


@dataclass(frozen=True, slots=True)
class _Enum:
    value: str


def read_takeoff(data: bytes, *, filename: str) -> ModelTakeoff:
    """The takeoff of an IFC file. Raises :class:`InvalidInputError` when the bytes are not an
    IFC STEP file."""
    if not data.lstrip().startswith(_HEADER):
        raise InvalidInputError("The model is not an IFC file (ISO 10303-21 STEP).")
    schema_match = _SCHEMA.search(data[:4096])
    schema = schema_match.group(1).decode("ascii", "replace") if schema_match else ""
    if not schema.upper().startswith("IFC"):
        raise InvalidInputError("The STEP file does not declare an IFC schema.")
    text = data.decode("utf-8", "replace")
    start = text.find("DATA;")
    if start < 0:
        raise InvalidInputError("The IFC file has no DATA section.")
    file = _StepFile(text[start + 5 :])
    return _Takeoff(file).build(hashlib.sha256(data).hexdigest(), filename, schema)


class _StepFile:
    """Records by id; arguments are parsed when first asked for."""

    def __init__(self, body: str) -> None:
        self.types: dict[int, str] = {}
        self._raw: dict[int, str] = {}
        self._parsed: dict[int, list[object]] = {}
        for record_id, entity, args in _records(body):
            self.types[record_id] = entity
            self._raw[record_id] = args

    def args(self, record_id: int) -> list[object]:
        parsed = self._parsed.get(record_id)
        if parsed is None:
            raw = self._raw.get(record_id)
            parsed = _Parser(raw).arguments() if raw is not None else []
            self._parsed[record_id] = parsed
        return parsed

    def of_type(self, entity: str) -> Iterator[int]:
        return (i for i, t in self.types.items() if t == entity)


class _Takeoff:
    def __init__(self, file: _StepFile) -> None:
        self.file = file
        self.scale = self._units()

    def build(self, sha256: str, filename: str, schema: str) -> ModelTakeoff:
        f = self.file
        quantities: dict[int, dict[str, Decimal]] = {}
        for rel in f.of_type("IFCRELDEFINESBYPROPERTIES"):
            args = f.args(rel)
            definition = _arg(args, 5)
            if not isinstance(definition, _Ref):
                continue
            if f.types.get(definition.id) != "IFCELEMENTQUANTITY":
                continue
            stated = self._element_quantities(definition.id)
            for obj in _refs(_arg(args, 4)):
                merged = quantities.setdefault(obj.id, {})
                for kind, value in stated.items():
                    merged.setdefault(kind, value)
        links: dict[int, list[str]] = {}
        reference_names: dict[str, str] = {}
        for rel in f.of_type("IFCRELASSOCIATESCLASSIFICATION"):
            args = f.args(rel)
            reference = _arg(args, 5)
            if not isinstance(reference, _Ref):
                continue
            if f.types.get(reference.id) != "IFCCLASSIFICATIONREFERENCE":
                continue
            reference_args = f.args(reference.id)
            code = _arg(reference_args, 1)
            if not isinstance(code, str) or not code.strip():
                continue
            name = _arg(reference_args, 2)
            if isinstance(name, str) and name.strip():
                reference_names.setdefault(code.strip(), name.strip())
            for obj in _refs(_arg(args, 4)):
                links.setdefault(obj.id, []).append(code.strip())
        elements = set(quantities) | set(links)
        grouped: dict[str, list[int]] = {}
        for element in sorted(links):
            for code in dict.fromkeys(links[element]):
                grouped.setdefault(code, []).append(element)
        positions = {
            code: self._position(code, members, quantities, reference_names.get(code))
            for code, members in grouped.items()
        }
        project = next(f.of_type("IFCPROJECT"), None)
        name = _arg(f.args(project), 2) if project is not None else None
        return ModelTakeoff(
            sha256=sha256,
            filename=filename,
            schema=schema,
            project=name if isinstance(name, str) else None,
            elements=len(elements),
            unlinked_elements=len(elements - set(links)),
            positions=positions,
        )

    def _position(
        self,
        code: str,
        members: list[int],
        quantities: dict[int, dict[str, Decimal]],
        reference_name: str | None,
    ) -> PositionTakeoff:
        f = self.file
        totals: dict[str, Decimal] = {}
        for kind in ("length", "area", "volume", "mass"):
            values = [quantities.get(m, {}).get(kind) for m in members]
            if all(v is not None for v in values):
                totals[kind] = sum((v for v in values if v is not None), Decimal(0))
        counts = [quantities.get(m, {}).get("count") for m in members]
        totals["count"] = (
            sum((c for c in counts if c is not None), Decimal(0))
            if all(c is not None for c in counts)
            else Decimal(len(members))
        )
        names = [_arg(f.args(m), 2) for m in members]
        return PositionTakeoff(
            item_code=code,
            elements=len(members),
            global_ids=tuple(str(_arg(f.args(m), 0)) for m in members),
            entity_types=tuple(sorted({f.types[m] for m in members})),
            names=tuple(dict.fromkeys(n for n in names if isinstance(n, str))),
            quantities=totals,
            reference_name=reference_name,
        )

    def _element_quantities(self, quantity_set: int) -> dict[str, Decimal]:
        f = self.file
        found: dict[str, dict[str, Decimal]] = {}
        for ref in _refs(_arg(f.args(quantity_set), 5)):
            kind = _QUANTITY_KIND.get(f.types.get(ref.id, ""))
            if kind is None:
                continue
            args = f.args(ref.id)
            name, value = _arg(args, 0), _number(_arg(args, 3))
            if not isinstance(name, str) or value is None:
                continue
            factor = self._unit_factor(kind, _arg(args, 2))
            found.setdefault(kind, {}).setdefault(name.upper(), value * factor)
        chosen: dict[str, Decimal] = {}
        for kind, by_name in found.items():
            if kind == "count":
                chosen[kind] = next(iter(by_name.values()))
                continue
            for name in _PREFERRED[kind]:
                if name in by_name:
                    chosen[kind] = by_name[name]
                    break
        return chosen

    def _unit_factor(self, kind: str, own_unit: object) -> Decimal:
        if isinstance(own_unit, _Ref):
            unit = self._si_unit(own_unit.id)
            if unit is not None and unit[0] == kind:
                return unit[1]
        return self.scale.get(kind, Decimal(1))

    def _units(self) -> dict[str, Decimal]:
        """Conversion of the project's units to the takeoff's base units."""
        f = self.file
        scale: dict[str, Decimal] = {}
        assignments = list(f.of_type("IFCUNITASSIGNMENT"))
        candidates = (
            [r.id for a in assignments for r in _refs(_arg(f.args(a), 0))]
            if assignments
            else list(f.of_type("IFCSIUNIT"))
        )
        for unit_id in candidates:
            unit = self._si_unit(unit_id)
            if unit is not None:
                scale.setdefault(unit[0], unit[1])
        return scale

    def _si_unit(self, unit_id: int) -> tuple[str, Decimal] | None:
        f = self.file
        if f.types.get(unit_id) != "IFCSIUNIT":
            return None
        args = f.args(unit_id)
        unit_type, prefix = _arg(args, 1), _arg(args, 2)
        if not isinstance(unit_type, _Enum):
            return None
        factor = _PREFIX.get(prefix.value, Decimal(1)) if isinstance(prefix, _Enum) else Decimal(1)
        if unit_type.value == "MASSUNIT":  # base unit gram; the takeoff counts kilograms
            return ("mass", factor / Decimal(1000))
        known = _UNIT_TYPES.get(unit_type.value)
        if known is None:
            return None
        return (known[0], factor ** known[1])


def _arg(args: list[object], index: int) -> object:
    return args[index] if index < len(args) else None


def _refs(value: object) -> list[_Ref]:
    return [v for v in value if isinstance(v, _Ref)] if isinstance(value, list) else []


def _number(value: object) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    return None


def _records(body: str) -> Iterator[tuple[int, str, str]]:
    """``(id, ENTITY, argument text)`` of every instance, skipping comments."""
    i, n = 0, len(body)
    while i < n:
        match = _RECORD.search(body, i)
        if match is None:
            return
        comment = body.find("/*", i, match.start())
        if comment >= 0:  # between records; a comment may itself look like a record
            end = body.find("*/", comment + 2)
            i = n if end < 0 else end + 2
            continue
        j = match.end()
        depth, in_string = 1, False
        while j < n and depth:
            ch = body[j]
            if in_string:
                if ch == "'":
                    if j + 1 < n and body[j + 1] == "'":
                        j += 1
                    else:
                        in_string = False
            elif ch == "'":
                in_string = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        yield int(match.group(1)), match.group(2).upper(), body[match.end() : j - 1]
        i = j


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0

    def arguments(self) -> list[object]:
        values: list[object] = []
        while True:
            self._space()
            if self.i >= len(self.text):
                return values
            values.append(self._value())
            self._space()
            if self.i < len(self.text) and self.text[self.i] == ",":
                self.i += 1

    def _space(self) -> None:
        while self.i < len(self.text) and self.text[self.i] in " \t\r\n":
            self.i += 1

    def _value(self) -> object:
        t, i = self.text, self.i
        ch = t[i]
        if ch in "$*":
            self.i += 1
            return None
        if ch == "#":
            j = i + 1
            while j < len(t) and t[j].isdigit():
                j += 1
            self.i = j
            return _Ref(int(t[i + 1 : j]))
        if ch == "'":
            return self._string()
        if ch == ".":
            j = t.index(".", i + 1)
            self.i = j + 1
            return _Enum(t[i + 1 : j])
        if ch == "(":
            self.i += 1
            items: list[object] = []
            while True:
                self._space()
                if t[self.i] == ")":
                    self.i += 1
                    return items
                items.append(self._value())
                self._space()
                if t[self.i] == ",":
                    self.i += 1
        if ch.isalpha():  # typed value such as IFCLENGTHMEASURE(2.5)
            j = i
            while t[j] != "(":
                j += 1
            self.i = j + 1
            self._space()
            inner = self._value()
            self._space()
            self.i += 1  # ")"
            return inner
        j = i
        while j < len(t) and t[j] not in ",) \t\r\n":
            j += 1
        self.i = j
        try:
            return Decimal(t[i:j])
        except InvalidOperation:
            return None

    def _string(self) -> str:
        t = self.text
        j = self.i + 1
        out: list[str] = []
        while j < len(t):
            if t[j] == "'":
                if j + 1 < len(t) and t[j + 1] == "'":
                    out.append("'")
                    j += 2
                    continue
                break
            out.append(t[j])
            j += 1
        self.i = j + 1
        return _decode("".join(out))


_X2 = re.compile(r"\\X2\\((?:[0-9A-Fa-f]{4})+)\\X0\\")
_X = re.compile(r"\\X\\([0-9A-Fa-f]{2})")


def _decode(value: str) -> str:
    """STEP string escapes: \\X2\\...\\X0\\ (UTF-16) and \\X\\hh (ISO 8859-1)."""
    if "\\" not in value:
        return value
    value = _X2.sub(lambda m: bytes.fromhex(m.group(1)).decode("utf-16-be", "replace"), value)
    value = _X.sub(lambda m: bytes.fromhex(m.group(1)).decode("latin-1"), value)
    return value.replace("\\\\", "\\")
