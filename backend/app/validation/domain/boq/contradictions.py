"""Contradictions within an item: its texts against each other, its unit, quantity and type.

A tender estimator prices what the long text specifies, so a short text that says something
else, or a unit or quantity the text contradicts, must be cleared before pricing. On item rows:

* ``spec_conflict``: the short text and the long text name different values of one kind of
  specification: each text states a value the other does not repeat. Nominal or outer diameter
  (``DN 125`` / ``DN 100``, ``DN/OD 75`` / ``DN/OD 63``, also one side of a reduction ``DN 125 /
  DN 50`` against ``DN 100 / 50``), pressure rating (PN, also against a nominal pressure in
  bar: ``PN 6`` / ``Nenndruck 1,6 MPa (16 bar)``), pressure in bar (``6 bar`` / ``25 bar``),
  angle or angle range (``15 - 30 Grad`` / ``45 - 90 Grad``; temperatures are not angles),
  material condition (``gebraucht`` / ``fabrikneu``), concrete strength class (``C20/25`` /
  ``C25/30``), steel grade (S235, S355), fire resistance (F30, T30, EI 90), SDR, RAL colour,
  soil class (Bodenklasse) -> semantic warning, medium. A text that names several values and
  repeats the other text's values among them is no conflict.
* ``billing_unit_conflict``: the text names how the item is measured (``Abrechnung nach m²``,
  ``vergütet je Stück``) in a unit of another dimension than the item's unit -> medium.
* ``item_type_conflict``: the text calls the item a contingency or alternative item
  (``Bedarfsposition``, ``Eventualposition``, ``Wahlposition``, ``Alternativposition``) but the
  item counts toward the total: its amount may be added to the bid sum -> medium. A contingency
  item "mit GB" (with total) counts on purpose and is not reported.
* ``quantity_text_conflict``: the text states the quantity (``Menge: 25 m²``, ``Anzahl: 3
  Stück``) in the item's unit dimension, and it differs from the item's quantity -> low.

Units are compared by dimension through the profile's unit vocabulary (m, lfm -> length;
m², qm -> area; St, Stk -> count). Only what both sides state is compared.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from pydantic import Field

from app.models.dataset import Row, Table
from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, Severity
from app.models.values import DataType
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._support import FieldId, fmt
from app.validation.domain.boq._bill_text import description_applicability
from app.validation.domain.boq._tender import anchor, quote, texts

RULE_SPEC = "spec_conflict"
RULE_BILLING = "billing_unit_conflict"
RULE_TYPE = "item_type_conflict"
RULE_QUANTITY = "quantity_text_conflict"
CATEGORY = "contradiction"
ITEMS_READ = "items_read"

# Kinds of specification compared between short and long text; every capture group is a value.
SPECIFICATIONS: dict[str, tuple[str, str]] = {
    # "DN 100", "DN/OD 63", and both sides of "DN 125 / DN 50" or "DN 100/50".
    "nominal_diameter": (
        "nominal diameter",
        r"\bDN(?:\s?/\s?OD)?\s?(\d{2,4})(?:\s?/\s?(?:DN\s?)?(\d{2,4}))?\b",
    ),
    # PN 16 is a nominal pressure of 16 bar: "Nenndruck 16 bar", "Nenndruck 1,6 MPa (16 bar)".
    "pressure_rating": (
        "pressure rating",
        r"\bPN\s?(\d{1,3})\b"
        r"|\bNenndruck\s+(?:\d+(?:[.,]\d+)?\s?MPa\s?\(\s?(\d{1,3})\s?bar\s?\)|(\d{1,3})\s?bar\b)",
    ),
    "pressure_bar": ("pressure in bar", r"(?<![\d.,])(\d{1,3}(?:[.,]\d)?)\s?bar\b"),
    # An angle or a range of angles in degrees ("90 Grad", "45 - 90 Grad", "30°"), never a
    # temperature ("60 Grad C", "5 °C").
    "angle": (
        "angle",
        r"(?<![\d.,])(\d{1,3})(?:\s?(?:-|bis)\s?(\d{1,3}))?\s?(?:Grad\b|°)(?!\s?(?:C\b|Celsius))",
    ),
    "material_condition": ("material condition", r"\b(gebraucht|fabrikneu)\w*"),
    "concrete_class": ("concrete strength class", r"\b(L?C\s?\d{1,3}\s?/\s?\d{2,3})\b"),
    "steel_grade": ("steel grade", r"\b(S\s?(?:235|275|355|420|460))\b"),
    "fire_rating": ("fire resistance", r"\b([FT]\s?(?:30|60|90|120|180)|EI\s?(?:30|60|90|120))\b"),
    "sdr": ("SDR", r"\bSDR\s?(\d{1,2}(?:[.,]\d)?)\b"),
    "ral": ("RAL colour", r"\bRAL\s?(\d{4})\b"),
    "soil_class": ("soil class", r"\bBodenklassen?\s+(\d(?:\s?(?:-|bis|und|\+)\s?\d)?)\b"),
}
# A unit token is matched whole (atomic group): "m² x Woche" is a compound unit, never "m".
_UNIT_WORD = r"((?>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß²³0-9]*\.?))"
_BILLING = re.compile(
    r"\b(?:abrechnung|abgerechnet|vergütung|vergütet|aufmaß)\s+(?:erfolgt\s+)?"
    rf"(?:nach|in|je|per|pro)\s+{_UNIT_WORD}(?!\s*[x×*/])",
    re.IGNORECASE,
)
_TYPES = re.compile(
    r"\b(Bedarfsposition|Eventualposition|Wahlposition|Alternativposition)\b", re.IGNORECASE
)
# "Bedarfsposition mit GB": a contingency item whose total is part of the bid sum, on purpose.
_WITH_TOTAL = re.compile(
    r"\b(?:bedarfs|eventual)(?:position(?:en)?|pos\.?)?\s+(?:mit\s+(?:gb|gesamtbetrag|gp)|m\.?\s?gb)\b",
    re.IGNORECASE,
)
_QUANTITY = re.compile(
    r"\b(?:Menge|Gesamtmenge|Anzahl|Stückzahl)\s*[:=]?\s*(?:ca\.\s*)?"
    rf"(\d{{1,3}}(?:\.\d{{3}})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*{_UNIT_WORD}(?!\s*[x×*/])",
    re.IGNORECASE,
)


class ContradictionsConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field holding the item number.")
    description_field: FieldId = plannable("description", description="Short text field.")
    long_description_field: FieldId = plannable(
        "long_description", description="Long text field (needed for spec_conflict)."
    )
    quantity_field: FieldId = plannable("quantity", description="Field holding the quantity.")
    item_type_field: FieldId = plannable("item_type", description="Field holding the item type.")
    specifications: list[str] = Field(
        default=list(SPECIFICATIONS),
        description="Kinds of specification compared between short and long text: "
        + ", ".join(SPECIFICATIONS),
    )


class BoqContradictionsDetector(Detector[ContradictionsConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_contradictions",
        name="Contradictions within an item",
        version="1.2.0",
        category=DetectorCategory.SEMANTIC,
        description=(
            "Finds items that contradict themselves: a short text and long text naming "
            "different diameters, pressures, angles, concrete classes, steel grades, fire "
            "ratings or colours, or used against new material; a "
            "text measuring the item in another unit than its unit column; a text calling it a "
            "contingency or alternative item while it counts toward the total; a quantity in "
            "the text that differs from the item's quantity."
        ),
        required_fields=("description",),
        optional_fields=("long_description", "unit", "quantity", "item_type", "item_code"),
        supported_data_types=(DataType.TEXT, DataType.NUMBER),
        applicability="Tables that map the item description of a bill of quantities.",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(CATEGORY,),
        limitations=(
            "A long text may legitimately name several values (a connection from DN 150 to "
            "DN 100); a conflict is reported only when each text states a value the other "
            "does not repeat.",
            "Only values written in both texts are compared: a value changed in a text whose "
            "counterpart does not state it at all is not found.",
            "Units in texts are read through the profile's unit vocabulary; unknown ones are "
            "not compared.",
        ),
        references=("VOB/A § 7 (1) Nr. 1: the description of the work must be unambiguous.",),
        cost="low",
    )
    config_model = ContradictionsConfig

    def required_fields(self, config: ContradictionsConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(
        self, context: ValidationContext, config: ContradictionsConfig
    ) -> Applicability:
        return description_applicability(context, config.description_field)

    def validate(self, context: ValidationContext, config: ContradictionsConfig) -> DetectorResult:
        result = DetectorResult()
        specs = {
            key: (label, re.compile(pattern, re.IGNORECASE))
            for key, (label, pattern) in SPECIFICATIONS.items()
            if key in config.specifications
        }
        conflicts: dict[tuple[str, str, str], list[tuple[Table, Row]]] = {}
        shown: dict[tuple[str, str, str], tuple[str, str]] = {}
        for table in context.tables():
            if not context.has_fields(table, config.description_field):
                continue
            for row in context.rows(table):
                result.count(ITEMS_READ)
                short, long = texts(
                    context, table, row, config.description_field, config.long_description_field
                )
                if short and long:
                    for label, pattern in specs.values():
                        if conflict := _spec_conflict(short, long, label, pattern):
                            key, as_written = conflict
                            conflicts.setdefault(key, []).append((table, row))
                            shown.setdefault(key, as_written)
                whole = f"{short} {long}"
                self._billing(context, config, table, row, whole, result)
                self._type(context, config, table, row, whole, result)
                self._quantity(context, config, table, row, whole, result)
        for key, rows in conflicts.items():
            self._spec(context, config, rows, key[0], *shown[key], result)
        return result

    # ------------------------------------------------------------------ rules
    def _spec(
        self,
        context: ValidationContext,
        config: ContradictionsConfig,
        rows: list[tuple[Table, Row]],
        label: str,
        stated: str,
        other: str,
        result: DetectorResult,
    ) -> None:
        """One finding per conflict: items whose texts repeat the same conflict (a long text
        copied to several positions) are one cause, so they are reported together."""
        table, row = rows[0]
        codes = [
            context.text(t, r, config.code_field) or f"row {r.source_row_number}" for t, r in rows
        ]
        also = rows[1:]
        repeated = (
            f" The same conflict is in {len(also)} more item(s): {', '.join(codes[1:])}."
            if also
            else ""
        )
        self._add(
            context,
            config,
            table,
            row,
            result,
            rule=RULE_SPEC,
            severity=Severity.MEDIUM,
            title=f"Short text says {stated}, long text says {other}"
            + (f" (and {len(also)} more)" if also else ""),
            explanation=(
                f"The short text of item {{code}} names the {label} {stated}, but the long text "
                f"names {other} and not {stated}. The estimator prices what the long text "
                f"specifies; one of the two is likely a copy-and-paste error.{repeated}"
            ),
            observed=f"short: {stated}; long: {other}",
            action=f"Ask the client which {label} applies.",
            subject=label,
            also=also,
        )

    def _billing(
        self,
        context: ValidationContext,
        config: ContradictionsConfig,
        table: Table,
        row: Row,
        whole: str,
        result: DetectorResult,
    ) -> None:
        found = _BILLING.search(whole)
        if found is None:
            return
        stated = context.units.resolve(found.group(1).rstrip("."))
        unit_field = context.unit_field_id()
        item_unit = context.unit(table, row) if unit_field else None
        if stated is None or item_unit is None or not unit_field:
            return
        dimensions = {stated.dimension, item_unit.unit.dimension}
        if len(dimensions) == 1 or "lump_sum" in dimensions:
            return
        cell = context.cell(table, row, unit_field)
        # the unit as the bill writes it ("St"), not its vocabulary id ("pcs")
        unit_text = (cell.raw_value or "").strip() if cell is not None else ""
        unit_text = unit_text or context.text(table, row, unit_field) or ""
        self._add(
            context,
            config,
            table,
            row,
            result,
            rule=RULE_BILLING,
            severity=Severity.MEDIUM,
            title=f"Measured '{quote(found.group(0), 40)}' but the unit is {unit_text}",
            explanation=(
                f"The text of item {{code}} says {quote(found.group(0), 60)!r} "
                f"({stated.dimension}), but the item's unit is {unit_text!r} "
                f"({item_unit.unit.dimension}). Quantity and price refer to different units."
            ),
            observed=f"text: {found.group(1)}; unit: {unit_text}",
            action="Ask the client in which unit the item is measured, and correct one of them.",
            subject="billing",
            extra_field=unit_field,
        )

    def _type(
        self,
        context: ValidationContext,
        config: ContradictionsConfig,
        table: Table,
        row: Row,
        whole: str,
        result: DetectorResult,
    ) -> None:
        found = _TYPES.search(whole)
        if found is None or row.counts_toward_totals is not True or _WITH_TOTAL.search(whole):
            return
        item_type = context.text(table, row, config.item_type_field) or ""
        if found.group(1).lower() in item_type.lower():
            return
        self._add(
            context,
            config,
            table,
            row,
            result,
            rule=RULE_TYPE,
            severity=Severity.MEDIUM,
            title=f"Text says {found.group(1)}, but the item counts toward the total",
            explanation=(
                f"The text of item {{code}} calls it a {found.group(1)}, but the bill treats it "
                f"as a normal item{f' ({item_type})' if item_type else ''} that counts toward "
                "the total. A contingency or alternative item is priced but not added to the "
                "bid sum; added, it inflates the total."
            ),
            observed=found.group(1),
            action="Ask the client whether the item is a contingency or alternative item, and "
            "mark it so.",
            subject="type",
        )

    def _quantity(
        self,
        context: ValidationContext,
        config: ContradictionsConfig,
        table: Table,
        row: Row,
        whole: str,
        result: DetectorResult,
    ) -> None:
        found = _QUANTITY.search(whole)
        if found is None or not context.has_fields(table, config.quantity_field):
            return
        quantity = context.number(table, row, config.quantity_field)
        stated_unit = context.units.resolve(found.group(2).rstrip("."))
        item_unit = context.unit(table, row) if context.unit_field_id() else None
        if quantity is None or stated_unit is None or item_unit is None:
            return
        if stated_unit.dimension != item_unit.unit.dimension:
            return
        stated = _decimal(found.group(1))
        if stated is None or stated == quantity:
            return
        self._add(
            context,
            config,
            table,
            row,
            result,
            rule=RULE_QUANTITY,
            severity=Severity.LOW,
            title=f"Text states {quote(found.group(0), 40)}, quantity is {fmt(quantity)}",
            explanation=(
                f"The text of item {{code}} states {quote(found.group(0), 60)!r}, but the "
                f"item's quantity is {fmt(quantity)}. Either the text or the quantity is out of "
                "date."
            ),
            observed=f"text: {found.group(1)}; quantity: {fmt(quantity)}",
            action="Check which quantity applies.",
            subject="quantity",
            extra_field=config.quantity_field,
        )

    def _add(
        self,
        context: ValidationContext,
        config: ContradictionsConfig,
        table: Table,
        row: Row,
        result: DetectorResult,
        *,
        rule: str,
        severity: Severity,
        title: str,
        explanation: str,
        observed: str,
        action: str,
        subject: str,
        extra_field: str | None = None,
        also: list[tuple[Table, Row]] | None = None,
    ) -> None:
        code = context.text(table, row, config.code_field) or f"row {row.source_row_number}"
        cells = anchor(context, table, row, config.description_field)
        if extra_field:
            cells += anchor(context, table, row, extra_field)
        for other_table, other_row in also or ():
            cells += anchor(context, other_table, other_row, config.description_field)
        result.add(
            context.issues.create(
                self.spec,
                rule_id=rule,
                category=CATEGORY,
                severity=severity,
                evidence_class=EvidenceClass.SEMANTIC_WARNING,
                title=f"Item {code}: {title}"[:200],
                explanation=explanation.replace("{code}", code),
                table=table,
                row=row,
                cells=cells,
                observed_value=observed[:500],
                evidence=[
                    EvidenceItem(
                        kind=EvidenceKind.COMPARISON,
                        label="What the item states",
                        detail=observed,
                        cells=cells,
                    )
                ],
                suggested_action=action,
                subject=subject,
            )
        )


def _spec_conflict(
    short: str, long: str, label: str, pattern: re.Pattern[str]
) -> tuple[tuple[str, str, str], tuple[str, str]] | None:
    """When the texts disagree: the conflict (label and the normalized values of both texts),
    which identifies it across items, and the values as the first item writes them."""
    in_short = _values(pattern, short)
    in_long = _values(pattern, long)
    # A conflict needs a value on each side that the other text does not repeat: a long text
    # that names more values than the short text (or the reverse) only says more.
    if not (in_short - in_long) or not (in_long - in_short):
        return None
    key = (label, ",".join(sorted(in_short)), ",".join(sorted(in_long)))
    stated = ", ".join(sorted(_shown(pattern, short)))
    return key, (stated, ", ".join(sorted(_shown(pattern, long))))


def _values(pattern: re.Pattern[str], text: str) -> set[str]:
    return {
        _normalized(group) for match in pattern.finditer(text) for group in match.groups() if group
    }


def _normalized(value: str) -> str:
    """A value as compared: without spaces, upper case, a decimal point, and no trailing
    decimal zeros ("1,0" is "1")."""
    value = re.sub(r"\s+", "", value).upper().replace(",", ".")
    if re.fullmatch(r"\d+\.\d+", value):
        value = value.rstrip("0").rstrip(".")
    return value


def _shown(pattern: re.Pattern[str], text: str) -> set[str]:
    return {" ".join(match.group(0).split()) for match in pattern.finditer(text)}


def _decimal(text: str) -> Decimal | None:
    normalized = text.replace(".", "").replace(",", ".") if "," in text else text
    if "," not in text and text.count(".") == 1 and len(text.split(".")[1]) == 3:
        normalized = text.replace(".", "")  # "1.500" written as thousands
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None
