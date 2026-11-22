"""Currency consistency: explicit currency markers that disagree.

Only explicit markers count, the same ones :meth:`ValidationContext.currency_evidence` reads: a
monetary cell's own marker (``NumberValue.currency``: "€ 1.234,50", "1,234.50 EUR", a currency
number format), its column header's currency (``Column.header_currency``: "EP [€]") and the
row's currency column (the field with role ``currency``), resolved with ``context.currencies``.
Unmarked amounts are never flagged and never assumed to be in a default currency.

Rules, per table (rows of every kind, reviewer-excluded rows skipped):

* ``row_currency_conflict`` (confirmed): the markers of one row disagree: two monetary cells, a
  cell and its column header, or a cell and the row's currency column.
* ``unexpected_currency`` (confirmed, only when ``expected_currency`` is set): markers that
  differ from it, one finding per column and currency.
* ``minority_currency`` (needs_external_context, only without ``expected_currency`` and without
  a currency column): when a table's amounts carry several currencies, one finding per
  currency other than the most common one (ties: the first seen), leaving out rows already
  reported as conflicts. With a currency column, rows in different currencies are legitimate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import ClassVar

from pydantic import Field

from app.models.dataset import CellRef, Column, Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import FieldRole
from app.models.values import DataType
from app.validation.contracts.conditions import Coverage
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
from app.validation.deterministic._reference_support import clip, describe_rows
from app.validation.deterministic._support import FieldId, field_label, row_guard, row_label

RULE_ROW_CONFLICT = "row_currency_conflict"
RULE_UNEXPECTED = "unexpected_currency"
RULE_MINORITY = "minority_currency"
CELLS_WITH_CURRENCY = "cells_with_explicit_currency"
CELLS_WITHOUT_CURRENCY = "cells_without_currency"
CURRENCY_CELLS_UNREADABLE = "currency_cells_unreadable"


class CurrencyConsistencyConfig(DetectorConfig):
    fields: list[FieldId] | None = plannable(
        None, description="Monetary fields to check; None: every mapped field with role monetary."
    )
    currency_field: FieldId | None = plannable(
        None, description="Field holding each row's currency; None: the field with role currency."
    )
    severity: Severity = plannable(Severity.MEDIUM, description="Severity of the findings.")
    max_cells_per_issue: int = plannable(
        50, ge=1, le=1000, description="The most cells a grouped finding lists."
    )
    expected_currency: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 code every explicit marker should carry (None: not checked).",
    )


@dataclass(frozen=True, slots=True)
class _Marker:
    column: Column
    code: str
    source: str  # "cell", "header", "currency column"
    ref: CellRef


@dataclass(slots=True)
class _Group:
    """Cells marked with one currency (per column for ``unexpected_currency``)."""

    code: str
    column: Column | None
    rows: list[Row] = field(default_factory=list)
    refs: list[CellRef] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    seen: set[tuple[str, str]] = field(default_factory=set)  # (row id, column id)

    def add(self, row: Row, column: Column, ref: CellRef, source: str) -> None:
        self.sources.add(source)
        key = (row.row_id, column.column_id)
        if key in self.seen:
            return
        self.seen.add(key)
        if not self.rows or self.rows[-1].row_id != row.row_id:
            self.rows.append(row)
        self.refs.append(ref)


class CurrencyConsistencyDetector(Detector[CurrencyConsistencyConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.currency_consistency",
        name="Currency consistency",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Finds explicit currency markers that disagree within a row, differ from the "
            "expected currency, or stand out from the rest of a table."
        ),
        supported_data_types=(DataType.NUMBER,),
        applicability="Tables with mapped monetary fields and at least one explicit currency.",
        evidence_classes=(
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
            EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
        ),
        issue_categories=(IssueCategory.CURRENCY,),
        limitations=(
            "Only explicit markers are compared; amounts without a currency marker are never "
            "assumed to be in a default currency.",
            "Ambiguous symbols such as '$' are not resolved to a currency.",
        ),
        cost="low",
    )
    config_model = CurrencyConsistencyConfig

    def applicability(
        self, context: ValidationContext, config: CurrencyConsistencyConfig
    ) -> Applicability:
        tables = [
            table.name
            for table in context.tables()
            if _monetary_columns(context, config, table) and _has_marker(context, config, table)
        ]
        if not tables:
            return Applicability.no(
                "No table has an amount explicitly marked with a currency (unmarked amounts "
                "are never assumed to be in one)."
            )
        return Applicability.yes(f"Explicit currency markers found in: {', '.join(tables)}.")

    def validate(
        self, context: ValidationContext, config: CurrencyConsistencyConfig
    ) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            monetary = _monetary_columns(context, config, table)
            if monetary:
                _TableCheck(self.spec, context, config, table, monetary, result).run()
        return result


def _monetary_columns(
    context: ValidationContext, config: CurrencyConsistencyConfig, table: Table
) -> list[Column]:
    field_ids = config.fields
    if field_ids is None:
        field_ids = [f.field_id for f in context.profile.fields_with_role(FieldRole.MONETARY)]
    columns = [table.column_for_field(field_id) for field_id in field_ids]
    return [column for column in columns if column is not None]


def _currency_column(
    context: ValidationContext, config: CurrencyConsistencyConfig, table: Table
) -> Column | None:
    if config.currency_field is not None:
        return table.column_for_field(config.currency_field)
    for profile_field in context.profile.fields_with_role(FieldRole.CURRENCY):
        column = table.column_for_field(profile_field.field_id)
        if column is not None:
            return column
    return None


def _has_marker(
    context: ValidationContext, config: CurrencyConsistencyConfig, table: Table
) -> bool:
    monetary = _monetary_columns(context, config, table)
    if any(column.header_currency for column in monetary):
        return True
    currency_column = _currency_column(context, config, table)
    for row in context.rows(table, kinds=None):
        for column in monetary:
            value = context.number_value_at(row, column.column_id)
            if value is not None and value.currency:
                return True
        if currency_column is not None and context.text_at(row, currency_column.column_id):
            return True
    return False


class _TableCheck:
    def __init__(
        self,
        spec: DetectorSpec,
        context: ValidationContext,
        config: CurrencyConsistencyConfig,
        table: Table,
        monetary: list[Column],
        result: DetectorResult,
    ) -> None:
        self.spec, self.context, self.config, self.table = spec, context, config, table
        self.monetary, self.result = monetary, result
        self.currency_column = _currency_column(context, config, table)

    def run(self) -> None:
        conflicts: set[str] = set()
        unexpected: dict[tuple[str, str], _Group] = {}
        by_currency: dict[str, _Group] = {}  # effective currency of each monetary cell
        for row in self.context.rows(self.table, kinds=None):
            with row_guard(self.result, self.table, row):
                markers, cells = self._row(row)
                if cells:
                    self.result.count(Coverage.ROWS_CHECKED)
                codes = list(dict.fromkeys(marker.code for marker in markers))
                if len(codes) > 1:
                    conflicts.add(row.row_id)
                    self.context.checkpoint()
                    self.result.add(self._conflict(row, markers, codes))
                expected = self.config.expected_currency
                for marker in markers:
                    if expected is not None and marker.code != expected:
                        key = (marker.column.column_id, marker.code)
                        group = unexpected.setdefault(key, _Group(marker.code, marker.column))
                        group.add(row, marker.column, marker.ref, marker.source)
                for column, code, ref in cells:
                    if code is not None:
                        group = by_currency.setdefault(code, _Group(code, None))
                        group.add(row, column, ref, "cell")
        for group in unexpected.values():
            self.result.add(self._unexpected(group))
        if self.config.expected_currency is None and self.currency_column is None:
            self._minorities(by_currency, conflicts)

    def _row(self, row: Row) -> tuple[list[_Marker], list[tuple[Column, str | None, CellRef]]]:
        """The row's explicit markers, and each usable monetary cell with its currency."""
        markers: list[_Marker] = []
        row_code: str | None = None
        if self.currency_column is not None:
            text = self.context.text_at(row, self.currency_column.column_id)
            if text:
                row_code = self.context.currencies.resolve_token(text)
                if row_code is None:
                    self.result.count(CURRENCY_CELLS_UNREADABLE)
                else:
                    ref = self.context.cell_ref(self.table, row, self.currency_column.column_id)
                    markers.append(_Marker(self.currency_column, row_code, "currency column", ref))
        cells: list[tuple[Column, str | None, CellRef]] = []
        for column in self.monetary:
            value = self.context.number_value_at(row, column.column_id)
            if value is None:
                continue
            ref = self.context.cell_ref(self.table, row, column.column_id)
            if value.currency:
                markers.append(_Marker(column, value.currency, "cell", ref))
            if column.header_currency:
                markers.append(_Marker(column, column.header_currency, "header", ref))
            code = value.currency or column.header_currency or row_code
            self.result.count(CELLS_WITH_CURRENCY if code else CELLS_WITHOUT_CURRENCY)
            cells.append((column, code, ref))
        return markers, cells

    def _label(self, column: Column) -> str:
        field_id = column.mapped_semantic_field
        if field_id is not None:
            return field_label(self.context, field_id)
        return column.original_header or column.normalized_name

    def _source_text(self, marker: _Marker) -> str:
        if marker.source == "header":
            return f"header '{marker.column.original_header or marker.column.normalized_name}'"
        return marker.source

    # ---------------------------------------------------------------- findings
    def _conflict(self, row: Row, markers: list[_Marker], codes: list[str]) -> ValidationIssue:
        listed = "; ".join(
            f"{self._label(marker.column)}: {marker.code} ({self._source_text(marker)})"
            for marker in markers
        )
        refs = list({(ref.row_id, ref.column_id): ref for ref in (m.ref for m in markers)}.values())
        codes_text = " and ".join(codes)
        return self.context.issues.create(
            self.spec,
            rule_id=RULE_ROW_CONFLICT,
            category=IssueCategory.CURRENCY,
            severity=self.config.severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=f"Amounts in row {row.source_row_number} are marked {codes_text}",
            explanation=clip(
                f"{row_label(self.table, row)}: the currency markers of one row disagree "
                f"({listed}). Amounts of one row must be in one currency; a product or sum of "
                "them is meaningless.",
                2000,
            ),
            table=self.table,
            row=row,
            cells=refs,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Currency markers",
                    detail=clip(listed, 1000),
                    cells=refs,
                    data={"currencies": ", ".join(codes)},
                )
            ],
            suggested_action=(
                "Check which currency the row's amounts are in and correct the markers."
            ),
            subject="currencies",
        )

    def _unexpected(self, group: _Group) -> ValidationIssue:
        assert group.column is not None
        expected = self.config.expected_currency
        label = self._label(group.column)
        count = len(group.refs)
        values = "value is" if count == 1 else "values are"
        how = ", ".join(sorted(group.sources))
        cap = self.config.max_cells_per_issue
        rows_text = describe_rows([(self.table, row) for row in group.rows])
        return self.context.issues.create(
            self.spec,
            rule_id=RULE_UNEXPECTED,
            category=IssueCategory.CURRENCY,
            severity=self.config.severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{count} {label} {values} marked {group.code}, not {expected}", 200),
            explanation=clip(
                f"'{self.table.name}': {count} {label} {values} marked {group.code} "
                f"({rows_text}; marked by: {how}), but the expected currency is {expected}.",
                2000,
            ),
            table=self.table,
            cells=group.refs[:cap],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Expected currency",
                    detail=f"Every explicit currency marker should be {expected}.",
                    data={"expected": expected, "found": group.code, "marked_by": how},
                ),
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Cells",
                    detail=clip(rows_text, 1000),
                    cells=group.refs[:cap],
                    data={"cells": count, "truncated": count > cap},
                ),
            ],
            suggested_action=(
                f"Check whether these amounts are really in {group.code}; convert or correct "
                "them, or change the expected currency."
            ),
            subject=f"{group.column.normalized_name}:{group.code}",
        )

    def _minorities(self, by_currency: dict[str, _Group], conflicts: set[str]) -> None:
        if len(by_currency) < 2:
            return
        counts = Counter({code: len(group.refs) for code, group in by_currency.items()})
        order = list(by_currency)  # first appearance
        majority = max(order, key=lambda code: (counts[code], -order.index(code)))
        summary = ", ".join(f"{code}: {counts[code]}" for code in order)
        for code in order:
            if code == majority:
                continue
            group = by_currency[code]
            kept = [
                (row, ref) for row, ref in self._cells_by_row(group) if row.row_id not in conflicts
            ]
            if not kept:
                continue
            self.context.checkpoint()
            self.result.add(self._minority(code, majority, kept, summary))

    @staticmethod
    def _cells_by_row(group: _Group) -> list[tuple[Row, CellRef]]:
        rows = {row.row_id: row for row in group.rows}
        return [(rows[ref.row_id], ref) for ref in group.refs if ref.row_id in rows]

    def _minority(
        self, code: str, majority: str, cells: list[tuple[Row, CellRef]], summary: str
    ) -> ValidationIssue:
        count = len(cells)
        cap = self.config.max_cells_per_issue
        rows = list({row.row_id: row for row, _ in cells}.values())
        refs = [ref for _, ref in cells]
        rows_text = describe_rows([(self.table, row) for row in rows])
        amounts = "amount is" if count == 1 else "amounts are"
        return self.context.issues.create(
            self.spec,
            rule_id=RULE_MINORITY,
            category=IssueCategory.CURRENCY,
            severity=self.config.severity,
            evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            title=clip(
                f"{count} {amounts} marked {code}; the rest of the table is in {majority}", 200
            ),
            explanation=clip(
                f"'{self.table.name}' has no currency column, and its marked amounts carry "
                f"several currencies ({summary}). The {code} amounts ({rows_text}) may belong to "
                "another currency on purpose or may be marked wrongly; the document does not say.",
                2000,
            ),
            table=self.table,
            cells=refs[:cap],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Currencies in the table",
                    detail=f"Marked amounts per currency: {summary}.",
                    data={"majority": majority, "currency": code, "cells": count},
                ),
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Cells",
                    detail=clip(rows_text, 1000),
                    cells=refs[:cap],
                    data={"cells": count, "truncated": count > cap},
                ),
            ],
            suggested_action=(
                f"Confirm whether these amounts are meant in {code}; if not, correct the markers "
                "or convert the amounts."
            ),
            subject=f"minority:{code}",
        )
