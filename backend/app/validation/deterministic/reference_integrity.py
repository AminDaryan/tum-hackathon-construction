"""Reference integrity: references to identifiers that do not exist in the document.

Two kinds of rules, both configured in the profile:

* **Field rules** (``rules``): a field whose value *is* a reference (a "related item" column),
  optionally several per cell split by ``separator``. A referenced code that matches no known
  identifier is a ``confirmed_rule_violation``: the document declares a reference that does not
  resolve.
* **Text references** (``text_references``): a pattern with exactly one capture group finds
  references written in text ("wie Pos. 01.02.0030", "siehe OZ 3.1.20", "as item 2.1.4"). A
  captured code that matches no known identifier ``needs_external_context``: the position may
  be in another document or lot of the same tender. A row referring to its own code is ignored.

Known identifiers are the ``target_field`` values of item rows and of section rows (plus the
section codes normalization recorded when the target field is the profile's
``section_code_field``) across all tables of the dataset, compared by code segments
(:func:`app.core.codes.code_segments`: ``01.02.0030`` equals ``1.2.30``). Resolved references
produce nothing. When some identifier cells cannot be read, an unresolved field reference is
reported as ``extraction_uncertainty`` instead (it may point at one of them). Patterns examine
the first ``MAX_MATCH_CHARS`` characters of a text (``app.core.patterns``).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field, field_validator, model_validator

from app.core.codes import code_segments
from app.models.base import FrozenModel
from app.models.dataset import Row, RowKind, Table
from app.models.issue import (
    RULE_ID_PATTERN,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.profile import FIELD_ID_PATTERN
from app.models.values import DataType
from app.validation.contracts.conditions import CellCondition, Coverage, cell_condition, skip_key
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
    find_captures,
    match_window,
)
from app.validation.deterministic._support import field_label, row_guard, row_label

MAX_REFERENCES_PER_CELL = 50  # parts of one split reference cell that are checked
_SOURCE_KINDS = frozenset({RowKind.ITEM, RowKind.SECTION, RowKind.TEXT})
_IDENTIFIER_KINDS = frozenset({RowKind.ITEM, RowKind.SECTION})
_READABLE = frozenset({CellCondition.TEXT, CellCondition.USABLE, CellCondition.INFERRED})

# Coverage keys specific to this detector.
REFERENCES_CHECKED = "references_checked"
REFERENCES_RESOLVED = "references_resolved"
REFERENCES_UNRESOLVED = "references_unresolved"
REFERENCES_SELF = "references_self_ignored"
REFERENCES_UNPARSEABLE = "references_unparseable"
REFERENCES_NOT_CHECKED = "references_not_checked_too_many"
TEXTS_TRUNCATED = "texts_truncated"


class TextReferenceRule(FrozenModel):
    """References written in ``text_field``: ``pattern`` (case-insensitive) has exactly one
    capture group, the referenced code, which must name a ``target_field`` value."""

    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    text_field: str = Field(pattern=FIELD_ID_PATTERN)
    pattern: str
    target_field: str = Field(pattern=FIELD_ID_PATTERN)

    @field_validator("pattern")
    @classmethod
    def _one_capture_group(cls, value: str) -> str:
        return checked_pattern(value, groups=1)


class FieldReferenceRule(FrozenModel):
    """``source_field`` holds references to ``target_field`` values; ``separator`` (plain
    text, not a pattern) splits several references in one cell."""

    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    source_field: str = Field(pattern=FIELD_ID_PATTERN)
    target_field: str = Field(pattern=FIELD_ID_PATTERN)
    separator: str | None = Field(default=None, min_length=1, max_length=8)


class ReferenceIntegrityConfig(DetectorConfig):
    text_references: tuple[TextReferenceRule, ...] = Field(
        default=(), description="References found in text by patterns (profile-controlled)."
    )
    rules: tuple[FieldReferenceRule, ...] = Field(
        default=(), description="Fields whose values are references (profile-controlled)."
    )
    severity_field_rule: Severity = plannable(
        Severity.MEDIUM, description="Severity of unresolved references in reference fields."
    )
    severity_text_rule: Severity = plannable(
        Severity.LOW, description="Severity of unresolved references written in text."
    )

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> ReferenceIntegrityConfig:
        ids = [rule.rule_id for rule in self.text_references]
        ids += [rule.rule_id for rule in self.rules]
        duplicates = sorted({rule_id for rule_id in ids if ids.count(rule_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate reference rule ids: {', '.join(duplicates)}")
        return self


@dataclass(frozen=True, slots=True)
class _Identifiers:
    """The known identifiers of one target field across the dataset."""

    codes: frozenset[tuple[str, ...]]
    tables: int  # tables that map the target field
    unreadable: int  # identifier cells that could not be read (error, unavailable, ...)


@dataclass(frozen=True, slots=True)
class _Reference:
    """One reference found in a cell: the code as written and its segments."""

    written: str
    segments: tuple[str, ...]
    context_text: str  # what was matched (text rules) or the cell text (field rules)


class ReferenceIntegrityDetector(Detector[ReferenceIntegrityConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="deterministic.reference_integrity",
        name="Reference integrity",
        version="1.0.0",
        category=DetectorCategory.DETERMINISTIC,
        description=(
            "Checks that references to identifiers resolve within the document: values of "
            "reference fields must name an existing identifier (confirmed rule violation when "
            "not), and references written in text (found by profile patterns, e.g. 'wie Pos. "
            "01.02.0030') that name no identifier of the document need external context (the "
            "position may be in another document or lot). Codes are compared by segments, so "
            "leading zeros do not matter."
        ),
        supported_data_types=(DataType.TEXT, DataType.NUMBER),
        applicability=(
            "At least one configured rule whose source (or text) field and target field are "
            "mapped in some table."
        ),
        evidence_classes=(
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
            EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            EvidenceClass.EXTRACTION_UNCERTAINTY,
        ),
        issue_categories=(IssueCategory.REFERENCE,),
        limitations=(
            "References in text are found only where the profile's patterns match, and only in "
            "the first 500 characters of a text; other wording is not recognised.",
            "A reference to another document or lot cannot be resolved from this document.",
            "Identifiers are compared by code segments only (separators '.' and '/', leading "
            "zeros ignored); differently structured codes for the same item do not match.",
            f"At most {MAX_REFERENCES_PER_CELL} references per reference cell are checked.",
        ),
        cost="low",
    )
    config_model = ReferenceIntegrityConfig

    def required_fields(self, config: ReferenceIntegrityConfig) -> tuple[str, ...]:
        fields = [f for rule in config.rules for f in (rule.source_field, rule.target_field)]
        fields += [f for r in config.text_references for f in (r.text_field, r.target_field)]
        return tuple(dict.fromkeys(fields))

    def applicability(
        self, context: ValidationContext, config: ReferenceIntegrityConfig
    ) -> Applicability:
        rules = [*_field_rules(config), *_text_rules(config)]
        if not rules:
            return Applicability.no("No reference rules are configured for this profile.")
        usable = [
            rule_id
            for rule_id, source, target in rules
            if _mapped_anywhere(context, source) and _mapped_anywhere(context, target)
        ]
        if not usable:
            fields = sorted({f for _, source, target in rules for f in (source, target)})
            return Applicability.no(
                "No reference rule has both its fields mapped in this dataset "
                f"(fields: {', '.join(fields)})."
            )
        return Applicability.yes(f"Reference rules with mapped fields: {', '.join(usable)}.")

    def validate(
        self, context: ValidationContext, config: ReferenceIntegrityConfig
    ) -> DetectorResult:
        result = DetectorResult()
        known: dict[str, _Identifiers | None] = {}
        for rule in config.rules:
            identifiers = self._identifiers_for(
                context, rule.rule_id, rule.source_field, rule.target_field, known, result
            )
            if identifiers is not None:
                self._check_field_rule(context, config, rule, identifiers, result)
        for text_rule in config.text_references:
            identifiers = self._identifiers_for(
                context,
                text_rule.rule_id,
                text_rule.text_field,
                text_rule.target_field,
                known,
                result,
            )
            if identifiers is not None:
                self._check_text_rule(context, config, text_rule, identifiers, result)
        truncated = result.coverage.get(TEXTS_TRUNCATED, 0)
        if truncated:
            result.notes.append(
                f"{truncated} text(s) are longer than the pattern window; only their first "
                "part was searched for references."
            )
        return result

    # ------------------------------------------------------------------ identifiers
    def _identifiers_for(
        self,
        context: ValidationContext,
        rule_id: str,
        source_field: str,
        target_field: str,
        known: dict[str, _Identifiers | None],
        result: DetectorResult,
    ) -> _Identifiers | None:
        """The identifiers a rule is checked against, or ``None`` (with a note) when the rule
        cannot be checked in this dataset."""
        if not _mapped_anywhere(context, source_field):
            result.notes.append(
                f"Reference rule '{rule_id}' was not checked: "
                f"{field_label(context, source_field)} is not mapped."
            )
            return None
        if target_field not in known:
            known[target_field] = _collect_identifiers(context, target_field)
        identifiers = known[target_field]
        target = field_label(context, target_field)
        if identifiers is None:
            result.notes.append(
                f"Reference rule '{rule_id}' was not checked: {target} is not mapped."
            )
            return None
        if not identifiers.codes:
            result.notes.append(
                f"Reference rule '{rule_id}' was not checked: no {target} values were found, so "
                "there is nothing to resolve references against."
            )
            return None
        if identifiers.unreadable:
            result.notes.append(
                f"{identifiers.unreadable} {target} cell(s) could not be read; references that "
                "do not resolve may point at one of them."
            )
        return identifiers

    # ------------------------------------------------------------------ field rules
    def _check_field_rule(
        self,
        context: ValidationContext,
        config: ReferenceIntegrityConfig,
        rule: FieldReferenceRule,
        identifiers: _Identifiers,
        result: DetectorResult,
    ) -> None:
        for table in _tables_mapping(context, rule.source_field):
            for row in context.rows(table, _SOURCE_KINDS):
                with row_guard(result, table, row):
                    text = _readable_text(context, table, row, rule.source_field, result)
                    if text is None:
                        continue
                    result.count(Coverage.ROWS_CHECKED)
                    for reference in _split_references(text, rule.separator, result):
                        result.count(REFERENCES_CHECKED)
                        if reference.segments in identifiers.codes:
                            result.count(REFERENCES_RESOLVED)
                            continue
                        result.count(REFERENCES_UNRESOLVED)
                        result.add(
                            self._field_issue(
                                context, config, rule, identifiers, table, row, reference
                            )
                        )

    def _field_issue(
        self,
        context: ValidationContext,
        config: ReferenceIntegrityConfig,
        rule: FieldReferenceRule,
        identifiers: _Identifiers,
        table: Table,
        row: Row,
        reference: _Reference,
    ) -> ValidationIssue:
        source = field_label(context, rule.source_field)
        target = field_label(context, rule.target_field)
        cell = context.cell_ref(table, row, rule.source_field)
        code = clip(reference.written, 60)
        uncertain = identifiers.unreadable > 0
        return context.issues.create(
            self.spec,
            rule_id=rule.rule_id,
            category=IssueCategory.REFERENCE,
            severity=config.severity_field_rule,
            evidence_class=(
                EvidenceClass.EXTRACTION_UNCERTAINTY
                if uncertain
                else EvidenceClass.CONFIRMED_RULE_VIOLATION
            ),
            title=clip(f"{source} {code} does not match any {target}", 200),
            explanation=(
                f"{row_label(table, row)}: {source} refers to {code}, but no item or section row "
                f"of this document has that {target} (codes are compared by their segments, so "
                "leading zeros do not matter)."
            ),
            table=table,
            row=row,
            cells=[cell],
            observed_value=reference.written,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Reference",
                    detail=f"{source}: '{clip(reference.context_text, 200)}'",
                    cells=[cell],
                    data={"referenced_code": reference.written},
                ),
                _known_evidence(identifiers, target, reference),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Reference rule",
                    detail=f"Rule '{rule.rule_id}': every {source} value must name an existing "
                    f"{target}.",
                    data={"rule_id": rule.rule_id},
                ),
                *_unreadable_note(identifiers, target),
            ],
            suggested_action=(
                f"Correct the reference in {source}, or add the missing {target} if the row was "
                "left out; if the reference points to another document, record that in the "
                "review."
            ),
            subject=".".join(reference.segments),
        )

    # ------------------------------------------------------------------ text rules
    def _check_text_rule(
        self,
        context: ValidationContext,
        config: ReferenceIntegrityConfig,
        rule: TextReferenceRule,
        identifiers: _Identifiers,
        result: DetectorResult,
    ) -> None:
        for table in _tables_mapping(context, rule.text_field):
            for row in context.rows(table, _SOURCE_KINDS):
                with row_guard(result, table, row):
                    self._check_text_row(context, config, rule, identifiers, table, row, result)

    def _check_text_row(
        self,
        context: ValidationContext,
        config: ReferenceIntegrityConfig,
        rule: TextReferenceRule,
        identifiers: _Identifiers,
        table: Table,
        row: Row,
        result: DetectorResult,
    ) -> None:
        cell = context.cell(table, row, rule.text_field)
        condition = cell_condition(cell)
        if condition is CellCondition.EMPTY:
            return
        if condition is not CellCondition.TEXT:
            key = skip_key(condition)
            result.count(key or Coverage.ROWS_SKIPPED_NOT_APPLICABLE)
            return
        text = context.text(table, row, rule.text_field) or ""
        window, truncated = match_window(text)
        if truncated:
            result.count(TEXTS_TRUNCATED)
        result.count(Coverage.ROWS_CHECKED)
        own = _own_codes(context, table, row, rule.target_field)
        seen: set[tuple[str, ...]] = set()
        for matched, written in find_captures(rule.pattern, window):
            segments = code_segments(written)
            if segments is None:
                result.count(REFERENCES_UNPARSEABLE)
                continue
            if segments in seen:
                continue
            seen.add(segments)
            if segments in own:
                result.count(REFERENCES_SELF)
                continue
            result.count(REFERENCES_CHECKED)
            if segments in identifiers.codes:
                result.count(REFERENCES_RESOLVED)
                continue
            result.count(REFERENCES_UNRESOLVED)
            reference = _Reference(written=written.strip(), segments=segments, context_text=matched)
            result.add(self._text_issue(context, config, rule, identifiers, table, row, reference))

    def _text_issue(
        self,
        context: ValidationContext,
        config: ReferenceIntegrityConfig,
        rule: TextReferenceRule,
        identifiers: _Identifiers,
        table: Table,
        row: Row,
        reference: _Reference,
    ) -> ValidationIssue:
        text_label = field_label(context, rule.text_field)
        target = field_label(context, rule.target_field)
        cell = context.cell_ref(table, row, rule.text_field)
        code = clip(reference.written, 60)
        matched = clip(" ".join(reference.context_text.split()), 120)
        return context.issues.create(
            self.spec,
            rule_id=rule.rule_id,
            category=IssueCategory.REFERENCE,
            severity=config.severity_text_rule,
            evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            title=clip(f"{text_label} refers to {code}, which is not in this document", 200),
            explanation=(
                f"{row_label(table, row)}: the {text_label} refers to {code} ('{matched}'), but "
                f"no item or section row of this document has that {target} (codes are compared "
                "by their segments, so leading zeros do not matter). The position may be in "
                "another document or lot of the same project; this document alone cannot "
                "settle it."
            ),
            table=table,
            row=row,
            cells=[cell],
            observed_value=reference.written,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Reference in the text",
                    detail=f"'{matched}'",
                    cells=[cell],
                    data={"referenced_code": reference.written, "matched_text": matched},
                ),
                _known_evidence(identifiers, target, reference),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Text reference rule",
                    detail=f"Rule '{rule.rule_id}': references written in the {text_label} are "
                    f"looked up among the {target} values of this document.",
                    data={"rule_id": rule.rule_id},
                ),
                *_unreadable_note(identifiers, target),
            ],
            suggested_action=(
                f"Check whether {code} exists in another document or lot. If it belongs in this "
                f"document, correct the reference in the {text_label} or the {target} of the "
                "referenced row."
            ),
            subject=".".join(reference.segments),
        )


# ---------------------------------------------------------------------------- helpers
def _field_rules(config: ReferenceIntegrityConfig) -> Iterator[tuple[str, str, str]]:
    for rule in config.rules:
        yield rule.rule_id, rule.source_field, rule.target_field


def _text_rules(config: ReferenceIntegrityConfig) -> Iterator[tuple[str, str, str]]:
    for rule in config.text_references:
        yield rule.rule_id, rule.text_field, rule.target_field


def _mapped_anywhere(context: ValidationContext, field_id: str) -> bool:
    return any(context.has_fields(table, field_id) for table in context.tables())


def _tables_mapping(context: ValidationContext, field_id: str) -> list[Table]:
    return [table for table in context.tables() if context.has_fields(table, field_id)]


def _collect_identifiers(context: ValidationContext, target_field: str) -> _Identifiers | None:
    """Code segments of every item and section identifier in all tables (``None`` when no
    table maps the target field)."""
    tables = _tables_mapping(context, target_field)
    if not tables:
        return None
    section_codes = target_field == context.profile.row_classification.section_code_field
    codes: set[tuple[str, ...]] = set()
    unreadable = 0
    for table in tables:
        for row in context.rows(table, _IDENTIFIER_KINDS):
            condition = cell_condition(context.cell(table, row, target_field))
            if condition in _READABLE:
                segments = code_segments(context.text(table, row, target_field))
                if segments is not None:
                    codes.add(segments)
            elif condition is not CellCondition.EMPTY:
                unreadable += 1
            if section_codes and row.kind is RowKind.SECTION and row.classification.code:
                segments = code_segments(row.classification.code)
                if segments is not None:
                    codes.add(segments)
    return _Identifiers(codes=frozenset(codes), tables=len(tables), unreadable=unreadable)


def _own_codes(
    context: ValidationContext, table: Table, row: Row, target_field: str
) -> set[tuple[str, ...]]:
    """Codes of the row a text belongs to: the row itself, or the item a continuation line
    continues."""
    owner = row
    if row.belongs_to_row_id is not None and table.has_row(row.belongs_to_row_id):
        owner = table.row(row.belongs_to_row_id)
    own: set[tuple[str, ...]] = set()
    if context.has_fields(table, target_field):
        segments = code_segments(context.text(table, owner, target_field))
        if segments is not None:
            own.add(segments)
    if owner.kind is RowKind.SECTION and owner.classification.code:
        segments = code_segments(owner.classification.code)
        if segments is not None:
            own.add(segments)
    return own


def _readable_text(
    context: ValidationContext, table: Table, row: Row, field_id: str, result: DetectorResult
) -> str | None:
    """Text of a reference cell, or ``None`` (counted) when it is empty or unusable."""
    condition = cell_condition(context.cell(table, row, field_id))
    if condition is CellCondition.EMPTY:
        return None
    if condition not in _READABLE:
        result.count(skip_key(condition) or Coverage.ROWS_SKIPPED_NOT_APPLICABLE)
        return None
    return context.text(table, row, field_id)


def _split_references(text: str, separator: str | None, result: DetectorResult) -> list[_Reference]:
    """The distinct references of one cell (split by ``separator``), as code segments."""
    parts = [text] if separator is None else text.split(separator)
    references: list[_Reference] = []
    seen: set[tuple[str, ...]] = set()
    for part in parts:
        written = part.strip()
        if not written:
            continue
        if len(references) == MAX_REFERENCES_PER_CELL:
            result.count(REFERENCES_NOT_CHECKED)
            continue
        segments = code_segments(written)
        if segments is None:
            result.count(REFERENCES_UNPARSEABLE)
            continue
        if segments not in seen:
            seen.add(segments)
            references.append(_Reference(written=written, segments=segments, context_text=text))
    return references


def _known_evidence(identifiers: _Identifiers, target: str, reference: _Reference) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.REFERENCE,
        label="Identifiers compared",
        detail=(
            f"{len(identifiers.codes)} distinct {target} values in {identifiers.tables} table(s) "
            f"were compared; none has the code segments {'.'.join(reference.segments)}."
        ),
        data={
            "known_identifiers": len(identifiers.codes),
            "tables": identifiers.tables,
            "code_segments": ".".join(reference.segments),
        },
    )


def _unreadable_note(identifiers: _Identifiers, target: str) -> list[EvidenceItem]:
    if not identifiers.unreadable:
        return []
    return [
        EvidenceItem(
            kind=EvidenceKind.NOTE,
            label="Some identifiers could not be read",
            detail=f"{identifiers.unreadable} {target} cell(s) could not be read (they are "
            "reported by their own checks), so the reference may point at one of them.",
            data={"unreadable_identifiers": identifiers.unreadable},
        )
    ]
