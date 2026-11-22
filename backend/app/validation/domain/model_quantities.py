"""Bill against model: quantities of the attached IFC model compared with the bill's.

A model (IFC) attached to the document (``PUT /documents/{id}/model``) links its elements to
bill positions by item number (``app.ingestion.ifc``). On item rows:

* ``model_quantity_mismatch``: the bill's quantity differs from the summed base quantities of
  the elements linked to its item number by more than the tolerance (pieces: by any number) ->
  confirmed rule violation, with the money at stake (the difference times the unit price).
  Severity by the relative difference. A wrong quantity whose line total was recomputed to
  match is consistent within the bill, so no check of the bill alone can find it; the model
  can. Which of the two is right, the bill or the model, a reviewer decides.
* ``model_unit_mismatch``: the model measures the position's work in another dimension than
  the bill's unit (m² in the model, m in the bill) -> confirmed rule violation.
* ``model_position_missing``: the model has elements for an item number the bill has no
  position for -> omission: work the design contains that no position prices. Reported on the
  section the number belongs to when the bill has it.
* ``model_position_renumbered``: such an item number's short text (as the model's link names
  it) is priced in the bill under another number that the model does not know -> the position
  moved or was renumbered; reported on that row instead of the omission.
* ``model_work_priced_twice``: a position the model does not know has the short text of a
  model position in the same section that the bill also prices -> the same work priced twice,
  with the second position's line total at stake. Repeats in other sections are not reported:
  bills repeat work per lot or area on purpose, and models leave positions unlinked.

The model is compared in the position's unit only when that unit has a dimension the takeoff
measures (length, area, volume, mass, pieces) and every linked element states the quantity;
other rows are counted in the coverage, never guessed. Positions without model elements are not
reported: a design model leaves out site setup, hire periods, services and lump sums.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from app.models.dataset import Row, RowKind, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    Severity,
    ValidationIssue,
)
from app.models.model_takeoff import ModelTakeoff, PositionTakeoff, code_key, same_text
from app.models.values import DataType
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import RoundingSpec
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.contracts.issue_factory import money_impact
from app.validation.deterministic._reference_support import clip, short_digest
from app.validation.deterministic._support import field_label, fmt, row_guard

RULE_MISMATCH = "model_quantity_mismatch"
RULE_MISSING = "model_position_missing"
RULE_UNIT = "model_unit_mismatch"
RULE_RENUMBERED = "model_position_renumbered"
RULE_TWICE = "model_work_priced_twice"
CATEGORY = "model_quantity"

ROWS_COMPARED = "rows_compared_with_model"
ROWS_NOT_IN_MODEL = "rows_without_model_elements"
ROWS_UNIT_NOT_COMPARED = "rows_unit_not_measured_by_model"
ROWS_QUANTITY_NOT_STATED = "rows_model_quantity_not_stated"
CODES_NOT_IN_BILL = "model_item_numbers_not_in_bill"

# Units of the profile -> (takeoff dimension, factor to the takeoff's base unit)
_BASE: dict[str, tuple[str, Decimal]] = {
    "m": ("length", Decimal(1)),
    "m2": ("area", Decimal(1)),
    "m3": ("volume", Decimal(1)),
    "l": ("volume", Decimal("0.001")),
    "kg": ("mass", Decimal(1)),
    "t": ("mass", Decimal(1000)),
    "pcs": ("count", Decimal(1)),
    "pr": ("count", Decimal(2)),
}
_SHOWN = Decimal("0.001")
_BASE_UNIT = {"length": "m", "area": "m²", "volume": "m³", "mass": "kg", "count": "pcs"}


class ModelQuantitiesConfig(DetectorConfig):
    tolerance: Decimal = Field(
        default=Decimal("0.05"),
        ge=0,
        le=1,
        description=(
            "Relative difference allowed between the bill's and the model's measured quantity "
            "(a bill rounds its quantities, and measurement rules differ from net geometry)."
        ),
    )
    high_from: Decimal = Field(default=Decimal("0.5"), gt=0, description="High severity from.")
    medium_from: Decimal = Field(default=Decimal("0.15"), gt=0, description="Medium severity from.")
    max_global_ids: int = Field(default=20, ge=1, le=200, description="Element ids listed.")


@dataclass(frozen=True, slots=True)
class _Item:
    table: Table
    row: Row
    code: str
    text: str | None = None


class ModelQuantitiesDetector(Detector[ModelQuantitiesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.model_quantities",
        name="Bill against model quantities (IFC)",
        version="1.0.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Compares each position's quantity with the base quantities of the elements an "
            "attached IFC model links to its item number, and reports item numbers the model "
            "has but the bill does not. Finds wrong quantities whose totals add up, which no "
            "check of the bill alone can see."
        ),
        required_fields=("item_code", "quantity", "unit"),
        optional_fields=("unit_price", "discount_percent", "currency"),
        supported_data_types=(DataType.TEXT, DataType.NUMBER),
        applicability=(
            "Bills with an attached IFC model whose elements carry classification references "
            "with the item numbers."
        ),
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(CATEGORY,),
        limitations=(
            "Elements are linked to positions only by item number (classification reference); "
            "no text or geometry matching.",
            "Quantities are the model's stated base quantities; geometry is not measured.",
            "A difference says the bill and the model disagree, not which one is wrong; "
            "measurement rules (for example VOB/C deductions) can explain small ones.",
            "Positions the model does not contain are not reported.",
            "Measured only with a test model generated from the bill itself (an upper bound); "
            "the 5 % tolerance has not been checked against an independent design model.",
        ),
        references=("ISO 16739-1 (IFC): IfcElementQuantity, IfcRelAssociatesClassification",),
        cost="low",
    )
    config_model = ModelQuantitiesConfig

    def applicability(
        self, context: ValidationContext, config: ModelQuantitiesConfig
    ) -> Applicability:
        if context.model is None:
            return Applicability.no("No model (IFC) is attached to this bill.")
        tables = [t.name for t in context.tables() if context.has_fields(t, "item_code")]
        if not tables:
            return Applicability.no("No table maps the item number.")
        return Applicability.yes(
            f"Model {context.model.filename}: {len(context.model.positions)} item numbers "
            f"linked; compared with {', '.join(tables)}."
        )

    def validate(self, context: ValidationContext, config: ModelQuantitiesConfig) -> DetectorResult:
        model = context.model
        assert model is not None  # applicability
        result = DetectorResult()
        by_key = {code_key(code): position for code, position in model.positions.items()}
        seen: set[tuple[object, ...]] = set()
        sections: list[_Item] = []
        unlinked: list[_Item] = []
        for table in context.tables():
            if not context.has_fields(table, "item_code"):
                continue
            for row in context.rows(table, kinds=None):
                code = context.text(table, row, "item_code")
                if not code:
                    continue
                if row.kind is RowKind.SECTION:
                    sections.append(_Item(table, row, code))
                    continue
                if row.kind is not RowKind.ITEM:
                    continue
                key = code_key(code)
                position = by_key.get(key)
                if position is None:
                    result.count(ROWS_NOT_IN_MODEL)
                    text = context.text(table, row, "description")
                    unlinked.append(_Item(table, row, code, text))
                    continue
                seen.add(key)
                with row_guard(result, table, row):
                    issue = self._compare(context, config, table, row, position, result)
                    if issue is not None:
                        result.add(issue)
        claimed: set[int] = set()
        for key, position in by_key.items():
            if key in seen:
                continue
            context.checkpoint()
            result.count(CODES_NOT_IN_BILL)
            moved = _same_work(position, unlinked, claimed)
            if moved is not None:
                claimed.add(id(moved))
                result.add(self._renumbered(context, position, moved, sections))
            else:
                result.add(self._missing(context, config, model, position, key, sections))
        linked = [p for k, p in by_key.items() if k in seen]
        for item in unlinked:
            if id(item) in claimed or not item.text:
                continue
            # Bills repeat the same work in other sections (another lot or area) on purpose,
            # and a model may leave a position unlinked, so only a repeat in the same section
            # counts as priced twice.
            parent = code_key(item.code)[:-1]
            twin = next(
                (
                    p
                    for p in linked
                    if p.reference_name
                    and code_key(p.item_code)[:-1] == parent
                    and same_text(p.reference_name, item.text)
                ),
                None,
            )
            if twin is not None:
                result.add(self._twice(context, item, twin))
        result.notes.append(
            f"Compared with model {model.filename} ({model.schema}, {model.elements} elements, "
            f"{model.unlinked_elements} without an item number)."
        )
        return result

    def _compare(
        self,
        context: ValidationContext,
        config: ModelQuantitiesConfig,
        table: Table,
        row: Row,
        position: PositionTakeoff,
        result: DetectorResult,
    ) -> ValidationIssue | None:
        quantity = context.number(table, row, "quantity")
        lookup = context.unit(table, row)
        base = _BASE.get(lookup.unit.unit_id) if lookup is not None else None
        if quantity is None or lookup is None or base is None:
            result.count(ROWS_UNIT_NOT_COMPARED)
            return None
        dimension, factor = base
        modelled = position.quantities.get(dimension)
        if modelled is None:
            measured = sorted(d for d in position.quantities if d != "count")
            if dimension != "count" and measured:
                return self._unit_mismatch(context, table, row, position, dimension, measured)
            result.count(ROWS_QUANTITY_NOT_STATED)
            return None
        result.count(ROWS_COMPARED)
        per_unit = factor * (lookup.multiplier or Decimal(1))
        model_in_unit = modelled / per_unit
        difference = quantity - model_in_unit
        if modelled == 0:
            relative = Decimal(1) if quantity else Decimal(0)
        else:
            relative = abs(difference) / model_in_unit
        allowed = Decimal(0) if dimension == "count" else config.tolerance
        if abs(difference) < Decimal("0.0005") or relative <= allowed:
            return None
        severity = (
            Severity.HIGH
            if relative >= config.high_from
            else Severity.MEDIUM
            if relative >= config.medium_from
            else Severity.LOW
        )
        unit_text = context.text(table, row, context.unit_field_id() or "unit") or ""
        shown_model = model_in_unit.quantize(_SHOWN).normalize()
        shown_diff = difference.quantize(_SHOWN).normalize()
        price = context.number(table, row, "unit_price")
        discount = context.number(table, row, "discount_percent")
        currency = context.currency_evidence(table, row, ["unit_price", "line_total"])
        impact = None
        if price is not None and currency:
            factor_discount = Decimal(1) - (discount or Decimal(0)) / Decimal(100)
            impact = money_impact(
                RoundingSpec().apply(difference * price * factor_discount),
                currency,
                "(bill quantity − model quantity) × unit price",
                reported=quantity,
                recomputed=shown_model,
            )
        quantity_label = field_label(context, "quantity")
        ids = ", ".join(position.global_ids[: config.max_global_ids])
        more = len(position.global_ids) - config.max_global_ids
        direction = "more" if difference > 0 else "less"
        types = ", ".join(t.removeprefix("IFC").title() for t in position.entity_types)
        return context.issues.create(
            self.spec,
            rule_id=RULE_MISMATCH,
            category=CATEGORY,
            severity=severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(
                f"Bill says {fmt(quantity)} {unit_text}, model gives {fmt(shown_model)} "
                f"{unit_text}: {position.item_code}",
                200,
            ),
            explanation=(
                f"The bill's {quantity_label} of {position.item_code} is {fmt(quantity)} "
                f"{unit_text}. The {position.elements} model element"
                f"{'' if position.elements == 1 else 's'} linked to this item number measure "
                f"{fmt(shown_model)} {unit_text}, so the bill holds {fmt(abs(shown_diff))} "
                f"{unit_text} {direction} ({_percent(relative)}). A quantity that is wrong but "
                "carried into its line total and the sums leaves the bill consistent in "
                "itself; the model shows it. Either the bill or the model may be wrong; "
                "measurement rules can explain a small difference."
            ),
            table=table,
            row=row,
            cells=[context.cell_ref(table, row, "quantity")],
            observed_value=fmt(quantity),
            expected_value=fmt(shown_model),
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Bill against model",
                    detail=(
                        f"Bill {fmt(quantity)} {unit_text}; model {fmt(shown_model)} "
                        f"{unit_text} from {position.elements} element"
                        f"{'' if position.elements == 1 else 's'} "
                        f"({types}); difference {fmt(shown_diff)} {unit_text} "
                        f"({_percent(relative)}, tolerance {_percent(allowed)})."
                    ),
                    cells=[context.cell_ref(table, row, "quantity")],
                    data={
                        "bill": fmt(quantity),
                        "model": fmt(shown_model),
                        "difference": fmt(shown_diff),
                        "elements": position.elements,
                    },
                ),
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Model elements (IFC GlobalId)",
                    detail=ids + (f" and {more} more" if more > 0 else ""),
                ),
            ],
            suggested_action=(
                "Check the quantity against the drawings and the model; correct the bill, or "
                "ask the designer to correct the model."
            ),
            financial_impact=impact,
            subject=short_digest(position.item_code),
        )

    def _missing(
        self,
        context: ValidationContext,
        config: ModelQuantitiesConfig,
        model: ModelTakeoff,
        position: PositionTakeoff,
        key: tuple[object, ...],
        sections: list[_Item],
    ) -> ValidationIssue:
        section = _section_for(key, sections)
        names = "; ".join(position.names[:3]) or "no name"
        ids = ", ".join(position.global_ids[: config.max_global_ids])
        place = (
            f"Section {section.code} has no position {position.item_code}."
            if section is not None
            else f"The bill has no position {position.item_code}."
        )
        return context.issues.create(
            self.spec,
            rule_id=RULE_MISSING,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Model has work for {position.item_code} that the bill lacks", 200),
            explanation=(
                f"The model {model.filename} has {position.elements} element"
                f"{'' if position.elements == 1 else 's'} linked to item number "
                f"{position.item_code} ({clip(names, 300)}). {place} Work the design contains "
                "that no position prices is not paid for, or becomes a change order. The item "
                "number may also have moved or be written differently in the bill."
            ),
            table=section.table if section is not None else None,
            row=section.row if section is not None else None,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Model elements (IFC GlobalId)",
                    detail=ids,
                    data={
                        "item_number": position.item_code,
                        "elements": position.elements,
                        **{
                            k: fmt(v.quantize(_SHOWN).normalize())
                            for k, v in position.quantities.items()
                        },
                    },
                ),
            ],
            suggested_action=(
                "Check whether the bill must price this work: add the position, or confirm "
                "where else it is paid for."
            ),
            subject=f"missing:{short_digest(position.item_code)}",
        )

    def _unit_mismatch(
        self,
        context: ValidationContext,
        table: Table,
        row: Row,
        position: PositionTakeoff,
        dimension: str,
        measured: list[str],
    ) -> ValidationIssue:
        unit_field = context.unit_field_id() or "unit"
        unit_text = context.text(table, row, unit_field) or "?"
        stated = ", ".join(
            f"{fmt(position.quantities[d].quantize(_SHOWN).normalize())} {_BASE_UNIT[d]}"
            for d in measured
        )
        cell = context.cell_ref(table, row, unit_field)
        return context.issues.create(
            self.spec,
            rule_id=RULE_UNIT,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(
                f"Bill measures {position.item_code} in {unit_text}, the model in "
                f"{', '.join(_BASE_UNIT[d] for d in measured)}",
                200,
            ),
            explanation=(
                f"The bill measures {position.item_code} in {unit_text} ({dimension}); the "
                f"model elements linked to it state {stated} and no {dimension}. One of the "
                "two measures the work in the wrong unit, and the quantity or the unit price "
                "may be wrong with it."
            ),
            table=table,
            row=row,
            cells=[cell],
            observed_value=unit_text,
            expected_value=", ".join(_BASE_UNIT[d] for d in measured),
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Unit against model",
                    detail=f"Bill: {unit_text}; model: {stated}.",
                    cells=[cell],
                ),
            ],
            suggested_action="Check the unit of the position against the drawings and model.",
            subject=f"unit:{short_digest(position.item_code)}",
        )

    def _renumbered(
        self,
        context: ValidationContext,
        position: PositionTakeoff,
        item: _Item,
        sections: list[_Item],
    ) -> ValidationIssue:
        section = _section_for(code_key(item.code), sections)
        where = f" in section {section.code}" if section is not None else ""
        cell = context.cell_ref(item.table, item.row, "item_code")
        return context.issues.create(
            self.spec,
            rule_id=RULE_RENUMBERED,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Model's {position.item_code} is priced as {item.code}", 200),
            explanation=(
                f"The model links {position.elements} element"
                f"{'' if position.elements == 1 else 's'} to {position.item_code} "
                f"('{clip(position.reference_name or '', 200)}'). The bill has no "
                f"{position.item_code}, but prices the same short text as {item.code}{where}, "
                "a number the model does not know. The position was moved or renumbered: "
                "check that it sits in the right section and that the bill and the model "
                "refer to the same work."
            ),
            table=item.table,
            row=item.row,
            cells=[cell],
            observed_value=item.code,
            expected_value=position.item_code,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Item number against model",
                    detail=f"Bill {item.code}; model {position.item_code}; same short text.",
                    cells=[cell],
                ),
            ],
            suggested_action=(
                f"Move the position back to {position.item_code}, or update the model's link."
            ),
            subject=f"moved:{short_digest(position.item_code)}",
        )

    def _twice(
        self, context: ValidationContext, item: _Item, twin: PositionTakeoff
    ) -> ValidationIssue:
        total = context.number(item.table, item.row, "line_total")
        currency = context.currency_evidence(item.table, item.row, ["line_total", "unit_price"])
        impact = None
        if total is not None and currency:
            impact = money_impact(
                total,
                currency,
                "line total of the second position",
                kind="potential_double_count",
            )
        cell = context.cell_ref(item.table, item.row, "item_code")
        return context.issues.create(
            self.spec,
            rule_id=RULE_TWICE,
            category=CATEGORY,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{item.code} prices the model's {twin.item_code} a second time", 200),
            explanation=(
                f"Position {item.code} has the short text of {twin.item_code} "
                f"('{clip(twin.reference_name or '', 200)}'), which the bill also prices. The "
                f"model contains this work once, as {twin.item_code}, and knows no "
                f"{item.code}. The same work may be paid twice."
            ),
            table=item.table,
            row=item.row,
            cells=[cell],
            observed_value=item.code,
            expected_value=twin.item_code,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Short text against model",
                    detail=(
                        f"{item.code} and {twin.item_code} share a short text; the model "
                        f"links {twin.elements} element{'' if twin.elements == 1 else 's'} "
                        f"to {twin.item_code} only."
                    ),
                    cells=[cell],
                ),
            ],
            suggested_action=(f"Check whether {item.code} is a different work; if not, remove it."),
            financial_impact=impact,
            subject=f"twice:{short_digest(item.code)}",
        )


def _same_work(position: PositionTakeoff, items: list[_Item], claimed: set[int]) -> _Item | None:
    if not position.reference_name:
        return None
    for item in items:
        if id(item) not in claimed and item.text and same_text(position.reference_name, item.text):
            return item
    return None


def _section_for(key: tuple[object, ...], sections: list[_Item]) -> _Item | None:
    """The deepest section whose number is a prefix of ``key``."""
    best: _Item | None = None
    best_length = 0
    for section in sections:
        prefix = code_key(section.code)
        if (
            0 < len(prefix) < len(key)
            and key[: len(prefix)] == prefix
            and len(prefix) > best_length
        ):
            best, best_length = section, len(prefix)
    return best


def _percent(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('0.1')).normalize():f} %"
