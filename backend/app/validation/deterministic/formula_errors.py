"""Spreadsheet formula errors, formula results the file does not store, and values linked
from other workbooks.

This detector owns two cell conditions (``app.validation.contracts.conditions``):

* ``error`` (``#REF!``, ``#DIV/0!``, ...): the spreadsheet itself stored an error as the
  cell's value -> ``confirmed_rule_violation`` (rule ``formula_error``), one finding per cell;
  when one column holds more than ``max_cells_per_issue`` cells with the same error code, one
  grouped finding for that column and code instead.
* ``unavailable`` (a formula whose result the file does not store) ->
  ``extraction_uncertainty`` (rule ``formula_result_unavailable``), per cell, grouped per
  column beyond the cap.

Every other detector abstains on such cells, so each one yields exactly one finding.

With ``flag_external_references``, values whose formula refers to another workbook
(``=[1]Sheet1!A1``, ``='C:\\path\\[Book.xlsx]Sheet'!A1``, ``=[Book.xlsx]Sheet!A1``) are grouped
per column -> ``needs_external_context`` (rule ``external_reference``): the linked workbook is
not part of the document, so the value cannot be verified from it. Error and unavailable cells
are not reported a second time for their link; their finding mentions it.

Every cell of every row is inspected (mapped and unmapped columns, every row kind) except rows
a reviewer excluded. Formulas are never evaluated: formula text is untrusted and is only
scanned by a bounded, linear tokenizer (:func:`links_other_workbook`, no regular expressions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from pydantic import Field

from app.models.dataset import Cell, CellRef, Column, Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType, ErrorValue
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._reference_support import (
    clip,
    column_key,
    column_label,
    describe_rows,
)
from app.validation.deterministic._support import row_guard, row_label

RULE_ERROR = "formula_error"
RULE_UNAVAILABLE = "formula_result_unavailable"
RULE_EXTERNAL = "external_reference"

MAX_FORMULA_CHARS = 8192  # Excel's own limit for formula text; longer text is not scanned
_MAX_CODE_CHARS = 32
_FORMULA_PREVIEW_CHARS = 160
_FORMULA_SAMPLES = 3

# Coverage keys specific to this detector (the shared ones are in conditions.Coverage).
FORMULA_CELLS = "formula_cells"
ERROR_CELLS = "error_cells"
UNAVAILABLE_CELLS = "unavailable_cells"
EXTERNAL_REFERENCE_CELLS = "external_reference_cells"
FORMULAS_NOT_SCANNED = "formulas_not_scanned_too_long"

# What each spreadsheet error literal means (generic spreadsheet semantics).
_ERROR_MEANINGS: dict[str, str] = {
    "#REF!": "a reference points to a cell, range or sheet that no longer exists",
    "#DIV/0!": "a division by zero or by an empty cell",
    "#VALUE!": "an operand has the wrong type, for example text in an arithmetic formula",
    "#NAME?": "the formula uses a name or function the spreadsheet does not recognise",
    "#N/A": "a lookup did not find a value",
    "#NUM!": "a calculation produced a number that is not valid",
    "#NULL!": "two ranges in the formula do not intersect",
    "#SPILL!": "a formula result could not spill into the neighbouring cells",
    "#CALC!": "the spreadsheet could not calculate the formula, for example an empty array",
    "#GETTING_DATA": "the value was still being retrieved from a data source when the file "
    "was saved",
}

# Values that can be "computed from another workbook" and are not owned by another finding:
# ambiguous and failed cells belong to data_type_conformance, errors and unavailable results
# are reported here with a note about the link.
_LINKABLE_CONDITIONS = frozenset(
    {CellCondition.USABLE, CellCondition.INFERRED, CellCondition.TEXT, CellCondition.MARKER}
)


class FormulaErrorsConfig(DetectorConfig):
    flag_external_references: bool = Field(
        default=True,
        description="Report values whose formula refers to another workbook (profile switch).",
    )
    severity: Severity = plannable(
        Severity.HIGH, description="Severity of spreadsheet error values (formula_error)."
    )
    severity_formula_result_unavailable: Severity = Field(
        default=Severity.MEDIUM,
        description="Severity of formulas without a stored result (profile).",
    )
    severity_external_reference: Severity = Field(
        default=Severity.LOW, description="Severity of links to other workbooks (profile)."
    )
    max_cells_per_issue: int = plannable(
        50,
        ge=1,
        le=1000,
        description="Cells of one column and error code reported one by one; more are grouped "
        "into one finding that highlights this many cells.",
    )


@dataclass(frozen=True, slots=True)
class _Hit:
    """One reported cell."""

    row: Row
    column: Column
    cell: Cell
    ref: CellRef
    linked: bool  # the formula refers to another workbook


@dataclass(slots=True)
class _TableHits:
    """Reported cells of one table, grouped as their findings will be."""

    errors: dict[tuple[str, str], list[_Hit]] = field(default_factory=dict)  # (column, code)
    unavailable: dict[str, list[_Hit]] = field(default_factory=dict)  # column id
    linked: dict[str, list[_Hit]] = field(default_factory=dict)  # column id


class FormulaErrorsDetector(Detector[FormulaErrorsConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.formula_errors",
        name="Spreadsheet formula errors and missing formula results",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Reports cells whose stored value is a spreadsheet error (#REF!, #DIV/0!, #N/A, "
            "...) as confirmed rule violations, formula cells whose result the file does not "
            "store as extraction uncertainty, and values computed from another workbook as "
            "needing external context. Inspects every cell of every table, mapped or not; "
            "formulas are never evaluated."
        ),
        supported_data_types=(DataType.ERROR, DataType.UNKNOWN, DataType.NUMBER, DataType.TEXT),
        applicability=(
            "Every dataset. Findings need formulas or error values, so delimited text (CSV) "
            "sources normally produce none."
        ),
        evidence_classes=(
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
            EvidenceClass.EXTRACTION_UNCERTAINTY,
            EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
        ),
        issue_categories=(IssueCategory.FORMULA_ERROR,),
        limitations=(
            "Formulas are never evaluated: a formula without a stored result is reported as "
            "unavailable, never recomputed.",
            "Links to other workbooks are recognised from the formula syntax ([n] or "
            "[Book.xlsx] prefixes and quoted paths before '!'); links hidden in defined names "
            "or in text passed to INDIRECT are not detected.",
            f"Formula text longer than {MAX_FORMULA_CHARS:,} characters (Excel's limit) is not "
            "scanned for links; such formulas are counted in the coverage.",
            "Rows a reviewer excluded are not inspected.",
        ),
        cost="low",
    )
    config_model = FormulaErrorsConfig

    def validate(self, context: ValidationContext, config: FormulaErrorsConfig) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            hits = _TableHits()
            for row in context.rows(table, None):
                with row_guard(result, table, row):
                    _scan_row(context, config, table, row, hits, result)
            self._report_table(context, config, table, hits, result)
        skipped = result.coverage.get(FORMULAS_NOT_SCANNED, 0)
        if skipped:
            result.notes.append(
                f"{skipped} formula(s) longer than {MAX_FORMULA_CHARS:,} characters were not "
                "scanned for links to other workbooks."
            )
        return result

    # ------------------------------------------------------------------ reporting
    def _report_table(
        self,
        context: ValidationContext,
        config: FormulaErrorsConfig,
        table: Table,
        hits: _TableHits,
        result: DetectorResult,
    ) -> None:
        cap = config.max_cells_per_issue
        for (_, code_key), group in hits.errors.items():
            context.checkpoint()
            if len(group) <= cap:
                for hit in group:
                    result.add(self._error_issue(context, config, table, hit, code_key))
            else:
                result.add(self._error_group_issue(context, config, table, group, code_key))
        for group in hits.unavailable.values():
            context.checkpoint()
            if len(group) <= cap:
                for hit in group:
                    result.add(self._unavailable_issue(context, config, table, hit))
            else:
                result.add(self._unavailable_group_issue(context, config, table, group))
        for group in hits.linked.values():
            context.checkpoint()
            result.add(self._linked_issue(context, config, table, group))

    def _error_issue(
        self,
        context: ValidationContext,
        config: FormulaErrorsConfig,
        table: Table,
        hit: _Hit,
        code_key: str,
    ) -> ValidationIssue:
        code = _error_code(context, hit.row, hit.column)
        label = column_label(context, table, hit.column)
        meaning = _ERROR_MEANINGS.get(code_key)
        formula = _formula(hit.cell)
        formula_text = f"The cell holds the formula {formula}; " if formula else ""
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.VALUE,
                label="Stored error value",
                detail=f"{label} shows {code}"
                + (f" with the formula {formula}." if formula else "."),
                cells=[hit.ref],
                data={"error_code": code, "formula": formula},
            ),
            _error_rule(code, meaning),
            *_link_notes([hit]),
        ]
        return context.issues.create(
            self.spec,
            rule_id=RULE_ERROR,
            category=IssueCategory.FORMULA_ERROR,
            severity=config.severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Formula error {code} in {label}", 200),
            explanation=(
                f"{row_label(table, hit.row)}: {label} shows the spreadsheet error {code}"
                + (f" ({meaning})" if meaning else "")
                + f". {formula_text}the spreadsheet itself stored this error as the cell's "
                "value, so the value is unknown and checks that need it abstain."
            ),
            table=table,
            row=hit.row,
            cells=[hit.ref],
            observed_value=code,
            evidence=evidence,
            suggested_action=_error_action(meaning),
            subject=code_key,
        )

    def _error_group_issue(
        self,
        context: ValidationContext,
        config: FormulaErrorsConfig,
        table: Table,
        group: list[_Hit],
        code_key: str,
    ) -> ValidationIssue:
        column = group[0].column
        code = _error_code(context, group[0].row, group[0].column)
        label = column_label(context, table, column)
        meaning = _ERROR_MEANINGS.get(code_key)
        listed = group[: config.max_cells_per_issue]
        rows = describe_rows([(table, hit.row) for hit in group])
        evidence = [
            EvidenceItem(
                kind=EvidenceKind.VALUE,
                label="Stored error values",
                detail=f"{len(group)} cells of {label} show {code}; the first {len(listed)} are "
                f"highlighted. Example formulas: {_formula_samples(group)}.",
                cells=[hit.ref for hit in listed],
                data={
                    "error_code": code,
                    "cells": len(group),
                    "cells_highlighted": len(listed),
                },
            ),
            _error_rule(code, meaning),
            *_link_notes(group),
        ]
        return context.issues.create(
            self.spec,
            rule_id=RULE_ERROR,
            category=IssueCategory.FORMULA_ERROR,
            severity=config.severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{len(group)} cells in {label} show formula error {code}", 200),
            explanation=(
                f"{label} of table '{table.name}' shows the spreadsheet error {code} in "
                f"{len(group)} cells ({rows})"
                + (f": {meaning}" if meaning else "")
                + ". The spreadsheet itself stored these errors as the cells' values, so the "
                "values are unknown and checks that need them abstain. They are reported as "
                f"one finding; the first {len(listed)} cells are highlighted."
            ),
            table=table,
            cells=[hit.ref for hit in listed],
            observed_value=code,
            evidence=evidence,
            suggested_action=_error_action(meaning),
            subject=f"{column_key(column)}:{code_key}",
        )

    def _unavailable_issue(
        self, context: ValidationContext, config: FormulaErrorsConfig, table: Table, hit: _Hit
    ) -> ValidationIssue:
        label = column_label(context, table, hit.column)
        formula = _formula(hit.cell) or "(formula text not available)"
        return context.issues.create(
            self.spec,
            rule_id=RULE_UNAVAILABLE,
            category=IssueCategory.FORMULA_ERROR,
            severity=config.severity_formula_result_unavailable,
            evidence_class=EvidenceClass.EXTRACTION_UNCERTAINTY,
            title=clip(f"Formula result not stored in the file: {label}", 200),
            explanation=(
                f"{row_label(table, hit.row)}: {label} holds the formula {formula}, but the file "
                "does not store its result (it was saved without calculating, or by a program "
                "that does not store results). Formulas are never evaluated here, so the value "
                "is unknown and checks that need it abstain."
            ),
            table=table,
            row=hit.row,
            cells=[hit.ref],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Formula without a stored result",
                    detail=f"{label}: {formula}",
                    cells=[hit.ref],
                    data={"formula": formula},
                ),
                *_link_notes([hit]),
            ],
            suggested_action=_UNAVAILABLE_ACTION,
        )

    def _unavailable_group_issue(
        self,
        context: ValidationContext,
        config: FormulaErrorsConfig,
        table: Table,
        group: list[_Hit],
    ) -> ValidationIssue:
        column = group[0].column
        label = column_label(context, table, column)
        listed = group[: config.max_cells_per_issue]
        rows = describe_rows([(table, hit.row) for hit in group])
        return context.issues.create(
            self.spec,
            rule_id=RULE_UNAVAILABLE,
            category=IssueCategory.FORMULA_ERROR,
            severity=config.severity_formula_result_unavailable,
            evidence_class=EvidenceClass.EXTRACTION_UNCERTAINTY,
            title=clip(
                f"Formula results not stored in the file: {len(group)} cells in {label}", 200
            ),
            explanation=(
                f"{label} of table '{table.name}' has {len(group)} formula cells ({rows}) whose "
                "results the file does not store (it was saved without calculating, or by a "
                "program that does not store results). Formulas are never evaluated here, so "
                "the values are unknown and checks that need them abstain. They are reported "
                f"as one finding; the first {len(listed)} cells are highlighted."
            ),
            table=table,
            cells=[hit.ref for hit in listed],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Formulas without a stored result",
                    detail=f"Example formulas: {_formula_samples(group)}.",
                    cells=[hit.ref for hit in listed],
                    data={"cells": len(group), "cells_highlighted": len(listed)},
                ),
                *_link_notes(group),
            ],
            suggested_action=_UNAVAILABLE_ACTION,
            subject=column_key(column),
        )

    def _linked_issue(
        self,
        context: ValidationContext,
        config: FormulaErrorsConfig,
        table: Table,
        group: list[_Hit],
    ) -> ValidationIssue:
        column = group[0].column
        label = column_label(context, table, column)
        listed = group[: config.max_cells_per_issue]
        count = len(group)
        values = "1 value" if count == 1 else f"{count} values"
        verb = "is" if count == 1 else "are"
        rows = describe_rows([(table, hit.row) for hit in group])
        return context.issues.create(
            self.spec,
            rule_id=RULE_EXTERNAL,
            category=IssueCategory.FORMULA_ERROR,
            severity=config.severity_external_reference,
            evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            title=clip(f"{values} in {label} {verb} computed from another workbook", 200),
            explanation=(
                f"{label} of table '{table.name}': {values} ({rows}) {verb} computed by formulas "
                f"that refer to another workbook, for example {_formula(group[0].cell)}. The "
                "linked workbook is not part of this document, so these values cannot be "
                "verified from it; they are the results stored when the file was last saved."
                + (
                    f" The first {len(listed)} cells are highlighted."
                    if count > len(listed)
                    else ""
                )
            ),
            table=table,
            cells=[hit.ref for hit in listed],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Formulas referring to another workbook",
                    detail=f"Example formulas: {_formula_samples(group)}.",
                    cells=[hit.ref for hit in listed],
                    data={"cells": count, "cells_highlighted": len(listed)},
                ),
                EvidenceItem(
                    kind=EvidenceKind.NOTE,
                    label="Outside this document",
                    detail="The values are the results the spreadsheet stored when the file was "
                    "last saved; whether the linked workbook still holds the same figures cannot "
                    "be checked here.",
                ),
            ],
            suggested_action=(
                "Obtain the linked workbook to verify these values, or replace the links with "
                "values in the source file and upload it again."
            ),
            subject=column_key(column),
        )


_UNAVAILABLE_ACTION = (
    "Open the file in a spreadsheet application and save it so the formula results are stored, "
    "then upload it again."
)


# ---------------------------------------------------------------------------- scanning
def _scan_row(
    context: ValidationContext,
    config: FormulaErrorsConfig,
    table: Table,
    row: Row,
    hits: _TableHits,
    result: DetectorResult,
) -> None:
    """Classify every cell of one row and collect the cells this detector reports."""
    result.count(Coverage.ROWS_CHECKED)
    for column in table.columns:
        cell = context.cell_at(row, column.column_id)
        if cell is None:
            continue
        result.count(Coverage.CELLS_CHECKED)
        condition = cell_condition(cell)
        linked = False
        if cell.formula is not None:
            result.count(FORMULA_CELLS)
            linked = _links(config, cell.formula.expression, result)
        if condition is CellCondition.ERROR:
            key = (column.column_id, _error_code(context, row, column).upper())
            hits.errors.setdefault(key, []).append(_hit(context, table, row, column, cell, linked))
            result.count(ERROR_CELLS)
        elif condition is CellCondition.UNAVAILABLE:
            group = hits.unavailable.setdefault(column.column_id, [])
            group.append(_hit(context, table, row, column, cell, linked))
            result.count(UNAVAILABLE_CELLS)
        elif linked and condition in _LINKABLE_CONDITIONS:
            group = hits.linked.setdefault(column.column_id, [])
            group.append(_hit(context, table, row, column, cell, linked))
            result.count(EXTERNAL_REFERENCE_CELLS)


def _hit(
    context: ValidationContext, table: Table, row: Row, column: Column, cell: Cell, linked: bool
) -> _Hit:
    ref = context.issues.cell_ref(table, row, column.column_id)
    return _Hit(row=row, column=column, cell=cell, ref=ref, linked=linked)


def _links(config: FormulaErrorsConfig, expression: str, result: DetectorResult) -> bool:
    if not config.flag_external_references:
        return False
    if len(expression) > MAX_FORMULA_CHARS:
        result.count(FORMULAS_NOT_SCANNED)
        return False
    return links_other_workbook(expression)


# ---------------------------------------------------------------------------- texts
def _error_code(context: ValidationContext, row: Row, column: Column) -> str:
    """The error literal as stored (bounded, whitespace collapsed)."""
    value = context.value_at(row, column.column_id)
    cell = context.cell_at(row, column.column_id)
    raw = cell.raw_value if cell is not None else None
    code = value.code if isinstance(value, ErrorValue) else (raw or "")
    return clip(" ".join(code.split()) or "error", _MAX_CODE_CHARS)


def _formula(cell: Cell) -> str | None:
    if cell.formula is None or not cell.formula.expression:
        return None
    return clip(cell.formula.expression, _FORMULA_PREVIEW_CHARS)


def _formula_samples(group: list[_Hit]) -> str:
    samples: list[str] = []
    for hit in group:
        formula = _formula(hit.cell)
        if formula and formula not in samples:
            samples.append(formula)
        if len(samples) == _FORMULA_SAMPLES:
            break
    return "; ".join(samples) if samples else "(formula text not available)"


def _error_rule(code: str, meaning: str | None) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.RULE,
        label="Spreadsheet error value",
        detail=(
            f"{code} is an error value that the spreadsheet application itself computed and "
            "stored" + (f": {meaning}." if meaning else ".")
        ),
        data={"error_code": code},
    )


def _error_action(meaning: str | None) -> str:
    cause = f" (the cell shows that {meaning})" if meaning else ""
    return (
        f"Correct the formula or its inputs in the source workbook{cause}, recalculate, save "
        "and upload the file again."
    )


def _link_notes(group: list[_Hit]) -> list[EvidenceItem]:
    linked = sum(hit.linked for hit in group)
    if not linked:
        return []
    return [
        EvidenceItem(
            kind=EvidenceKind.NOTE,
            label="Formula refers to another workbook",
            detail=(
                f"{linked} of these formula(s) refer to another workbook, which is not part of "
                "this document; it must be available when the file is recalculated."
            ),
            data={"cells_linking_other_workbooks": linked},
        )
    ]


# ---------------------------------------------------------------------------- links
def links_other_workbook(expression: str) -> bool:
    """True when formula text refers to another workbook.

    Recognised forms (alone or inside larger expressions): ``[1]Sheet1!A1`` (the index form
    files store), ``[Book.xlsx]Sheet1!A1``, ``[1]!Name`` (a workbook-level name), 3-D ranges
    ``[1]Sheet1:Sheet3!A1``, and quoted prefixes holding a bracket or a path,
    ``'C:\\path\\[Book.xlsx]Sheet 1'!A1``, ``'https://host/[Book.xlsx]Sheet'!A1``,
    ``'C:\\path\\Book.xlsx'!Name`` (sheet names cannot contain ``[ ] \\ /``).

    Not links: text in string literals (``="[1]Sheet1!A1"``), structured table references
    (``Table1[Amount]``, ``[@Qty]``, ``Table1[[#This Row],[Qty]]``) and R1C1 offsets
    (``R[1]C[2]``). The scan is one linear pass without regular expressions; callers bound the
    length (:data:`MAX_FORMULA_CHARS`)."""
    if "!" not in expression or ("[" not in expression and "'" not in expression):
        return False
    length = len(expression)
    index = 0
    while index < length:
        char = expression[index]
        if char == '"':
            index = _after_quoted(expression, index, '"')
        elif char == "'":
            end = _after_quoted(expression, index, "'")
            if end < length and expression[end] == "!" and _holds_path(expression[index:end]):
                return True
            index = end
        elif char == "[":
            end = _after_brackets(expression, index)
            if not _after_name(expression, index) and _sheet_reference_follows(expression, end):
                return True
            index = end
        else:
            index += 1
    return False


def _after_quoted(text: str, start: int, quote: str) -> int:
    """Index after the literal opened by ``quote`` at ``start`` (a doubled quote is an
    escaped quote); ``len(text)`` when it is not closed."""
    index = start + 1
    while True:
        close = text.find(quote, index)
        if close < 0:
            return len(text)
        if close + 1 < len(text) and text[close + 1] == quote:
            index = close + 2
            continue
        return close + 1


def _after_brackets(text: str, start: int) -> int:
    """Index after the bracket group opened at ``start`` (nested groups, as in structured
    references, and the ``'`` escape of structured references are respected)."""
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "'":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _holds_path(quoted: str) -> bool:
    return any(char in quoted for char in "[]\\/")


def _is_name_char(char: str) -> bool:
    return char.isalnum() or char in "_."


def _after_name(text: str, index: int) -> bool:
    """True when the bracket at ``index`` continues a name (``Table1[``, ``R[``): a structured
    reference or an R1C1 offset, not a workbook prefix."""
    return index > 0 and _is_name_char(text[index - 1])


def _sheet_reference_follows(text: str, index: int) -> bool:
    """A sheet name (possibly empty or quoted, or a 3-D range of names) and then ``!``."""
    length = len(text)
    if index < length and text[index] == "'":
        end = _after_quoted(text, index, "'")
        return end < length and text[end] == "!"
    index = _skip_name(text, index)
    if index < length and text[index] == ":":
        index = _skip_name(text, index + 1)
    return index < length and text[index] == "!"


def _skip_name(text: str, index: int) -> int:
    while index < len(text) and _is_name_char(text[index]):
        index += 1
    return index
