"""Domain constraints on text: patterns, allowed values and unique identifiers.

For every field with a text rule (the profile's ``FieldConstraints``, or the profile's settings
for this detector, whose ``constraints`` replace the field's), on item rows:

* ``pattern``: the value must match the whole pattern, case-insensitively, through
  :mod:`app.core.patterns` (a value longer than ``MAX_MATCH_CHARS`` never matches): low;
* ``allowed_values``: compared case-insensitively after whitespace is collapsed: medium;
* ``unique``: one finding per group of rows sharing a value: medium. Identifier fields compare
  by :func:`app.core.codes.normalize_code` (case, spaces and trailing dots ignored; leading
  zeros kept, so ``01.10`` and ``1.10`` differ); other fields by case-folded collapsed text,
  or the exact text with ``case_sensitive_unique``. ``unique_scope: table`` compares all item
  rows of a table; ``section`` compares rows of the same innermost section, and a
  carry-forward row (page break) starts a new scope, because some layouts restart item
  letters on every page.

All findings are ``confirmed_rule_violation``. More than ``max_cells_per_issue`` pattern or
allowed-value failures of one field form one grouped finding. Empty cells (required_values),
markers and unreadable cells (their owners) are skipped. Numeric bounds belong to
``deterministic.numeric_validity``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field

from app.core import patterns
from app.models.cell_rules import normalize_text
from app.models.dataset import CellRef, Row, RowKind, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    JsonScalar,
    Severity,
    ValidationIssue,
)
from app.models.profile import FieldConstraints, FieldRole, SemanticField
from app.models.values import DataType
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition
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
from app.validation.deterministic._support import (
    FieldId,
    field_label,
    normalize_code,
    row_guard,
    row_label,
)

RULE_PATTERN = "pattern"
RULE_ALLOWED = "allowed_values"
RULE_UNIQUE = "unique"

_VALUE_CONDITIONS = frozenset({CellCondition.TEXT, CellCondition.USABLE, CellCondition.INFERRED})
_SHOWN_CHARS = 60
_ROWS_LISTED = 20
_ROW_NUMBERS_KEPT = 200


class FieldConstraintsConfig(DetectorConfig):
    fields: list[FieldId] | None = plannable(
        None,
        description=(
            "Fields to check; None = every field with a pattern, allowed values or a "
            "uniqueness rule."
        ),
    )
    constraints: dict[FieldId, FieldConstraints] = Field(
        default_factory=dict,
        description="Constraints per field id, replacing the profile's for that field.",
    )
    max_cells_per_issue: int = plannable(
        50,
        ge=1,
        le=1000,
        description=(
            "Pattern or allowed-value failures of one field beyond which they form one "
            "finding; also the most cells a finding highlights."
        ),
    )
    case_sensitive_unique: bool = Field(
        default=False,
        description="Compare values of non-identifier fields for uniqueness by exact text.",
    )
    severity_pattern: Severity = Field(
        default=Severity.LOW, description="Severity of values that do not match the pattern."
    )
    severity_allowed_values: Severity = Field(
        default=Severity.MEDIUM, description="Severity of values not among the allowed ones."
    )
    severity_unique: Severity = Field(
        default=Severity.MEDIUM, description="Severity of repeated values of a unique field."
    )

    def severity_of(self, rule: str) -> Severity:
        return {
            RULE_PATTERN: self.severity_pattern,
            RULE_ALLOWED: self.severity_allowed_values,
            RULE_UNIQUE: self.severity_unique,
        }[rule]


@dataclass(frozen=True, slots=True)
class _Hit:
    row: Row
    text: str
    ref: CellRef
    scope: tuple[str, int]  # (innermost section row id, carry-forward rows seen before)


class FieldConstraintsDetector(Detector[FieldConstraintsConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.field_constraints",
        name="Domain constraints",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Checks item rows against the patterns, allowed values and uniqueness rules the "
            "profile sets for their fields, such as unique item codes."
        ),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables mapping a field with a pattern, allowed values or a uniqueness rule.",
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(IssueCategory.CONSTRAINT,),
        limitations=(
            "A value longer than 500 characters never matches a pattern.",
            "Identifiers are compared ignoring case, spaces and trailing dots, but not leading "
            "zeros: '01.10' and '1.10' are different codes here.",
        ),
        cost="low",
    )
    config_model = FieldConstraintsConfig

    def applicability(
        self, context: ValidationContext, config: FieldConstraintsConfig
    ) -> Applicability:
        fields = _fields(context, config)
        mapped = [
            table.name
            for table in context.tables()
            if any(table.column_for_field(field.field_id) for field, _ in fields)
        ]
        if not mapped:
            return Applicability.no(
                "No mapped field has a pattern, allowed values or a uniqueness rule."
            )
        return Applicability.yes(f"Fields with text rules are mapped in: {', '.join(mapped)}.")

    def validate(
        self, context: ValidationContext, config: FieldConstraintsConfig
    ) -> DetectorResult:
        result = DetectorResult()
        for table in context.tables():
            for field_def, rules in _fields(context, config):
                if table.column_for_field(field_def.field_id) is None:
                    continue
                source = (
                    "the profile's settings for this detector"
                    if field_def.field_id in config.constraints
                    else "the profile's field constraints"
                )
                check = _FieldCheck(self.spec, context, config, table, field_def, rules, source)
                hits = check.values(result)
                check.patterns_and_values(hits, result)
                if rules.unique:
                    check.uniqueness(hits, result)
        return result


@dataclass(frozen=True, slots=True)
class _FieldCheck:
    """The checks of one field in one table."""

    spec: DetectorSpec
    context: ValidationContext
    config: FieldConstraintsConfig
    table: Table
    field_def: SemanticField
    rules: FieldConstraints
    source: str

    @property
    def label(self) -> str:
        return field_label(self.context, self.field_def.field_id)

    def values(self, result: DetectorResult) -> list[_Hit]:
        """Item-row values of the field in source order, with their uniqueness scope."""
        column = self.table.column_for_field(self.field_def.field_id)
        assert column is not None
        hits: list[_Hit] = []
        pages = 0
        for row in self.context.rows(self.table, kinds=None):
            kind = row.classification.kind
            if kind is RowKind.CARRY_FORWARD:
                pages += 1
                continue
            if kind is not RowKind.ITEM:
                continue
            with row_guard(result, self.table, row):
                cell = self.context.cell_at(row, column.column_id)
                if cell_condition(cell) not in _VALUE_CONDITIONS:
                    continue
                text = self.context.text_at(row, column.column_id)
                if text is None:
                    continue
                result.count(Coverage.CELLS_CHECKED)
                ref = self.context.issues.cell_ref(self.table, row, column.column_id)
                hits.append(_Hit(row, text, ref, (row.section_row_id or "", pages)))
        return hits

    # ------------------------------------------------------------ pattern, allowed values
    def patterns_and_values(self, hits: list[_Hit], result: DetectorResult) -> None:
        tests: list[tuple[str, Callable[[str], bool]]] = []
        pattern = self.rules.pattern
        if pattern is not None:
            tests.append((RULE_PATTERN, lambda text: patterns.fullmatch(pattern, text) is None))
        if self.rules.allowed_values:
            allowed = {_comparable(value) for value in self.rules.allowed_values}
            tests.append((RULE_ALLOWED, lambda text: _comparable(text) not in allowed))
        for rule, fails in tests:
            failing = [hit for hit in hits if fails(hit.text)]
            if not failing:
                continue
            result.count(f"cells_{rule}", len(failing))
            if len(failing) <= self.config.max_cells_per_issue:
                for hit in failing:
                    self.context.checkpoint()
                    result.add(self._value_issue(rule, hit))
            else:
                result.add(self._value_group(rule, failing))

    def _expectation(self, rule: str) -> tuple[str, str, str]:
        """``(expected value, the rule as a requirement, the problem)`` for explanations."""
        if rule == RULE_PATTERN:
            pattern = self.rules.pattern or ""
            return (
                clip(f"matches {pattern}", 200),
                f"match the pattern {pattern}",
                "does not have the expected format",
            )
        allowed = ", ".join(self.rules.allowed_values or ())
        return clip(f"one of: {allowed}", 200), f"be one of: {allowed}", "is not an allowed value"

    def _rule_evidence(self, rule: str) -> EvidenceItem:
        _, requirement, _ = self._expectation(rule)
        data: dict[str, JsonScalar] = {"field": self.field_def.field_id, "constraint": rule}
        if rule == RULE_PATTERN:
            data["pattern"] = self.rules.pattern or ""
        elif rule == RULE_ALLOWED:
            data["allowed_values"] = clip(", ".join(self.rules.allowed_values or ()), 1000)
        else:
            data["scope"] = self.rules.unique_scope
            requirement = f"be unique within each {self.rules.unique_scope}"
        return EvidenceItem(
            kind=EvidenceKind.RULE,
            label="Constraint",
            detail=clip(f"{self.label} must {requirement} (set by {self.source}).", 1000),
            data=data,
        )

    def _value_issue(self, rule: str, hit: _Hit) -> ValidationIssue:
        expected, requirement, problem = self._expectation(rule)
        shown = clip(hit.text, _SHOWN_CHARS)
        return self.context.issues.create(
            self.spec,
            rule_id=rule,
            category=IssueCategory.CONSTRAINT,
            severity=self.config.severity_of(rule),
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{self.label} '{shown}' {problem}", 200),
            explanation=clip(
                f"{row_label(self.table, hit.row)}: {self.label} is '{shown}', but "
                f"{self.source} require it to {requirement}.",
                2000,
            ),
            table=self.table,
            row=hit.row,
            cells=[hit.ref],
            observed_value=shown,
            expected_value=expected,
            evidence=[
                self._rule_evidence(rule),
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Value",
                    detail=f"{self.label} = '{shown}'",
                    cells=[hit.ref],
                    data={"value": shown},
                ),
            ],
            suggested_action=(
                f"Correct {self.label} in the source document, or adjust the profile's rule "
                "if this value is legitimate."
            ),
            subject=f"{self.field_def.field_id}:{rule}",
        )

    def _value_group(self, rule: str, hits: list[_Hit]) -> ValidationIssue:
        expected, requirement, _ = self._expectation(rule)
        listed = hits[: self.config.max_cells_per_issue]
        where = describe_rows([(self.table, hit.row) for hit in hits])
        problem = (
            "do not have the expected format" if rule == RULE_PATTERN else "are not allowed values"
        )
        examples = "; ".join(f"'{clip(hit.text, _SHOWN_CHARS)}'" for hit in hits[:5])
        return self.context.issues.create(
            self.spec,
            rule_id=rule,
            category=IssueCategory.CONSTRAINT,
            severity=self.config.severity_of(rule),
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{len(hits)} values in {self.label} {problem}", 200),
            explanation=clip(
                f"{len(hits)} values of {self.label} in table '{self.table.name}' ({where}) "
                f"{problem}: {self.source} require {self.label} to {requirement}. They are "
                f"reported as one finding; the first {len(listed)} cells are highlighted.",
                2000,
            ),
            table=self.table,
            cells=[hit.ref for hit in listed],
            expected_value=expected,
            evidence=[
                self._rule_evidence(rule),
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Values as written",
                    detail=clip(f"{self.label}: {examples}", 1000),
                    cells=[hit.ref for hit in listed],
                    data={"cells": len(hits), "cells_highlighted": len(listed)},
                ),
            ],
            suggested_action=(
                f"Check how {self.label} is written in the source document; if this format is "
                "legitimate, adjust the profile's rule."
            ),
            subject=f"{self.field_def.field_id}:{rule}",
        )

    # ------------------------------------------------------------ uniqueness
    def uniqueness(self, hits: list[_Hit], result: DetectorResult) -> None:
        by_section = self.rules.unique_scope == "section"
        identifier = self.field_def.role is FieldRole.IDENTIFIER
        groups: dict[tuple[tuple[str, int], str], list[_Hit]] = defaultdict(list)
        for hit in hits:
            key = _unique_key(hit.text, identifier, self.config.case_sensitive_unique)
            if key is not None:
                groups[(hit.scope if by_section else ("", 0), key)].append(hit)
        for (_, key), group in groups.items():
            if len(group) < 2:
                continue
            result.count("duplicate_groups")
            result.count("rows_duplicated", len(group) - 1)
            self.context.checkpoint()
            result.add(self._unique_issue(key, group))

    def _scope_text(self, hit: _Hit) -> tuple[str, str]:
        """``(where the rows are, the scope the rule names)``."""
        if self.rules.unique_scope != "section":
            return f"in table '{self.table.name}'", "within a table"
        section_id = hit.row.section_row_id
        code = self.table.row(section_id).classification.code if section_id else None
        where = f"in section {code}" if code else f"in one section of table '{self.table.name}'"
        return where, "within a section"

    def _unique_issue(self, key: str, hits: list[_Hit]) -> ValidationIssue:
        shown = clip(hits[0].text, _SHOWN_CHARS)
        listed = hits[: self.config.max_cells_per_issue]
        rows = describe_rows([(self.table, hit.row) for hit in hits], limit=_ROWS_LISTED)
        where, within = self._scope_text(hits[0])
        return self.context.issues.create(
            self.spec,
            rule_id=RULE_UNIQUE,
            category=IssueCategory.CONSTRAINT,
            severity=self.config.severity_unique,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"{self.label} {shown} appears {len(hits)} times", 200),
            explanation=clip(
                f"{self.label} '{shown}' appears {len(hits)} times {where} ({rows}), but "
                f"{self.source} require it to be unique {within}, so references and totals "
                "that use it cannot tell these rows apart.",
                2000,
            ),
            table=self.table,
            row=hits[1].row,
            cells=[hit.ref for hit in listed],
            observed_value=shown,
            expected_value=f"unique {within}",
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Rows with the same value",
                    detail=clip(f"{self.label} '{shown}': {rows}", 1000),
                    cells=[hit.ref for hit in listed],
                    data={
                        "value": shown,
                        "rows": len(hits),
                        "source_rows": ", ".join(
                            str(hit.row.source_row_number) for hit in hits[:_ROW_NUMBERS_KEPT]
                        ),
                    },
                ),
                self._rule_evidence(RULE_UNIQUE),
            ],
            suggested_action=(
                f"Check whether these rows are the same item entered twice (remove the extra "
                f"row) or different items that need distinct {self.label} values."
            ),
            subject=f"{self.field_def.field_id}:{RULE_UNIQUE}:{short_digest(key)}",
        )


def _fields(
    context: ValidationContext, config: FieldConstraintsConfig
) -> list[tuple[SemanticField, FieldConstraints]]:
    profile = context.profile
    ids = config.fields if config.fields is not None else [f.field_id for f in profile.fields]
    found = []
    for field_id in ids:
        field_def = profile.field(field_id)
        if field_def is None:
            continue
        rules = config.constraints.get(field_id) or field_def.constraints
        if rules is not None and (
            rules.pattern is not None or bool(rules.allowed_values) or rules.unique
        ):
            found.append((field_def, rules))
    return found


def _comparable(text: str) -> str:
    return normalize_text(text).casefold()


def _unique_key(text: str, identifier: bool, case_sensitive: bool) -> str | None:
    if identifier:
        return normalize_code(text)
    if case_sensitive:
        return text
    return _comparable(text) or None
