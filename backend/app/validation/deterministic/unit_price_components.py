"""Unit price components: the components of a unit price add up to it.

GAEB DA XML 3.3 (Fachdokumentation 2023-01, 4.6.5 "Aufgliederung von Einheitspreisen") lets the
client ask for each unit price split into up to six components (UPComp1 to UPComp6; in VHB
Formblatt 223 the first four are wages, materials, plant and other costs), and says: "Die Summe
der Einheitspreisanteile einer Position muss den Einheitspreis ergeben." On every item row with
a usable unit price and at least one usable component (``component_fields``, which a reviewer
maps: no header does), the sum of the components, rounded to the unit price's decimal places,
must equal the unit price:

* ``component_sum_mismatch``: it does not -> ``confirmed_rule_violation``, medium, with the sum
  written out and the unit price and the components highlighted. No financial impact: the unit
  price is what the bid offers, so the bill's total does not change.

The unit price's decimal places are the most that a usable unit price of the table shows, as
written or by its number format ("#,##0.00"): a spreadsheet stores numbers as binary floats, so
40.00 reads back as 40. The sum is rounded half up (``rounding_mode``) and compared exactly.

Abstentions, each counted in coverage: a row without any component
(``rows_without_components``), a component or unit price that is a value marker
(``rows_skipped_marker``) or no usable amount, such as an unreadable cell or a percentage
(``rows_skipped_unusable_inputs``), an empty unit price (``rows_skipped_missing_inputs``), and
explicit currencies that disagree (``rows_skipped_currency_conflict``).

The GAEB import keeps the unit price components in the file but does not read them yet (UPComp1
to UPComp6 in GAEB XML, record 30 in GAEB 90); its warning ``gaeb_elements_not_shown`` counts
them in its message ("UPComp1 (12), UPComp2 (12)", or "Satzart 30 (Einheitspreisanteile) (12)").
A table under such a warning (``not_imported_warning``, ``not_imported_elements``) gets a note
that its file has unit price components that were not checked
(``tables_skipped_components_not_imported``), so the check runs on such a file and says so.

Finding category (B2): error, for every finding of this detector (``component_sum_mismatch``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from app.models.dataset import Row, Table
from app.models.issue import (
    Calculation,
    CalculationOperand,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType, NumberValue
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import (
    RoundingMode,
    RoundingSpec,
    add_all,
    format_decimal,
    subtract,
)
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._reference_support import clip
from app.validation.deterministic._support import (
    FieldId,
    field_label,
    row_guard,
    row_label,
    written_places,
)

RULE_COMPONENT_SUM = "component_sum_mismatch"
COMPONENT_FIELDS = tuple(f"unit_price_component_{k}" for k in range(1, 7))
COMPONENT_RULE = (
    'GAEB DA XML 3.3 (Fachdokumentation 2023-01, 4.6.5 "Aufgliederung von Einheitspreisen"): '
    '"Die Summe der Einheitspreisanteile einer Position muss den Einheitspreis ergeben." The '
    "components of a position's unit price must add up to the unit price."
)
ROWS_WITHOUT_COMPONENTS = "rows_without_components"
ROWS_CURRENCY_CONFLICT = "rows_skipped_currency_conflict"
TABLES_NOT_IMPORTED = "tables_skipped_components_not_imported"

# Number formats: quoted text, escaped characters, [colour] / [$€-407] sections, and the
# padding (_x) and fill (*x) characters are not digits; what is left after "." are the places.
_FORMAT_LITERALS = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.')
_FORMAT_PLACES = re.compile(r"\.([0#?]+)")
_MAX_PLACES = 10  # the most places a rounding takes (RoundingSpec)


@dataclass(frozen=True, slots=True)
class _Component:
    field_id: str
    value: NumberValue


class UnitPriceComponentsConfig(DetectorConfig):
    price_field: FieldId = plannable("unit_price", description="Field holding the unit price.")
    component_fields: list[FieldId] = plannable(
        list(COMPONENT_FIELDS),
        min_length=1,
        max_length=6,
        description="Fields holding the unit price components (GAEB allows up to six).",
    )
    severity: Severity = plannable(Severity.MEDIUM, description="Severity of a mismatch.")
    rounding_mode: RoundingMode = Field(
        default=RoundingMode.HALF_UP,
        description="How the sum is rounded to the unit price's decimal places.",
    )
    not_imported_warning: str | None = Field(
        default=None,
        description="Extraction warning code whose message counts elements the import kept in "
        "the file but did not read.",
    )
    not_imported_elements: list[str] = Field(
        default_factory=list,
        description="Element names in that warning that are unit price components.",
    )


class UnitPriceComponentsDetector(Detector[UnitPriceComponentsConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.unit_price_components",
        name="Unit price components add up to the unit price",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Adds up each item's unit price components (GAEB Preisanteile, up to six, for "
            "example wages, materials, plant and other costs) and compares the sum, rounded to "
            "the unit price's decimal places, with the unit price."
        ),
        required_fields=("unit_price",),
        optional_fields=COMPONENT_FIELDS,
        supported_data_types=(DataType.NUMBER,),
        applicability=(
            "Tables that map the unit price and at least one unit price component (a reviewer "
            "maps the components; no header does), and GAEB tables whose file holds components "
            "the import does not read yet (the check then says so)."
        ),
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.ARITHMETIC,),
        limitations=(
            "The GAEB import does not read the unit price components yet (UPComp1 to UPComp6 "
            "in GAEB XML, record 30 in GAEB 90): in a GAEB file the components are not "
            "checked, and the run says so.",
            "A mismatch shows that the components and the unit price disagree, not which "
            "component is wrong.",
        ),
        references=(
            "GAEB DA XML 3.3, Fachdokumentation 2023-01, 4.6.5 Aufgliederung von Einheitspreisen",
        ),
        cost="low",
    )
    config_model = UnitPriceComponentsConfig

    def required_fields(self, config: UnitPriceComponentsConfig) -> tuple[str, ...]:
        return (config.price_field,)

    def applicability(
        self, context: ValidationContext, config: UnitPriceComponentsConfig
    ) -> Applicability:
        mapped, not_imported = [], []
        for table in context.tables():
            if not context.has_fields(table, config.price_field):
                continue
            if _mapped_components(table, config):
                mapped.append(table.name)
            elif _not_imported(context, table, config):
                not_imported.append(table.name)
        if not mapped and not not_imported:
            return Applicability.no(
                "No table maps the unit price and a unit price component (a reviewer maps the "
                "components: no header does)."
            )
        reasons = []
        if mapped:
            reasons.append(f"Unit price components are mapped in: {', '.join(mapped)}.")
        if not_imported:
            reasons.append(
                "The file holds unit price components that the import does not read yet: "
                f"{', '.join(not_imported)}."
            )
        return Applicability.yes(*reasons)

    def validate(
        self, context: ValidationContext, config: UnitPriceComponentsConfig
    ) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            if not context.has_fields(table, config.price_field):
                continue
            not_imported = _not_imported(context, table, config)
            if not_imported:
                result.count(TABLES_NOT_IMPORTED)
                result.notes.append(
                    f"Table '{table.name}': the file has unit price components "
                    f"({not_imported}) that the import does not read yet, so they were not "
                    "checked against the unit prices."
                )
            fields = _mapped_components(table, config)
            if not fields:
                continue
            rounding = RoundingSpec(
                decimal_places=_price_places(context, table, config), mode=config.rounding_mode
            )
            for row in context.rows(table):
                with row_guard(result, table, row):
                    self._check(context, config, table, row, fields, rounding, result)
        return result

    def _check(
        self,
        context: ValidationContext,
        config: UnitPriceComponentsConfig,
        table: Table,
        row: Row,
        fields: list[str],
        rounding: RoundingSpec,
        result: DetectorResult,
    ) -> None:
        present = [
            field_id
            for field_id in fields
            if cell_condition(context.cell(table, row, field_id)) is not CellCondition.EMPTY
        ]
        if not present:
            result.count(ROWS_WITHOUT_COMPONENTS)
            return
        components = []
        for field_id in [*present, config.price_field]:
            value = context.number_value(table, row, field_id)
            if value is None or value.is_percent:
                result.count(_skip_reason(context, table, row, field_id))
                return
            components.append(_Component(field_id, value))
        price = components.pop()
        if _currency_conflict(table, [*components, price]):
            result.count(ROWS_CURRENCY_CONFLICT)
            return
        total = add_all(component.value.value for component in components)
        rounded = rounding.apply(total)
        result.count(Coverage.ROWS_CHECKED)
        if rounded == price.value.value:
            result.count(Coverage.ROWS_CONSISTENT)
            return
        result.count(Coverage.ROWS_INCONSISTENT)
        context.checkpoint()
        result.add(
            self._issue(context, config, table, row, components, price, rounding, total, rounded)
        )

    def _issue(
        self,
        context: ValidationContext,
        config: UnitPriceComponentsConfig,
        table: Table,
        row: Row,
        components: list[_Component],
        price: _Component,
        rounding: RoundingSpec,
        total: Decimal,
        rounded: Decimal,
    ) -> ValidationIssue:
        p_label = field_label(context, config.price_field)
        p_ref = context.cell_ref(table, row, config.price_field)
        refs = [context.cell_ref(table, row, c.field_id) for c in components]
        operands = [
            CalculationOperand(
                label=field_label(context, c.field_id), value=c.value.value, cell=ref
            )
            for c, ref in zip(components, refs, strict=True)
        ]
        stated, summed = format_decimal(price.value.value), format_decimal(rounded)
        difference = subtract(price.value.value, rounded)
        written = " + ".join(f"{o.label} {format_decimal(o.value)}" for o in operands)
        sum_text = f"{written} = {format_decimal(total)}"
        if rounded != total:
            sum_text += f" → {summed} ({rounding.describe()})"
        places = rounding.decimal_places
        calculation = Calculation(
            operation="sum",
            operands=operands,
            terms=len(operands),
            exact_result=total,
            rounding=rounding.describe() if places is not None else None,
            rounded_result=rounded if places is not None else None,
            reported=price.value.value,
            difference=difference,
            allowed_difference=Decimal(0),
        )
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.CALCULATION,
                label="Sum of the components",
                detail=(f"{sum_text}; {p_label} {stated}; difference {format_decimal(difference)}"),
                cells=[*refs, p_ref],
                calculation=calculation,
            ),
            EvidenceItem(
                kind=EvidenceKind.RULE,
                label="Rule",
                detail=(
                    f"{COMPONENT_RULE} The sum is rounded to {rounding.describe()}, the places "
                    f"the {p_label}s of table '{table.name}' are written with, and compared "
                    "exactly."
                ),
            ),
        ]
        return context.issues.create(
            self.spec,
            rule_id=RULE_COMPONENT_SUM,
            category=IssueCategory.ARITHMETIC,
            severity=config.severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Components of the {p_label} add up to {summed}, not {stated}", 200),
            explanation=(
                f"{row_label(table, row)}: {sum_text}, but the {p_label} is {stated} "
                f"(difference {format_decimal(difference)}). The components of a unit price "
                "must add up to it. The bill's total does not change: the unit price is what "
                "the bid offers."
            ),
            table=table,
            row=row,
            cells=[p_ref, *refs],
            observed_value=summed,
            expected_value=stated,
            evidence=evidence,
            suggested_action=(
                f"Make the components add up to the {p_label} {stated}, the price the bid "
                f"offers. If the {p_label} itself is wrong, correct it together with its "
                "components."
            ),
            subject=config.price_field,
        )


def _mapped_components(table: Table, config: UnitPriceComponentsConfig) -> list[str]:
    return [f for f in config.component_fields if table.column_for_field(f) is not None]


def _not_imported(
    context: ValidationContext, table: Table, config: UnitPriceComponentsConfig
) -> str:
    """The component elements an import warning counts for this table ("UPComp1 (12),
    UPComp2 (12)"); empty when there is none. The GAEB import lists the elements it kept in
    the file but did not read as "Name (count)" in its message."""
    if config.not_imported_warning is None or not config.not_imported_elements:
        return ""
    found: dict[str, int] = {}
    for warning in context.dataset.extraction.warnings:
        if warning.code != config.not_imported_warning:
            continue
        if warning.table_id not in (None, table.table_id):
            continue
        for name in config.not_imported_elements:
            match = re.search(rf"(?<!\w){re.escape(name)} \((\d+)\)", warning.message)
            if match is not None and int(match.group(1)) > 0:
                found[name] = found.get(name, 0) + int(match.group(1))
    return ", ".join(f"{name} ({count})" for name, count in found.items())


def _skip_reason(context: ValidationContext, table: Table, row: Row, field_id: str) -> str:
    condition = cell_condition(context.cell(table, row, field_id))
    if condition is CellCondition.EMPTY:
        return Coverage.ROWS_SKIPPED_MISSING_INPUTS
    if condition is CellCondition.MARKER:
        return Coverage.ROWS_SKIPPED_MARKER
    return Coverage.ROWS_SKIPPED_UNUSABLE_INPUTS


def _currency_conflict(table: Table, values: list[_Component]) -> bool:
    found = set()
    for component in values:
        column = table.column_for_field(component.field_id)
        currency = component.value.currency or (
            column.header_currency if column is not None else None
        )
        if currency is not None:
            found.add(currency)
    return len(found) > 1


def _price_places(
    context: ValidationContext, table: Table, config: UnitPriceComponentsConfig
) -> int | None:
    """The most decimal places a usable unit price of the table shows, as written or by its
    number format (at most ten); ``None`` (no rounding) when the table has no usable unit
    price."""
    places: int | None = None
    for row in context.rows(table):
        value = context.number_value(table, row, config.price_field)
        if value is None:
            continue
        cell = context.cell(table, row, config.price_field)
        shown = max(
            written_places(value.value),
            _format_places(cell.number_format if cell is not None else None) or 0,
        )
        places = shown if places is None else max(places, shown)
    return None if places is None else min(places, _MAX_PLACES)


def _format_places(number_format: str | None) -> int | None:
    """Decimal places of a spreadsheet number format (``#,##0.00`` -> 2, ``0`` -> 0); ``None``
    for a format without digits, such as ``General``."""
    if not number_format:
        return None
    section = _FORMAT_LITERALS.sub("", number_format.split(";", 1)[0])
    if not any(ch in "0#?" for ch in section):
        return None
    match = _FORMAT_PLACES.search(section)
    return len(match.group(1)) if match is not None else 0
