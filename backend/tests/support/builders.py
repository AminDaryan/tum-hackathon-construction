"""Test helpers that build canonical datasets directly (no files, no parsing).

Detector tests use these builders so they exercise detector logic in isolation from ingestion
and normalization. Values given as ``Decimal`` / ``int`` / numeric ``str`` in columns whose
profile field is numeric become exact ``NumberValue`` cells; ``None`` or ``""`` become empty cells;
anything else becomes text. Pass a prebuilt :class:`Cell` (see the ``*_cell`` helpers) for
special cases such as ambiguous parses, formula errors or low OCR confidence.

Example::

    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", [("Item", "item_code"), ("Description", "description"),
                                  ("Qty", "quantity"), ("Unit", "unit"),
                                  ("Rate", "unit_price"), ("Amount", "line_total")])
    table.row(["01.001", "Excavation", "10", "m3", "12.50", "125.00"])
    table.row([None, "Subtotal section 1", None, None, None, "125.00"], kind=RowKind.SUBTOTAL)
    dataset = builder.build()
    context = make_context(dataset, boq_profile)

Sections: ``row(..., kind=RowKind.SECTION, level=2)`` opens a section (level 1 = outermost); a
SUBTOTAL row with ``closes_section=True`` records the innermost open section as its scope and
closes it. ``in_totals=False`` marks an item as listed but not counted in totals, and
``in_totals=None`` as undecided (an item that may or may not count). ``hidden=True`` marks a row
hidden in the source; ``belongs_to=<row index>`` attaches a continuation row to an item.

Value markers: a profile marker token ("Incl.", "entfällt", "psch") in a numeric column becomes
a ``marker`` cell automatically, just as normalization does; see :func:`marker_cell`.

Cells default to ``extraction_confidence=None`` (verbatim digital source); pass a confidence to
simulate OCR.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.clock import FixedClock
from app.core.config import ValidationLimits
from app.core.ids import SequentialIdFactory
from app.models import cell_rules as rules
from app.models.dataset import (
    Cell,
    Column,
    ColumnMapping,
    Dataset,
    ExtractionQuality,
    ExtractionReport,
    ExtractionWarning,
    FormulaInfo,
    HeaderDetection,
    HeaderMethod,
    MappingMethod,
    Row,
    RowClassification,
    RowKind,
    Table,
    TypeProfile,
)
from app.models.profile import DomainProfile
from app.models.source import SourceKind, SourceLocation
from app.models.values import (
    CellValue,
    DataType,
    NumberValue,
    ParseStatus,
    TextValue,
    ValueMarker,
    is_bounded_decimal,
)
from app.profiles.units import UnitCatalog
from app.validation.contracts.context import ValidationContext, build_validation_context

FIXED_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _source(sheet: str, row: int, column: int) -> SourceLocation:
    return SourceLocation(
        kind=SourceKind.SPREADSHEET,
        sheet_name=sheet,
        sheet_index=0,
        row_number=row,
        column_number=column,
    )


def _placeholder() -> SourceLocation:
    # Replaced by the real coordinates when the builder places the cell in a table.
    return _source("Sheet1", 1, 1)


def number_cell(
    value: Decimal | str | int,
    *,
    raw: str | None = None,
    currency: str | None = None,
    status: ParseStatus = ParseStatus.EXACT,
    confidence: float | None = None,
    formula: str | None = None,
    note: str | None = None,
    percent: bool = False,
    number_format: str | None = None,
) -> Cell:
    number = NumberValue(value=Decimal(str(value)), currency=currency, is_percent=percent)
    return rules.number_cell(
        number,
        _placeholder(),
        raw=raw if raw is not None else str(value),
        status=status,
        note=note,
        formula=FormulaInfo(expression=formula, cached_result_available=True) if formula else None,
        number_format=number_format,
        confidence=confidence,
    )


def text_cell(text: str, *, normalized: str | None = None, confidence: float | None = None) -> Cell:
    cell = rules.text_cell(text, _placeholder(), confidence=confidence)
    if normalized is not None and not cell.is_empty:
        cell = cell.evolve(normalized_value=TextValue(value=normalized))
    return cell


def unit_cell(text: str, unit_id: str | None) -> Cell:
    return rules.unit_cell(text, _placeholder(), unit_id)


def empty_cell(raw: str | None = None) -> Cell:
    return rules.empty_cell(_placeholder(), raw=raw)


def error_cell(code: str = "#REF!", *, formula: str | None = "=A1/0") -> Cell:
    return rules.error_cell(
        code,
        _placeholder(),
        formula=FormulaInfo(expression=formula, cached_result_available=True) if formula else None,
    )


def ambiguous_cell(raw: str, note: str = "Decimal separator is ambiguous.") -> Cell:
    return rules.ambiguous_cell(raw, _placeholder(), note)


def failed_number_cell(raw: str, note: str = "Not a number.") -> Cell:
    """Text in a numeric field that could not be parsed as a number."""
    return rules.failed_cell(raw, _placeholder(), note)


def marker_cell(raw: str, marker: ValueMarker) -> Cell:
    """A conventional token in a numeric column ("Incl.", "Nil", "entfällt"): kept as text,
    with its meaning in ``Cell.marker``; no number is invented."""
    return rules.marker_cell(raw, _placeholder(), marker)


def unavailable_formula_cell(formula: str = "=B2*C2") -> Cell:
    return rules.unavailable_cell(
        _placeholder(), FormulaInfo(expression=formula, cached_result_available=False)
    )


@dataclass
class _ColumnSpec:
    header: str | None
    field_id: str | None


@dataclass
class _RowSpec:
    values: list[Any]
    kind: RowKind
    excluded: bool
    level: int | None
    closes_section: bool
    in_totals: bool | None
    hidden: bool = False
    belongs_to: int | None = None
    code: str | None = None


@dataclass
class TableBuilder:
    builder: DatasetBuilder
    name: str
    columns: list[_ColumnSpec]
    rows: list[_RowSpec] = field(default_factory=list)

    def row(
        self,
        values: Sequence[Any],
        *,
        kind: RowKind = RowKind.ITEM,
        excluded: bool = False,
        level: int | None = None,
        closes_section: bool | None = None,
        in_totals: bool | None = True,
        hidden: bool = False,
        belongs_to: int | None = None,
        code: str | None = None,
    ) -> TableBuilder:
        """Append a row. ``belongs_to`` is the 0-based index of an earlier row of this table
        (a continuation line of that item); ``code`` is the classification code (an item or
        section code as normalization would record it). ``closes_section`` defaults to what
        normalization does: a SUBTOTAL closes the innermost open section (pass ``False`` for
        a subtotal whose scope normalization could not establish)."""
        if closes_section is None:
            closes_section = kind is RowKind.SUBTOTAL
        if len(values) != len(self.columns):
            raise ValueError(f"Expected {len(self.columns)} values, got {len(values)}")
        if belongs_to is not None and not 0 <= belongs_to < len(self.rows):
            raise ValueError("belongs_to must name an earlier row of this table")
        if kind is RowKind.SECTION and level is None:
            level = 1
        self.rows.append(
            _RowSpec(
                list(values),
                kind,
                excluded,
                level,
                closes_section,
                in_totals,
                hidden=hidden,
                belongs_to=belongs_to,
                code=code,
            )
        )
        return self


class DatasetBuilder:
    """Builds a :class:`Dataset` with deterministic ids (``tbl_000001``, ``row_000001``…)."""

    def __init__(
        self,
        profile: DomainProfile,
        *,
        quality: ExtractionQuality | None = None,
        warnings: Sequence[ExtractionWarning] = (),
        document_id: str = "doc_000001",
        dataset_id: str = "ds_000001",
    ) -> None:
        """``quality`` defaults to the rule normalization applies: ``needs_review`` when any
        warning needs review, else ``ok``. Pass ``quality=FAILED`` to simulate a failed
        extraction."""
        self.profile = profile
        self.warnings = list(warnings)
        if quality is None:
            quality = (
                ExtractionQuality.NEEDS_REVIEW
                if any(w.needs_review for w in self.warnings)
                else ExtractionQuality.OK
            )
        self.quality = quality
        self.document_id = document_id
        self.dataset_id = dataset_id
        self.ids = SequentialIdFactory()
        self._tables: list[TableBuilder] = []
        self._units = UnitCatalog.from_profile(profile)

    def table(self, name: str, columns: Sequence[tuple[str | None, str | None]]) -> TableBuilder:
        builder = TableBuilder(self, name, [_ColumnSpec(h, f) for h, f in columns])
        self._tables.append(builder)
        return builder

    def build(self) -> Dataset:
        tables = [self._build_table(index, tb) for index, tb in enumerate(self._tables)]
        return Dataset(
            dataset_id=self.dataset_id,
            document_id=self.document_id,
            profile_id=self.profile.profile_id,
            profile_version=self.profile.version,
            created_at=FIXED_TIME,
            tables=tables,
            extraction=ExtractionReport(
                adapter_id="test.builder",
                adapter_version="1",
                quality=self.quality,
                warnings=self.warnings,
            ),
        )

    # ------------------------------------------------------------------ internals
    def _build_table(self, index: int, tb: TableBuilder) -> Table:
        table_id = self.ids.new("tbl")
        column_ids = [self.ids.new("col") for _ in tb.columns]
        header_row = 1
        rows: list[Row] = []
        row_ids: list[str] = []
        open_sections: list[tuple[str, int]] = []  # (row_id, level), outermost first
        for position, spec_row in enumerate(tb.rows):
            row_id = self.ids.new("row")
            row_ids.append(row_id)
            source_row = header_row + 1 + position
            cells = {}
            for col_index, (column_id, spec, value) in enumerate(
                zip(column_ids, tb.columns, spec_row.values, strict=True)
            ):
                cell = self._cell(spec, value)
                cells[column_id] = cell.evolve(
                    source=_source(tb.name, source_row, col_index + 1).evolve(sheet_index=index)
                )
            closes: str | None = None
            if spec_row.kind is RowKind.SECTION:
                level = spec_row.level or 1
                while open_sections and open_sections[-1][1] >= level:
                    open_sections.pop()
                path = [section_id for section_id, _ in open_sections]
                open_sections.append((row_id, level))
            else:
                path = [section_id for section_id, _ in open_sections]
                if spec_row.kind is RowKind.SUBTOTAL and spec_row.closes_section and open_sections:
                    closes = open_sections.pop()[0]
            rows.append(
                Row(
                    row_id=row_id,
                    position=position,
                    source_row_number=source_row,
                    cells=cells,
                    classification=RowClassification(
                        kind=spec_row.kind,
                        rule="test.builder",
                        code=spec_row.code,
                        section_level=spec_row.level if spec_row.kind is RowKind.SECTION else None,
                        counts_toward_totals=spec_row.in_totals,
                        totals_rule=None if spec_row.in_totals is True else "test.builder",
                    ),
                    section_path=path,
                    closes_section_id=closes,
                    excluded=spec_row.excluded,
                    source_hidden=spec_row.hidden,
                    belongs_to_row_id=(
                        row_ids[spec_row.belongs_to] if spec_row.belongs_to is not None else None
                    ),
                )
            )
        columns = [
            self._column(column_id, position, spec, [r.cells[column_id] for r in rows])
            for position, (column_id, spec) in enumerate(zip(column_ids, tb.columns, strict=True))
        ]
        return Table(
            table_id=table_id,
            name=tb.name,
            source=SourceLocation(
                kind=SourceKind.SPREADSHEET, sheet_name=tb.name, sheet_index=index
            ),
            header=HeaderDetection(
                header_row_numbers=[header_row], method=HeaderMethod.PROFILE_SYNONYMS
            ),
            columns=columns,
            rows=rows,
        )

    def _column(
        self, column_id: str, position: int, spec: _ColumnSpec, cells: list[Cell]
    ) -> Column:
        counts: dict[DataType, int] = {}
        markers = 0
        for cell in cells:
            if cell.parse_status is ParseStatus.MARKER:
                markers += 1  # markers are counted apart, as normalization does
            elif not cell.is_empty:
                counts[cell.data_type] = counts.get(cell.data_type, 0) + 1
        non_empty = sum(counts.values())
        dominant = max(counts, key=counts.__getitem__) if counts else DataType.EMPTY
        share = (counts.get(dominant, 0) / non_empty) if non_empty else 0.0
        return Column(
            column_id=column_id,
            position=position,
            source_column_number=position + 1,
            original_header=spec.header,
            normalized_name=(spec.header or f"column_{position + 1}").lower().replace(" ", "_"),
            inferred_type=dominant,
            type_profile=TypeProfile(
                counts=counts,
                non_empty=non_empty,
                dominant_type=dominant,
                dominant_share=share,
                marker_count=markers,
            ),
            mapping=(
                ColumnMapping(
                    field_id=spec.field_id, method=MappingMethod.HEADER_EXACT, similarity=1.0
                )
                if spec.field_id
                else None
            ),
        )

    def _cell(self, spec: _ColumnSpec, value: Any) -> Cell:
        if isinstance(value, Cell):
            return value
        if value is None:
            return empty_cell()
        if isinstance(value, str) and rules.is_blank(value):
            return empty_cell(value or None)
        field_def = self.profile.field(spec.field_id) if spec.field_id else None
        numeric_field = field_def is not None and field_def.data_type is DataType.NUMBER
        if isinstance(value, Decimal | int) and not isinstance(value, bool):
            return number_cell(value)
        if isinstance(value, str) and (numeric_field or field_def is None):
            try:
                number: Decimal | None = Decimal(value)
            except InvalidOperation:
                number = None
            # Out-of-range and non-finite text is a failed number, as in normalization.
            if number is not None and number.is_finite() and is_bounded_decimal(number):
                return number_cell(value)
            if numeric_field:
                marker = self.profile.match_marker(value, field_def.role)
                if marker is not None:
                    return marker_cell(value, marker)
                return failed_number_cell(value)
        text = str(value)
        if field_def is not None and field_def.role.value == "unit":
            lookup = self._units.lookup(text)
            return unit_cell(text, lookup.unit.unit_id if lookup else None)
        return text_cell(text)


# Small limits for unit tests, so caps and deadlines are exercised the way the pipeline
# applies them (a detector that swallows DetectorStopped fails its tests).
TEST_LIMITS = ValidationLimits(
    max_issues_per_detector=2_000,
    max_issues_per_run=5_000,
    max_detector_seconds=30.0,
    max_run_seconds=120.0,
)


def make_context(
    dataset: Dataset,
    profile: DomainProfile,
    *,
    run_id: str = "run_000001",
    low_confidence_threshold: float = 0.9,
    limits: ValidationLimits | None = None,
) -> ValidationContext:
    """A :class:`ValidationContext` wired exactly like the pipeline's (same factory, review
    caveats, caps and a per-detector deadline), with deterministic ids and a fixed clock."""
    base = limits or TEST_LIMITS
    return build_validation_context(
        dataset=dataset,
        profile=profile,
        run_id=run_id,
        limits=base.model_copy(update={"low_confidence_threshold": low_confidence_threshold}),
        ids=SequentialIdFactory(),
        clock=FixedClock(FIXED_TIME),
    )


def default_limits() -> ValidationLimits:
    return ValidationLimits()


def cell_value(
    dataset: Dataset, table_index: int, row_index: int, column_index: int
) -> CellValue | None:
    table = dataset.tables[table_index]
    column = table.columns[column_index]
    return table.rows[row_index].cells[column.column_id].normalized_value
