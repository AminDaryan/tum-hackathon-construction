"""Standard text keys (STLB-Bau, StLB, StLK): consistency checks that need no catalogue.

STLB-Bau is DIN's licensed catalogue of standard work descriptions. A GAEB item can name the
standard text it uses; the GAEB import puts that reference into ``standard_text_key`` and the
catalogue with its version into ``standard_text_catalog``. The catalogue texts are not available
here (they are licensed), so no item text is compared with them, and every run says so. What
the document itself shows is checked, on item rows:

* ``same_key_units``: rows with the same key whose units differ (another unit, or the same unit
  with another multiplier such as "100 St") -> semantic warning, medium, one per key. One
  standard text describes one kind of work, which is normally measured in one unit.
* ``same_key_unit_prices``: rows with the same key, unit and currency whose unit prices differ
  -> suspected anomaly, low, one per key and unit, without a probability. Prices of one standard
  text can legitimately differ (quantity, access, location), so a reviewer decides.
* ``catalogue_versions``: keys from more than one catalogue or catalogue version -> needs
  external context, info, once per dataset: which version applies is a matter of the contract.

Keys are compared as written (whitespace collapsed). Rows with an empty or unknown unit are not
compared by unit, rows without a usable unit price not by price; coverage counts them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from pydantic import Field

from app.models.dataset import CellRef, Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
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
from app.validation.deterministic._reference_support import clip, describe_rows, short_digest
from app.validation.deterministic._support import FieldId, field_label, fmt, row_guard

RULE_UNITS = "same_key_units"
RULE_PRICES = "same_key_unit_prices"
RULE_VERSIONS = "catalogue_versions"
CATEGORY_PRICE = "unit_price"
CATEGORY_CATALOGUE = "standard_text"

ROWS_WITH_KEY = "rows_with_standard_text_key"
ROWS_UNIT_NOT_COMPARED = "rows_unit_not_compared"
ROWS_PRICE_NOT_COMPARED = "rows_price_not_compared"
KEYS_COMPARED = "keys_compared"
NOT_IN_CATALOGUE_NOTE = (
    "Standard texts were not compared with the STLB-Bau catalogue: its texts are licensed by "
    "DIN and not part of this tool. Only the keys the document states were compared."
)


@dataclass(frozen=True, slots=True)
class _Member:
    """An item row that names a standard text."""

    table_index: int
    table: Table
    row: Row
    unit: tuple[str, Decimal | None] | None  # (unit id, multiplier); None = empty or unknown
    unit_text: str | None
    price: Decimal | None
    currency: str | None  # the price's marked currency, None when unmarked or mixed


class StandardTextKeysConfig(DetectorConfig):
    key_field: FieldId = plannable(
        "standard_text_key", description="Field holding the standard text key."
    )
    catalogue_field: FieldId = plannable(
        "standard_text_catalog", description="Field holding the key's catalogue and version."
    )
    price_field: FieldId = plannable("unit_price", description="Field holding the unit price.")
    max_cells_per_issue: int = Field(
        default=20, ge=1, le=200, description="Rows highlighted in one finding."
    )


class StandardTextKeysDetector(Detector[StandardTextKeysConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.standard_text_keys",
        name="Standard text keys (STLB-Bau)",
        version="1.0.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Compares items that name the same standard text (an STLB-Bau, StLB or StLK key "
            "from a GAEB file): different units or unit prices for one standard text, and keys "
            "from several catalogues or catalogue versions. The licensed catalogue texts are "
            "not checked."
        ),
        required_fields=("standard_text_key",),
        optional_fields=("standard_text_catalog", "unit", "unit_price"),
        supported_data_types=(DataType.TEXT, DataType.NUMBER),
        applicability=(
            "Tables that map the standard text key (GAEB bills whose items carry STLB-Bau or "
            "StLNo references)."
        ),
        evidence_classes=(
            EvidenceClass.SEMANTIC_WARNING,
            EvidenceClass.SUSPECTED_ANOMALY,
            EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
        ),
        issue_categories=(IssueCategory.UNIT, CATEGORY_PRICE, CATEGORY_CATALOGUE),
        limitations=(
            "The STLB-Bau catalogue is licensed by DIN and not bundled: item texts are not "
            "compared with catalogue texts, and keys are not looked up in the catalogue.",
            "Keys are compared as written; two spellings of one reference are two keys.",
            "One standard text can legitimately carry different unit prices; that finding is a "
            "signal for a reviewer, not an error, and carries no probability.",
        ),
        references=("GAEB DA XML 3.3 (2021-05): Description/STLBBau and Description/StLNo",),
        cost="low",
    )
    config_model = StandardTextKeysConfig

    def required_fields(self, config: StandardTextKeysConfig) -> tuple[str, ...]:
        return (config.key_field,)

    def applicability(
        self, context: ValidationContext, config: StandardTextKeysConfig
    ) -> Applicability:
        tables = [t.name for t in context.tables() if context.has_fields(t, config.key_field)]
        if not tables:
            return Applicability.no("No table maps the standard text key.")
        return Applicability.yes(f"Standard text keys are mapped in: {', '.join(tables)}.")

    def validate(
        self, context: ValidationContext, config: StandardTextKeysConfig
    ) -> DetectorResult:
        result = DetectorResult()
        groups: dict[str, list[_Member]] = {}
        catalogues: dict[str, list[_Member]] = {}
        for table_index, table in enumerate(context.tables()):
            if not context.has_fields(table, config.key_field):
                continue
            for row in context.rows(table):
                with row_guard(result, table, row):
                    key = context.text(table, row, config.key_field)
                    if not key:
                        continue
                    member = _member(context, config, table_index, table, row)
                    result.count(ROWS_WITH_KEY)
                    groups.setdefault(" ".join(key.split()), []).append(member)
                    catalogue = context.text(table, row, config.catalogue_field)
                    if catalogue:
                        catalogues.setdefault(" ".join(catalogue.split()), []).append(member)
        result.notes.append(NOT_IN_CATALOGUE_NOTE)
        for key, members in groups.items():
            if len(members) < 2:
                continue
            context.checkpoint()
            result.count(KEYS_COMPARED)
            self._compare(context, config, key, members, result)
        if len(catalogues) > 1:
            result.add(self._versions_issue(context, config, catalogues))
        return result

    def _compare(
        self,
        context: ValidationContext,
        config: StandardTextKeysConfig,
        key: str,
        members: list[_Member],
        result: DetectorResult,
    ) -> None:
        by_unit: dict[tuple[str, Decimal | None], list[_Member]] = {}
        for member in members:
            if member.unit is None:
                result.count(ROWS_UNIT_NOT_COMPARED)
            else:
                by_unit.setdefault(member.unit, []).append(member)
        if len(by_unit) > 1:
            result.add(self._units_issue(context, config, key, by_unit))
        for unit, same_unit in by_unit.items():
            by_currency: dict[str | None, list[_Member]] = {}
            for member in same_unit:
                if member.price is None:
                    result.count(ROWS_PRICE_NOT_COMPARED)
                else:
                    by_currency.setdefault(member.currency, []).append(member)
            for currency, priced in by_currency.items():
                if len({m.price for m in priced}) > 1:
                    result.add(self._prices_issue(context, config, key, unit, currency, priced))

    def _units_issue(
        self,
        context: ValidationContext,
        config: StandardTextKeysConfig,
        key: str,
        by_unit: dict[tuple[str, Decimal | None], list[_Member]],
    ) -> ValidationIssue:
        # The rarest unit first, so a capped list still shows the deviation.
        ordered = [m for _, ms in sorted(by_unit.items(), key=lambda i: len(i[1])) for m in ms]
        unit_field = context.unit_field_id() or "unit"
        cells = _refs(context, ordered, unit_field, config.max_cells_per_issue)
        per_unit = "; ".join(
            f"{_unit_shown(ms)}: {_rows_text(ms)}" for ms in sorted(by_unit.values(), key=len)
        )
        key_label = field_label(context, config.key_field)
        return context.issues.create(
            self.spec,
            rule_id=RULE_UNITS,
            category=IssueCategory.UNIT,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(f"One standard text measured in {len(by_unit)} units: {key}", 200),
            explanation=(
                f"{len(ordered)} item rows name the {key_label} '{clip(key, 300)}', but their "
                f"units differ: {per_unit}. One standard text describes one kind of work, "
                "which is normally measured in one unit. This is an advisory warning."
            ),
            table=ordered[0].table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"{field_label(context, unit_field)} by row",
                    detail=per_unit,
                    cells=cells,
                    data={"rows": len(ordered), "units": len(by_unit)},
                ),
            ],
            suggested_action=(
                "Check the units: if the rows describe the same work, measure it in one unit; "
                "otherwise check that each row names the right standard text."
            ),
            subject=short_digest(key),
        )

    def _prices_issue(
        self,
        context: ValidationContext,
        config: StandardTextKeysConfig,
        key: str,
        unit: tuple[str, Decimal | None],
        currency: str | None,
        members: list[_Member],
    ) -> ValidationIssue:
        prices = Counter(m.price for m in members if m.price is not None)
        # The rarest price first, so a capped list still shows the deviation.
        ordered = sorted(members, key=lambda m: prices[m.price] if m.price is not None else 0)
        cells = _refs(context, ordered, config.price_field, config.max_cells_per_issue)
        lowest, highest = min(prices), max(prices)
        price_label = field_label(context, config.price_field)
        listed = "; ".join(
            f"{fmt(price)}: {_rows_text([m for m in ordered if m.price == price])}"
            for price in sorted(prices)
        )
        return context.issues.create(
            self.spec,
            rule_id=RULE_PRICES,
            category=CATEGORY_PRICE,
            severity=Severity.LOW,
            evidence_class=EvidenceClass.SUSPECTED_ANOMALY,
            title=clip(f"One standard text with {len(prices)} {price_label}s: {key}", 200),
            explanation=(
                f"{len(members)} item rows name the standard text '{clip(key, 300)}' in the "
                f"same unit ({_unit_shown(members)}), but their {price_label}s range from "
                f"{fmt(lowest)} to {fmt(highest)}: {listed}. The same standard work is usually "
                "priced alike within one document; differences can be legitimate (quantity, "
                "access, location), so a reviewer should decide."
            ),
            table=ordered[0].table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"{price_label} by row",
                    detail=listed,
                    cells=cells,
                    data={"rows": len(members), "lowest": fmt(lowest), "highest": fmt(highest)},
                ),
            ],
            suggested_action=(
                f"Check whether the different {price_label}s are intended; if the rows describe "
                "the same work, align them."
            ),
            subject=f"{short_digest(key)}:{unit[0]}:{unit[1] or ''}:{currency or ''}",
        )

    def _versions_issue(
        self,
        context: ValidationContext,
        config: StandardTextKeysConfig,
        catalogues: dict[str, list[_Member]],
    ) -> ValidationIssue:
        ordered = sorted(catalogues.items(), key=lambda i: (len(i[1]), i[0]))
        first = [ms[0] for _, ms in ordered]
        cells = _refs(context, first, config.catalogue_field, config.max_cells_per_issue)
        listed = "; ".join(f"{name} ({_count(len(ms), 'item row')})" for name, ms in ordered)
        label = field_label(context, config.catalogue_field)
        return context.issues.create(
            self.spec,
            rule_id=RULE_VERSIONS,
            category=CATEGORY_CATALOGUE,
            severity=Severity.INFO,
            evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            title=f"Standard texts from {len(catalogues)} catalogues or versions",
            explanation=(
                f"The items name standard texts from {len(catalogues)} catalogues or catalogue "
                f"versions: {listed}. Texts of different versions can differ; whether the "
                "older texts still apply depends on the contract, which is not part of this "
                "document. The first row of each is highlighted."
            ),
            table=first[0].table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label=f"{label} values",
                    detail=listed,
                    cells=cells,
                    data={"catalogues": len(catalogues)},
                ),
            ],
            suggested_action=(
                "Check which catalogue version the contract refers to, and whether the texts "
                "from other versions still apply."
            ),
            subject="catalogues",
        )


def _member(
    context: ValidationContext,
    config: StandardTextKeysConfig,
    table_index: int,
    table: Table,
    row: Row,
) -> _Member:
    lookup = context.unit(table, row)
    unit_field = context.unit_field_id()
    return _Member(
        table_index=table_index,
        table=table,
        row=row,
        unit=(lookup.unit.unit_id, lookup.multiplier) if lookup is not None else None,
        unit_text=context.text(table, row, unit_field) if unit_field else None,
        price=context.number(table, row, config.price_field),
        currency=context.currency_evidence(table, row, [config.price_field]),
    )


def _refs(
    context: ValidationContext, members: list[_Member], field_id: str, cap: int
) -> list[CellRef]:
    anchor = members[0].table
    return [context.cell_ref(m.table, m.row, field_id) for m in members if m.table is anchor][:cap]


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _rows_text(members: list[_Member]) -> str:
    return describe_rows([(m.table, m.row) for m in members], 4)


def _unit_shown(members: list[_Member]) -> str:
    texts = sorted({m.unit_text or "?" for m in members})
    return ", ".join(texts)
