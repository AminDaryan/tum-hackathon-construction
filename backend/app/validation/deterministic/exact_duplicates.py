"""Exact duplicate item rows.

Two item rows of a table are exact duplicates when every compared column holds the same value:
numbers by value (``12.50`` equals ``12.5``) and currency, text and units by their normalized
value (case-folded unless ``case_sensitive``), dates and booleans by value, error literals by
code, unreadable cells by their collapsed text, empty cells as empty. Every column of the
table is compared except ``ignore_fields`` and ``ignore_columns`` (header text, compared
case-insensitively), so rows that differ only in their item code are not duplicates. Rows with
fewer than ``min_non_empty_cells`` non-empty compared cells are skipped.

Profile settings narrow the comparison (all off by default):

* ``scope``: ``table`` compares all item rows of a table; ``section`` compares the rows of one
  innermost section at a time, as ``unique_scope: section`` does for domain constraints. The
  same row in two sections (a document that repeats its structure section by section) is then
  not a duplicate. Unlike ``unique_scope``, a carry-forward row (page break) does not start a
  new scope: that rule exists because some layouts restart item letters on every page, and
  rows are compared here by their content, which a page break does not make new.
* ``required_fields``: rows with an empty cell in one of these fields are not compared, and a
  table that does not map one of them is not compared at all (rows of a document that carries
  only quantities and prices may hold equal values without being copies).
* ``relative_wording_pattern``: a row whose ``relative_wording_fields`` match it ("as before,
  but 30 cm") refers to the row before it, so it repeats word for word where different work is
  meant. Such a row is compared together with the nearest row before it in its scope that has
  no such wording: two of them are duplicates only when the rows they refer to are identical
  too.

Each group of two or more rows is one ``confirmed_rule_violation`` (medium) anchored on the
second occurrence (finding category: inconsistency). When two or more rows of the group count
toward totals and the total field holds usable amounts in one explicit currency, the finding
carries a ``potential_double_count`` financial impact: the sum of the totals of the extra
counted rows.

A row duplicated with its item code also repeats the code; ``deterministic.field_constraints``
reports that under its own rule. Neither detector suppresses the other, because a plan may
run either one alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import Field, field_validator

from app.core import patterns
from app.models.cell_rules import normalize_text
from app.models.dataset import Column, Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    FinancialImpact,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.values import (
    BooleanValue,
    DateTimeValue,
    DateValue,
    ErrorValue,
    NumberValue,
    TextValue,
)
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
from app.validation.deterministic._reference_support import (
    checked_pattern,
    clip,
    column_label,
    describe_rows,
    match_window,
    short_digest,
)
from app.validation.deterministic._support import FieldId, code_segments, field_label, row_guard

RULE_DUPLICATE = "exact_duplicate"

_ROWS_LISTED = 20
_ROW_NUMBERS_KEPT = 200
_VALUES_SHOWN = 8

ROWS_SKIPPED_REQUIRED = "rows_skipped_required_value_empty"
TABLES_SKIPPED_REQUIRED = "tables_skipped_required_field_unmapped"
RELATIVE_ROWS = "rows_with_relative_wording"
CellKey = tuple[str, ...] | None
RowKey = tuple[CellKey, ...]
Scope = str  # the innermost section's row id (scope "section"), else ""
# Rows of one group: the same scope, the same compared values and, for a row with relative
# wording, the same row it refers to (a digest of that row's key; None for rows without).
GroupKey = tuple[Scope, RowKey, str | None]


class ExactDuplicatesConfig(DetectorConfig):
    ignore_fields: list[FieldId] = plannable(
        [], description="Fields whose columns are not compared."
    )
    ignore_columns: list[str] = plannable(
        [], description="Column headers that are not compared (case-insensitive)."
    )
    case_sensitive: bool = Field(default=False, description="Compare text by exact case.")
    severity_exact_duplicate: Severity = Field(
        default=Severity.MEDIUM, description="Severity of a group of identical rows."
    )
    min_non_empty_cells: int = Field(
        default=2,
        ge=1,
        le=100,
        description="Rows with fewer non-empty compared cells are not compared.",
    )
    max_cells_per_issue: int = plannable(
        50, ge=1, le=1000, description="The most cells a finding highlights."
    )
    total_field: FieldId = plannable(
        "line_total", description="Monetary field summed for the potential double count."
    )
    scope: Literal["table", "section"] = Field(
        default="table",
        description="Compare the item rows of a whole table, or of one section at a time.",
    )
    required_fields: list[FieldId] = Field(
        default_factory=list,
        description="Rows with an empty cell in one of these fields are not compared; tables "
        "that do not map one of them are not compared.",
    )
    relative_wording_pattern: str | None = Field(
        default=None,
        description="Wording that refers to the row before ('as before'): such a row is compared "
        "together with the row it refers to.",
    )
    relative_wording_fields: list[FieldId] = Field(
        default_factory=lambda: ["description"],
        description="Fields searched for the relative wording.",
    )

    @field_validator("relative_wording_pattern")
    @classmethod
    def _valid_pattern(cls, value: str | None) -> str | None:
        return None if value is None else checked_pattern(value, groups=None)


class ExactDuplicatesDetector(Detector[ExactDuplicatesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.exact_duplicates",
        name="Exact duplicate rows",
        version="1.1.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Finds item rows that repeat another item row of the same table (or of the same "
            "section, where the profile says so) in every compared column, and the amount they "
            "may count twice."
        ),
        applicability="Every table with item rows.",
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.DUPLICATE,),
        limitations=(
            "Only exact repeats are found: a different item code, description or amount "
            "makes rows distinct.",
            "The double count is an amount at risk, not a confirmed error: some documents "
            "repeat an item on purpose.",
            "With the section scope, a row repeated in another section is not a duplicate.",
        ),
        cost="low",
    )
    config_model = ExactDuplicatesConfig

    def applicability(
        self, context: ValidationContext, config: ExactDuplicatesConfig
    ) -> Applicability:
        if not any(_compared_columns(table, config) for table in context.tables()):
            return Applicability.no("Every column is excluded from the comparison.")
        return Applicability.yes("Compares the item rows of every table.")

    def validate(self, context: ValidationContext, config: ExactDuplicatesConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            columns = _compared_columns(table, config)
            if not columns:
                continue
            unmapped = [f for f in config.required_fields if table.column_for_field(f) is None]
            if unmapped:
                labels = ", ".join(field_label(context, field) for field in unmapped)
                result.count(TABLES_SKIPPED_REQUIRED)
                result.notes.append(
                    f"Table '{table.name}': {labels} not mapped, so its rows were not compared "
                    "(a required field of this check)."
                )
                continue
            groups = self._groups(context, config, table, columns, result)
            for (_, key, after), rows in groups.items():
                if len(rows) < 2:
                    continue
                context.checkpoint()
                result.count("duplicate_groups")
                result.count("rows_duplicated", len(rows) - 1)
                result.add(self._issue(context, config, table, columns, key, after, rows))
        return result

    @staticmethod
    def _groups(
        context: ValidationContext,
        config: ExactDuplicatesConfig,
        table: Table,
        columns: Sequence[Column],
        result: DetectorResult,
    ) -> dict[GroupKey, list[Row]]:
        groups: dict[GroupKey, list[Row]] = {}
        referred: dict[Scope, RowKey] = {}  # per scope: the last row without relative wording
        for row in context.rows(table):
            with row_guard(result, table, row):
                scope = (row.section_row_id or "") if config.scope == "section" else ""
                key = tuple(
                    _cell_key(context, row, column.column_id, config.case_sensitive)
                    for column in columns
                )
                after: str | None = None
                if _relative(context, config, table, row):
                    before = referred.get(scope)
                    after = "none" if before is None else short_digest(repr(before))
                else:
                    referred[scope] = key
                if any(context.text(table, row, f) is None for f in config.required_fields):
                    result.count(ROWS_SKIPPED_REQUIRED)
                    continue
                if sum(part is not None for part in key) < config.min_non_empty_cells:
                    result.count("rows_skipped_too_few_values")
                    continue
                result.count(Coverage.ROWS_CHECKED)
                if after is not None:
                    result.count(RELATIVE_ROWS)
                groups.setdefault((scope, key, after), []).append(row)
        return groups

    def _issue(
        self,
        context: ValidationContext,
        config: ExactDuplicatesConfig,
        table: Table,
        columns: Sequence[Column],
        key: RowKey,
        after: str | None,
        rows: list[Row],
    ) -> ValidationIssue:
        filled = [column for column, part in zip(columns, key, strict=True) if part is not None]
        cells = [
            context.issues.cell_ref(table, row, column.column_id)
            for row in rows
            for column in filled
        ][: config.max_cells_per_issue]
        where = describe_rows([(table, row) for row in rows], limit=_ROWS_LISTED)
        shared = "; ".join(
            f"{column_label(context, table, column)} = "
            f"'{clip(context.text_at(rows[0], column.column_id) or '', 40)}'"
            for column in filled[:_VALUES_SHOWN]
        )
        impact = _impact(context, config, table, rows)
        consequence = (
            "the totals count it more than once"
            if impact is not None
            else f"it is listed {len(rows)} times"
        )
        left_out = len(table.columns) - len(columns)
        compared = (
            "every column" if not left_out else f"every compared column ({left_out} left out)"
        )
        located = f"{where}{_section_text(table, rows[0])}" if config.scope == "section" else where
        return context.issues.create(
            self.spec,
            rule_id=RULE_DUPLICATE,
            category=IssueCategory.DUPLICATE,
            severity=config.severity_exact_duplicate,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Rows {_row_numbers(rows)} are identical", 200),
            explanation=clip(
                f"{located} hold the same value in {compared}. If they describe the same item, "
                f"{consequence}.{_relative_note(config, after)}",
                2000,
            ),
            table=table,
            row=rows[1],
            cells=cells,
            observed_value=f"{len(rows)} identical rows",
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Identical rows",
                    detail=clip(where, 1000),
                    data={
                        "rows": len(rows),
                        "source_rows": ", ".join(
                            str(row.source_row_number) for row in rows[:_ROW_NUMBERS_KEPT]
                        ),
                        "scope": config.scope,
                        "relative_wording": after is not None,
                    },
                ),
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Shared values",
                    detail=clip(shared, 1000),
                    cells=cells[: len(filled)],
                    data={"columns_compared": len(columns), "columns_with_values": len(filled)},
                ),
            ],
            suggested_action=(
                "Check whether the same item was entered twice by mistake or is meant to be "
                "repeated. If the document comes from someone else, ask its author which rows are "
                "meant instead of deleting one yourself."
            ),
            financial_impact=impact,
            subject=short_digest(repr(key) if after is None else repr((key, after))),
        )


def _compared_columns(table: Table, config: ExactDuplicatesConfig) -> list[Column]:
    fields = set(config.ignore_fields)
    headers = {_folded(header) for header in config.ignore_columns if _folded(header)}
    return [
        column
        for column in table.columns
        if not (column.mapping is not None and column.mapping.field_id in fields)
        and _folded(column.original_header or "") not in headers
    ]


def _folded(text: str) -> str:
    return normalize_text(text).casefold()


def _relative(
    context: ValidationContext, config: ExactDuplicatesConfig, table: Table, row: Row
) -> bool:
    """Whether the row's wording refers to the row before it (``relative_wording_pattern``)."""
    pattern = config.relative_wording_pattern
    if pattern is None:
        return False
    for field_id in config.relative_wording_fields:
        text = context.text(table, row, field_id)
        if text and patterns.search(pattern, match_window(text)[0]) is not None:
            return True
    return False


def _relative_note(config: ExactDuplicatesConfig, after: str | None) -> str:
    if after is None:
        return ""
    if after == "none":
        where = " in their section" if config.scope == "section" else ""
        return f" Their wording refers to a row before them, but none comes before them{where}."
    return " Their wording refers to the row before them, and those rows are identical too."


def _section_text(table: Table, row: Row) -> str:
    """``, all in section 03.02,`` for the rows' section. Only a code of numbers is quoted: a
    code with letters may be an anonymised token rather than a code."""
    section_id = row.section_row_id
    if section_id is None:
        return ""
    code = table.row(section_id).classification.code
    segments = code_segments(code)
    if code is None or segments is None or not all(s.isascii() and s.isdigit() for s in segments):
        return ", all in one section,"
    return f", all in section {clip(code, 60)},"


def _cell_key(
    context: ValidationContext, row: Row, column_id: str, case_sensitive: bool
) -> CellKey:
    """Comparison key of one cell (``None`` = empty), from its typed value as written."""
    cell = context.cell_at(row, column_id)
    if cell is None or cell.is_empty:
        return None
    value = context.value_at(row, column_id)
    if isinstance(value, NumberValue):
        return ("number", str(value.value.normalize()), value.currency or "")
    if isinstance(value, TextValue):
        text = normalize_text(value.value)
        return ("text", text if case_sensitive else text.casefold())
    if isinstance(value, DateValue | DateTimeValue):
        return ("date", value.value.isoformat())
    if isinstance(value, BooleanValue):
        return ("boolean", str(value.value))
    if isinstance(value, ErrorValue):
        return ("error", value.code)
    raw = normalize_text(cell.raw_value or "")
    if not raw:
        return None
    return ("raw", raw if case_sensitive else raw.casefold())


def _impact(
    context: ValidationContext, config: ExactDuplicatesConfig, table: Table, rows: list[Row]
) -> FinancialImpact | None:
    """Totals of the counted rows after the first counted one, in one explicit currency."""
    if table.column_for_field(config.total_field) is None:
        return None
    extra = [row for row in rows if row.classification.counts_toward_totals is True][1:]
    if not extra:
        return None
    amounts = [context.number(table, row, config.total_field) for row in extra]
    values = [amount for amount in amounts if amount is not None]
    currencies = {context.currency_evidence(table, row, [config.total_field]) for row in extra}
    if len(values) != len(extra) or len(currencies) != 1:
        return None
    currency = currencies.pop()
    total = sum(values, Decimal(0))
    if currency is None or total == 0:
        return None
    plural = "s" if len(extra) != 1 else ""
    return FinancialImpact(
        amount=total,
        currency=currency,
        basis=f"potential double counting of {len(extra)} duplicated row{plural}",
        kind="potential_double_count",
    )


def _row_numbers(rows: Sequence[Row], limit: int = 5) -> str:
    """``'14 and 27'``, ``'14, 27 and 30'``, ``'14, 27, 30, 41 and 3 more'``."""
    numbers = [str(row.source_row_number) for row in rows]
    if len(numbers) > limit:
        return f"{', '.join(numbers[: limit - 1])} and {len(numbers) - limit + 1} more"
    return f"{', '.join(numbers[:-1])} and {numbers[-1]}"
