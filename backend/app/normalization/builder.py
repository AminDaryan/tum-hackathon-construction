"""Raw grids -> canonical :class:`~app.models.dataset.Dataset`.

CONTRACT (the rules are also in ``docs/architecture/data-model.md``):

Tables. One table per sheet in Phase 1, in workbook order. Hidden sheets are skipped with the
informational warning ``hidden_sheet_skipped`` (naming the sheet) unless a reviewer decision
includes the sheet (``TableDecisions.include_hidden_sheet``); sheets without non-empty cells
are skipped with ``empty_sheet_skipped``. ``ExtractionError`` when no sheet yields a table.

Identity. Ids come from the injected ``IdFactory``; everything that must survive
re-normalization (issue fingerprints, reviewer decisions) is keyed by source coordinates (sheet
index, source row and column numbers), so re-normalizing after a reviewer decision keeps
fingerprints stable.

Cells. Every cell is built with :mod:`app.models.cell_rules`, which holds the output matrix
(raw content x parse outcome -> data type, parse status, parsed and normalized value, marker):
blank text is EMPTY with the raw text kept, text is NFC + whitespace-collapsed, a unit cell's
normalized value is the canonical unit id, a failed number is TEXT/``failed``, a marker cell is
TEXT/``marker``. ``extraction_confidence`` only from engines that report one.

Headers. Detected within ``options.header_scan_rows`` rows; the method is recorded in
``HeaderDetection`` (``header_row_numbers`` is a list: multi-row headers). Methods other than
profile synonyms add the warning ``header_uncertain``. Matching normalizes headers (NFKC,
casefold, punctuation to spaces, currency markers such as ``[€]`` stripped and remembered as
``header_currency``) and tries exact synonyms and ``exact_header_synonyms`` first, then token
runs (synonyms longer than three characters, not the exact-only ones), then fuzzy matching
(difflib ratio >= ``options.fuzzy_header_threshold``); assignment is one-to-one, greedy by
score; a tie leaves both columns unmapped with ``column_mapping_ambiguous``. Multi-row headers
try the bottom row first, then the composed text ("Preis EP").

Parsing. Per column: decimal separator from column evidence (``inferred``) or ``ambiguous``
when the evidence conflicts; ``locale.parenthesized_numbers``; percentages set ``is_percent``;
values outside ``BoundedDecimal`` are ``failed`` with a note; profile value markers become
``marker`` cells (no number invented); currency only from explicit markers.

Rows. Kinds by the decision table in the ``RowClassificationRules`` docstring
(``app/models/profile.py``), including value presence, summary blocks, carry-forward,
adjustment, tax, gross and grand totals, ``unclassified_amount_row`` (needs review) and
``section_amount_on_heading`` (informational). Section hierarchy: a section whose code is a
strict prefix of the previous open section's code nests (level = parent level + 1), otherwise
the pattern's level, else the code depth, else 1; opening a section closes open sections with a
level >= its own. Subtotal scope: the code (identifier cell or pattern group ``code``) closes
the innermost open section with equal code segments; without a code the innermost open
section; with none open ``closes_section_id=None`` (scope unknown). Grand and gross totals close
all sections. Totals rules decide ``counts_toward_totals`` (True / False / None) and are
inherited from SECTION rows (``not_counted_above_section_id``); a ``rate_only`` marker in the
line total means not counted. Continuation rows get ``belongs_to_row_id``; hidden rows keep
``source_hidden`` and ``outline_level`` (informational ``hidden_rows_present``). Units through
``UnitCatalog.lookup`` and reviewer ``unit_aliases``.

Decisions. Reviewer ``SchemaDecisions`` override detection: header rows, column mapping, row
kinds, counts toward totals, section levels, closing sections, unit aliases, rows that are not
data, hidden sheets to include. A format that states its own structure (GAEB) declares the same
decisions in ``RawSheet.declared``; the reviewer's decisions are laid over them
(``TableDecisions.over``) and each source gets its own note (``structure_declared``,
``decisions_applied``).

Quality. ``ok``, ``needs_review`` (any warning with ``needs_review``) or ``failed``. Never
modify the ``RawWorkbook`` input and never invent values.

Implementation notes. The modules of this package each own one step: :mod:`.headers`
(header rows), :mod:`.mapping` (header -> field), :mod:`.numbers` / :mod:`.dates` /
:mod:`.cells` (cell parsing), :mod:`.types` (column type profiles), :mod:`.rows` (row kinds and
sections) and :mod:`.warnings` (codes and the quality rule); this module only orchestrates.
Decimal separators are decided per column, then from the whole document (every column with
evidence agrees), then from ``locale.decimal_separator``; typed spreadsheet numbers are never
evidence. A column mapped automatically to a number field whose values are less than half
numbers loses its mapping (``mapping_rejected_type_mismatch``) and is read as unmapped.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from app.core.clock import Clock
from app.core.config import NormalizationOptions
from app.core.errors import ExtractionError
from app.core.ids import IdFactory, IdPrefix
from app.ingestion.base import RawCell, RawSheet, RawValueType, RawWorkbook
from app.models.cell_rules import is_blank
from app.models.dataset import (
    Cell,
    Column,
    ColumnMapping,
    Dataset,
    ExtractionReport,
    ExtractionWarning,
    HeaderDetection,
    HeaderMethod,
    MappingMethod,
    Row,
    Table,
)
from app.models.profile import DomainProfile, FieldRole, SemanticField
from app.models.schema import SchemaDecisions, TableDecisions
from app.models.source import SourceLocation
from app.models.values import DataType, ParseStatus
from app.normalization import warnings as codes
from app.normalization.cells import CellParser, Draft, finish, typed_cell
from app.normalization.headers import HeaderResult, SheetView, detect_header
from app.normalization.mapping import HeaderMatcher, assign_fields
from app.normalization.numbers import AmbiguousNumber, DecimalMark, NumberReading, parse_number
from app.normalization.rows import RowClassifier, RowInput, RowWarnings
from app.normalization.text import column_letter, snake_name, unique_names
from app.normalization.types import type_profile
from app.profiles.currency import CurrencyResolver
from app.profiles.units import UnitCatalog, unit_key

__all__ = ["NormalizationOptions", "build_dataset"]

_NUMERIC_DRAFTS = frozenset({"number", "ambiguous", "parenthesized", "out_of_range"})
_UNCERTAIN_HEADER = {
    HeaderMethod.STRUCTURAL: "was found by its layout, not by the profile's column names",
    HeaderMethod.FIRST_ROW: "is the first non-empty row, taken as the header by default",
}


def build_dataset(
    raw: RawWorkbook,
    *,
    profile: DomainProfile,
    document_id: str,
    ids: IdFactory,
    clock: Clock,
    options: NormalizationOptions | None = None,
    decisions: SchemaDecisions | None = None,
) -> Dataset:
    options = options or NormalizationOptions()
    context = _Context(
        profile=profile,
        options=options,
        ids=ids,
        currencies=CurrencyResolver.from_profile(profile),
        units=UnitCatalog.from_profile(profile),
    )
    context.matcher = HeaderMatcher(profile, context.currencies, options.fuzzy_header_threshold)
    dataset_id = ids.new(IdPrefix.DATASET)
    warnings = [codes.reflag(w) for w in raw.warnings]
    prepared: list[_Sheet] = []
    for sheet in raw.sheets:
        reviewer = decisions.for_sheet(sheet.index) if decisions else None
        table_decisions = reviewer.over(sheet.declared) if reviewer else sheet.declared
        where = _sheet_source(sheet)
        if sheet.hidden and not (table_decisions and table_decisions.include_hidden_sheet):
            message = f"Hidden sheet '{sheet.name}' was not checked; a reviewer can include it."
            warnings.append(codes.warning("hidden_sheet_skipped", message, source=where))
            continue
        grid = _Grid.of(sheet)
        if not grid.rows:
            message = f"Sheet '{sheet.name}' has no content."
            warnings.append(codes.warning("empty_sheet_skipped", message, source=where))
            continue
        prepared.append(_prepare(context, sheet, grid, table_decisions, reviewer))
    if not prepared:
        raise ExtractionError("No table could be extracted: every sheet is empty or hidden.")
    document: Counter[DecimalMark] = Counter()
    for sheet_state in prepared:
        for evidence in sheet_state.evidence.values():
            document.update(evidence)
    tables: list[Table] = []
    for sheet_state in prepared:
        table, table_warnings = _finish(context, sheet_state, document)
        tables.append(table)
        warnings.extend(table_warnings)
    return Dataset(
        dataset_id=dataset_id,
        document_id=document_id,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        created_at=clock.now(),
        tables=tables,
        extraction=ExtractionReport(
            adapter_id=raw.adapter_id,
            adapter_version=raw.adapter_version,
            quality=codes.quality(warnings),
            warnings=warnings,
            details=dict(raw.details),
        ),
    )


# ---------------------------------------------------------------------------- state


@dataclass(slots=True)
class _Context:
    profile: DomainProfile
    options: NormalizationOptions
    ids: IdFactory
    currencies: CurrencyResolver
    units: UnitCatalog
    matcher: HeaderMatcher = field(init=False)


@dataclass(slots=True)
class _Grid:
    """The non-empty cells of a sheet, by row."""

    sheet: RawSheet
    by_row: dict[int, list[int]]  # source row -> non-empty source columns, ascending
    rows: list[int]
    columns: list[int]

    @classmethod
    def of(cls, sheet: RawSheet) -> _Grid:
        by_row: dict[int, list[int]] = {}
        for (row, column), cell in sheet.cells.items():
            if _non_empty(cell):
                by_row.setdefault(row, []).append(column)
        for columns in by_row.values():
            columns.sort()
        rows = sorted(by_row)
        columns = sorted({c for cs in by_row.values() for c in cs})
        return cls(sheet, by_row, rows, columns)


@dataclass(slots=True)
class _Sheet:
    """One sheet after header detection, mapping and the first parsing pass."""

    sheet: RawSheet
    decisions: TableDecisions | None
    reviewer: TableDecisions | None  # the reviewer's part of ``decisions``
    table_id: str
    header: HeaderResult
    columns: list[int]  # source columns of the table
    fields: dict[int, SemanticField | None]
    mappings: dict[int, ColumnMapping]
    data_rows: list[int]
    excluded: set[int]
    repeated: set[int]  # header rows repeated inside the data (page headers)
    parser: CellParser
    drafts: dict[tuple[int, int], Draft] = field(default_factory=dict)
    evidence: dict[int, Counter[DecimalMark]] = field(default_factory=dict)
    warnings: list[ExtractionWarning] = field(default_factory=list)


# ---------------------------------------------------------------------------- pass 1


def _prepare(
    context: _Context,
    sheet: RawSheet,
    grid: _Grid,
    decisions: TableDecisions | None,
    reviewer: TableDecisions | None,
) -> _Sheet:
    """``decisions``: the reviewer's decisions (``reviewer``) over the structure the file
    declares (``sheet.declared``); each source is counted in its own note."""
    profile, matcher = context.profile, context.matcher
    table_id = context.ids.new(IdPrefix.TABLE)
    where = _sheet_source(sheet)
    view = _view(grid, context.currencies)
    user_rows = decisions.header_row_numbers if decisions else None
    header = detect_header(view, matcher, context.options.header_scan_rows, user_rows)
    start = header.data_start if header.rows else grid.rows[0]
    data_rows = list(range(start, grid.rows[-1] + 1)) if start is not None else []
    data_columns = {c for r in data_rows for c in grid.by_row.get(r, ())}
    columns = sorted(data_columns | set(header.texts))
    user_fields = {
        c: f
        for c, f in (decisions.column_fields.items() if decisions else ())
        if c in columns and (f is None or profile.field(f) is not None)
    }
    candidates = {c: header.candidates.get(c, ()) for c in columns}
    assignment = assign_fields(candidates, user=user_fields)
    mappings = dict(assignment.mappings)
    aliases = {
        unit_key(text): unit_id
        for text, unit_id in (decisions.unit_aliases.items() if decisions else ())
        if context.units.get(unit_id) is not None
    }
    state = _Sheet(
        sheet=sheet,
        decisions=decisions,
        reviewer=reviewer,
        table_id=table_id,
        header=header,
        columns=columns,
        fields={c: profile.field(mappings[c].field_id) if c in mappings else None for c in columns},
        mappings=mappings,
        data_rows=data_rows,
        excluded=set(decisions.not_data_rows) & set(data_rows) if decisions else set(),
        repeated=_repeated_headers(view, matcher, grid, header, data_rows),
        parser=CellParser(profile, context.units, context.currencies, aliases),
    )
    for r in data_rows:
        if r in state.repeated:
            continue
        for c in grid.by_row.get(r, ()):
            cell = sheet.get(r, c)
            if cell is not None and cell.value_type is RawValueType.STRING:
                state.drafts[(r, c)] = state.parser.draft(cell, state.fields[c])
    add = state.warnings.append
    for field_id, tied in assignment.ambiguous:
        label = _field_label(profile, field_id)
        names = " and ".join(_column_name(header, c) for c in tied)
        message = f"Columns {names} match '{label}' equally well; neither was mapped to it."
        add(codes.warning("column_mapping_ambiguous", message, table_id=table_id, source=where))
    _reject_type_mismatches(context, state)
    for code, prefix, source in (
        ("structure_declared", "Structure declared by the file applied", sheet.declared),
        ("decisions_applied", "Reviewer decisions applied", reviewer),
    ):
        if source is None:
            continue
        applied, ignored = _decision_counts(context, source, set(data_rows), set(columns))
        message = f"{prefix}: {applied}."
        if ignored:
            message += (
                f" Ignored {ignored}: they refer to rows, columns, fields or units that do not"
                " exist."
            )
        add(codes.warning(code, message, table_id=table_id, source=where))
    missing = [
        f.label
        for f in profile.required_fields()
        if f.field_id not in {m.field_id for m in state.mappings.values()}
    ]
    if missing and data_rows:
        message = f"Required field(s) not found in the columns: {', '.join(missing)}."
        add(codes.warning("required_field_unmapped", message, table_id=table_id, source=where))
    for c in columns:
        counter: Counter[DecimalMark] = Counter()
        for r in data_rows:
            draft = state.drafts.get((r, c))
            if draft is not None and draft.kind == "number":
                evidence = draft.reading_as(NumberReading).decimal_evidence
                if evidence is not None:
                    counter[evidence] += 1
        if counter:
            state.evidence[c] = counter
    return state


def _reject_type_mismatches(context: _Context, state: _Sheet) -> None:
    for c, mapping in list(state.mappings.items()):
        field_def = state.fields[c]
        if (
            mapping.method is MappingMethod.USER
            or field_def is None
            or field_def.data_type is not DataType.NUMBER
        ):
            continue
        numeric = values = 0
        for r in state.data_rows:
            if r in state.repeated or r in state.excluded:
                continue
            cell = state.sheet.get(r, c)
            if cell is None or not _non_empty(cell):
                continue
            if cell.value_type in (RawValueType.ERROR, RawValueType.UNAVAILABLE):
                continue
            draft = state.drafts.get((r, c))
            if draft is not None and draft.kind == "marker":
                continue
            values += 1
            if cell.value_type is RawValueType.NUMBER or (
                draft is not None and draft.kind in _NUMERIC_DRAFTS
            ):
                numeric += 1
        thresholds = context.profile.normalization
        if (
            values < thresholds.type_mismatch_min_values
            or numeric >= values * thresholds.type_mismatch_share
        ):
            continue
        del state.mappings[c]
        state.fields[c] = None
        for r in state.data_rows:
            raw = state.sheet.get(r, c)
            if raw is not None and (r, c) in state.drafts:  # drafts exist for STRING cells only
                state.drafts[(r, c)] = state.parser.draft(raw, None)
        message = (
            f"Column {_column_name(state.header, c)} looked like "
            f"'{field_def.label}' by its header, but only {numeric} of its {values} values "
            "are numbers, so it was not mapped to that field."
        )
        state.warnings.append(
            codes.warning(
                "mapping_rejected_type_mismatch",
                message,
                table_id=state.table_id,
                source=_sheet_source(state.sheet),
            )
        )


def _repeated_headers(
    view: SheetView,
    matcher: HeaderMatcher,
    grid: _Grid,
    header: HeaderResult,
    data_rows: list[int],
) -> set[int]:
    """Data rows that repeat a header row (page headers of a long printout)."""
    keyed = []
    for row in header.rows:
        texts = {c: matcher.key(t) for c in grid.by_row.get(row, ()) if (t := view.text_of(row, c))}
        if len(texts) >= 2 and len(texts) == len(grid.by_row.get(row, ())):
            keyed.append(texts)
    repeated: set[int] = set()
    for row in data_rows:
        columns = grid.by_row.get(row)
        if not columns:
            continue
        for texts in keyed:
            if len(columns) == len(texts) and all(
                c in texts and matcher.key(view.text_of(row, c)) == texts[c] for c in columns
            ):
                repeated.add(row)
                break
    return repeated


def _decision_counts(
    context: _Context, decisions: TableDecisions | None, rows: set[int], columns: set[int]
) -> tuple[int, int]:
    """(applied, ignored) decisions of one table, reviewer's or declared by the file."""
    if decisions is None:
        return 0, 0
    applied = ignored = 0
    for keyed in (
        decisions.row_kinds,
        decisions.counts_toward_totals,
        decisions.section_levels,
        decisions.closes_section,
    ):
        for row in keyed:
            applied, ignored = (applied + 1, ignored) if row in rows else (applied, ignored + 1)
    for row in decisions.not_data_rows:
        applied, ignored = (applied + 1, ignored) if row in rows else (applied, ignored + 1)
    for column, field_id in decisions.column_fields.items():
        known = field_id is None or context.profile.field(field_id) is not None
        ok = column in columns and known
        applied, ignored = (applied + 1, ignored) if ok else (applied, ignored + 1)
    for unit_id in decisions.unit_aliases.values():
        ok = context.units.get(unit_id) is not None
        applied, ignored = (applied + 1, ignored) if ok else (applied, ignored + 1)
    if decisions.header_row_numbers is not None:
        applied += 1
    if decisions.include_hidden_sheet:
        applied += 1
    return applied, ignored


# ---------------------------------------------------------------------------- pass 2


def _finish(
    context: _Context, state: _Sheet, document: Counter[DecimalMark]
) -> tuple[Table, list[ExtractionWarning]]:
    profile, ids, sheet = context.profile, context.ids, state.sheet
    where = _sheet_source(sheet)
    table_warnings = [codes.reflag(w, state.table_id) for w in sheet.warnings]
    table_warnings.extend(state.warnings)
    column_ids = {c: ids.new(IdPrefix.COLUMN) for c in state.columns}
    separators: dict[int, tuple[DecimalMark | None, str | None]] = {}
    for c in state.columns:
        evidence = state.evidence.get(c, Counter())
        if len(evidence) > 1:
            separators[c] = (None, None)
            dots, commas = evidence["."], evidence[","]
            message = (
                f"Column {_column_name(state.header, c)} uses both '.' ({dots} values) and ','"
                f" ({commas} values) as the decimal separator; values that could be read either"
                " way were left unparsed."
            )
            table_warnings.append(
                codes.warning(
                    "decimal_separator_conflict", message, table_id=state.table_id, source=where
                )
            )
        else:
            separators[c] = _separator(evidence, document, profile.locale.decimal_separator)
    used_separator: dict[int, DecimalMark] = {
        c: next(iter(e)) for c, e in state.evidence.items() if len(e) == 1
    }
    inputs: list[RowInput] = []
    ambiguous = unavailable = 0
    for position, r in enumerate(state.data_rows):
        cells: dict[str, Cell] = {}
        for c in state.columns:
            raw = sheet.get(r, c)
            source = _cell_source(sheet, r, c, raw)
            draft = state.drafts.get((r, c))
            if draft is not None and raw is not None:
                resolved = None
                if draft.kind == "ambiguous":
                    separator, note = separators[c]
                    if separator is not None and note is not None:
                        resolved = (separator, note)
                        used_separator.setdefault(c, separator)
                cell = finish(raw, draft, source, resolved)
            elif r in state.repeated and raw is not None and raw.value_type is RawValueType.STRING:
                cell = finish(raw, Draft("text"), source)
            else:
                cell = typed_cell(raw, source, context.currencies)
            if cell.parse_status is ParseStatus.AMBIGUOUS:
                ambiguous += 1
            elif cell.parse_status is ParseStatus.UNAVAILABLE:
                unavailable += 1
            cells[column_ids[c]] = cell
        inputs.append(
            RowInput(
                row_id=ids.new(IdPrefix.ROW),
                position=position,
                source_row=r,
                cells=cells,
                hidden=r in sheet.hidden_rows,
                outline_level=sheet.row_outline_levels.get(r),
                excluded=r in state.excluded,
                repeated_header=r in state.repeated,
            )
        )
    field_columns = {m.field_id: column_ids[c] for c, m in state.mappings.items()}
    order = [column_ids[c] for c in state.columns]
    classifier = RowClassifier(profile, field_columns, order, state.decisions, state.reviewer)
    rows, row_warnings = classifier.classify(inputs)
    columns = _columns(context, state, column_ids, rows, used_separator)
    table = Table(
        table_id=state.table_id,
        name=sheet.name,
        source=where,
        header=HeaderDetection(
            header_row_numbers=state.header.rows,
            method=state.header.method,
            matched_fields=[
                state.mappings[c].field_id for c in state.columns if c in state.mappings
            ],
            note=state.header.note,
        ),
        columns=columns,
        rows=rows,
    )
    table_warnings.extend(_header_warnings(context, state, where))
    table_warnings.extend(_count_warnings(state.table_id, where, ambiguous, unavailable))
    table_warnings.extend(_row_warnings(state.table_id, where, row_warnings))
    return table, table_warnings


def _columns(
    context: _Context,
    state: _Sheet,
    column_ids: dict[int, str],
    rows: list[Row],
    separators: dict[int, DecimalMark],
) -> list[Column]:
    threshold = context.options.type_dominance_threshold
    counted = [r for r in rows if not r.excluded and r.classification.rule != "repeated_header"]
    names = unique_names(
        [
            snake_name(state.header.texts.get(c)) or f"column_{column_letter(c).lower()}"
            for c in state.columns
        ]
    )
    columns: list[Column] = []
    for position, (c, name) in enumerate(zip(state.columns, names, strict=True)):
        column_id = column_ids[c]
        profile_of = type_profile((r.cells[column_id] for r in counted), threshold)
        field_def = state.fields[c]
        header_text = state.header.texts.get(c)
        columns.append(
            Column(
                column_id=column_id,
                position=position,
                source_column_number=c,
                original_header=header_text,
                normalized_name=name,
                inferred_type=profile_of.dominant_type,
                type_profile=profile_of,
                mapping=state.mappings.get(c),
                header_currency=_header_currency(
                    context, header_text, field_def, profile_of.dominant_type
                ),
                decimal_separator=separators.get(c),
                source_hidden=c in state.sheet.hidden_columns,
            )
        )
    return columns


def _separator(
    column: Counter[DecimalMark], document: Counter[DecimalMark], locale: Literal["auto", ".", ","]
) -> tuple[DecimalMark | None, str | None]:
    """The decimal separator for a column's ambiguous values, with the note citing why."""
    if len(column) == 1:
        separator, count = next(iter(column.items()))
        return separator, (
            f"Decimal separator '{separator}' inferred from {_values(count)} in this column."
        )
    if len(document) == 1:
        separator, count = next(iter(document.items()))
        return separator, (
            f"Decimal separator '{separator}' inferred from {_values(count)} elsewhere in the"
            " document."
        )
    if locale in (".", ","):
        return locale, f"Decimal separator '{locale}' taken from the profile's locale setting."
    return None, None


def _header_currency(
    context: _Context, text: str | None, field_def: SemanticField | None, inferred: DataType
) -> str | None:
    if not text:
        return None
    if field_def is not None and field_def.role is not FieldRole.MONETARY:
        return None
    if field_def is None and inferred is not DataType.NUMBER:
        return None
    found = context.currencies.find_in_text(text)
    return next(iter(found)) if len(found) == 1 else None


# ---------------------------------------------------------------------------- warnings


def _header_warnings(
    context: _Context, state: _Sheet, where: SourceLocation
) -> list[ExtractionWarning]:
    header, table_id = state.header, state.table_id
    found: list[ExtractionWarning] = []
    if header.method in _UNCERTAIN_HEADER:
        message = (
            f"The header (row {header.rows[0]}) {_UNCERTAIN_HEADER[header.method]}; check the"
            " column mapping."
        )
    elif header.method is HeaderMethod.NONE:
        message = "No header row was recognized; columns are named by letter and every row is data."
    else:
        message = None
    if message is not None:
        found.append(
            codes.warning(
                "header_uncertain",
                message,
                table_id=table_id,
                source=where,
                needs_review=context.matcher.has_fields,
            )
        )
    if "header_ambiguous" in header.warnings:
        message = (
            f"Several rows look like the header; row {header.rows[0]}, the first of them, was used."
        )
        found.append(codes.warning("header_ambiguous", message, table_id=table_id, source=where))
    return found


def _count_warnings(
    table_id: str, where: SourceLocation, ambiguous: int, unavailable: int
) -> list[ExtractionWarning]:
    found = []
    if ambiguous:
        message = (
            f"{_values(ambiguous).capitalize()} could be read in more than one way (decimal "
            "separator, parentheses or day/month order) and were left unparsed."
        )
        found.append(
            codes.warning(
                "number_format_ambiguous", message, table_id=table_id, source=where, count=ambiguous
            )
        )
    if unavailable:
        message = (
            f"{_values(unavailable, 'formula').capitalize()} have no stored result in the file;"
            " formulas are never evaluated, so these cells have no value."
        )
        found.append(
            codes.warning(
                "formula_without_cached_result",
                message,
                table_id=table_id,
                source=where,
                count=unavailable,
            )
        )
    return found


def _row_warnings(
    table_id: str, where: SourceLocation, rows: RowWarnings
) -> list[ExtractionWarning]:
    found = []
    specs = (
        (
            "unclassified_amount_row",
            rows.unclassified_amount_rows,
            "hold numbers but are neither items, sections nor totals; check how they count",
        ),
        (
            "section_amount_on_heading",
            rows.section_amount_rows,
            "are section headings that also state an amount",
        ),
        (
            "hidden_rows_present",
            rows.hidden_rows,
            "are hidden in the source; they were kept and checked",
        ),
    )
    for code, numbers, text in specs:
        if numbers:
            message = f"Source {codes.list_rows(numbers)} {text}."
            found.append(
                codes.warning(code, message, table_id=table_id, source=where, count=len(numbers))
            )
    return found


# ---------------------------------------------------------------------------- helpers


def _non_empty(cell: RawCell) -> bool:
    if cell.value_type is RawValueType.EMPTY:
        return False
    if cell.value_type is RawValueType.STRING:
        return not is_blank(cell.text or "")
    return True


def _view(grid: _Grid, currencies: CurrencyResolver) -> SheetView:
    sheet = grid.sheet
    texts: dict[tuple[int, int], str | None] = {}

    def text_of(row: int, column: int) -> str | None:
        key = (row, column)
        if key not in texts:
            cell = sheet.get(row, column)
            text = None
            if (
                cell is not None
                and cell.value_type is RawValueType.STRING
                and cell.text
                and not is_blank(cell.text)
                and parse_number(cell.text, currencies=currencies) is None
            ):
                text = " ".join(cell.text.split())
            texts[key] = text
        return texts[key]

    def non_empty(row: int, column: int) -> bool:
        cell = sheet.get(row, column)
        return cell is not None and _non_empty(cell)

    def numeric(row: int, column: int) -> bool:
        cell = sheet.get(row, column)
        if cell is None:
            return False
        if cell.value_type is RawValueType.NUMBER:
            return True
        if cell.value_type is RawValueType.STRING and cell.text:
            parsed = parse_number(cell.text, currencies=currencies)
            return isinstance(parsed, (NumberReading, AmbiguousNumber))
        return False

    return SheetView(sheet, text_of, non_empty, numeric, grid.rows, grid.columns)


def _sheet_source(sheet: RawSheet) -> SourceLocation:
    return SourceLocation(kind=sheet.source_kind, sheet_name=sheet.name, sheet_index=sheet.index)


def _cell_source(sheet: RawSheet, row: int, column: int, cell: RawCell | None) -> SourceLocation:
    """Per-cell location. Built without re-validation: every value comes from the validated
    sheet-level location (``_sheet_source``) or is a 1-based coordinate / engine field of the
    raw cell, and one validation per cell would dominate normalization time."""
    return SourceLocation.model_construct(
        kind=sheet.source_kind,
        sheet_name=sheet.name,
        sheet_index=sheet.index,
        page_number=cell.page_number if cell is not None else None,
        table_index=None,
        row_number=row,
        column_number=column,
        line_number=cell.line_number if cell is not None else None,
        bbox=cell.bbox if cell is not None else None,
    )


def _column_name(header: HeaderResult, column: int) -> str:
    text = header.texts.get(column)
    letter = column_letter(column)
    return f"{letter} ('{text[:40]}')" if text else letter


def _field_label(profile: DomainProfile, field_id: str) -> str:
    definition = profile.field(field_id)
    return definition.label if definition else field_id


def _values(count: int, noun: str = "value") -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
