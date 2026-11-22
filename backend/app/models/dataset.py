"""Canonical, format-agnostic dataset model.

Ingestion adapters (XLSX, CSV, later PDF/OCR) never hand raw library objects to detectors.
Normalization converts their output into this model, and every detector reads only this model
through :class:`app.validation.contracts.context.ValidationContext`.

Identity rules:

* ``table_id``, ``column_id`` and ``row_id`` are opaque, assigned once at ingestion and persisted.
* A cell is addressed by ``(table_id, row_id, column_id)`` (:class:`CellRef`), never by a display
  position, so sorting/filtering a view cannot change what an issue points at.
* ``position`` fields record ingestion order only; ``source_*`` fields record original coordinates.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, PrivateAttr, computed_field, field_validator, model_validator

from app.core.errors import NotFoundError
from app.models.base import FrozenModel
from app.models.source import SourceLocation
from app.models.values import CellValue, DataType, ParseStatus, ValueMarker


class RowKind(StrEnum):
    ITEM = "item"  # a data row / line item
    SECTION = "section"  # heading that opens a group of items
    SUBTOTAL = "subtotal"
    GRAND_TOTAL = "grand_total"  # net total of the whole table
    TAX = "tax"  # e.g. a VAT line below the net total
    GROSS_TOTAL = "gross_total"  # total including tax
    ADJUSTMENT = "adjustment"  # signed change of a total: discount, surcharge
    CARRY_FORWARD = "carry_forward"  # page running total ("carried forward", "Übertrag")
    SUMMARY_LINE = "summary_line"  # restates a total defined elsewhere (recap/collection)
    TEXT = "text"  # text-only row: notes, long-text continuation lines
    BLANK = "blank"


# Rows that state a total of other rows. Carry-forward and summary lines restate totals but are
# never reconciled as scope totals, and never summed with items.
TOTAL_ROW_KINDS: frozenset[RowKind] = frozenset(
    {RowKind.SUBTOTAL, RowKind.GRAND_TOTAL, RowKind.TAX, RowKind.GROSS_TOTAL}
)
# Rows that end the scope of a subtotal that has no established section.
SCOPE_BOUNDARY_KINDS: frozenset[RowKind] = frozenset(
    {RowKind.SUBTOTAL, RowKind.GRAND_TOTAL, RowKind.GROSS_TOTAL}
)


class RowClassification(FrozenModel):
    """Why a row was given its kind. ``rule`` names the rule, e.g. ``pattern.subtotal``.

    ``counts_toward_totals`` (ITEM rows): True = added into subtotals and grand totals;
    False = listed but not added (e.g. German Alternativ-/Wahlpositionen, items priced
    "nur EP", English optional items); None = unknown (e.g. a "Bedarfsposition" that does not
    say whether its amount is included): reconciliation detectors then test both readings and
    never report a confirmed violation that depends on the guess. ``totals_rule`` names the
    rule that decided it. When the decision was inherited from a SECTION row (a whole section
    of optional items), ``not_counted_above_section_id`` names that section: the items still
    count toward that section's own subtotal and toward subtotals inside it, but not above it.

    ``code`` is the hierarchical identifier that established the row's place in the section
    hierarchy (a section's code, or the code a subtotal names), when there is one.
    """

    kind: RowKind
    rule: str
    matched_text: str | None = None
    section_level: int | None = Field(default=None, ge=1)  # SECTION rows: 1 = outermost
    code: str | None = None
    counts_toward_totals: bool | None = True
    totals_rule: str | None = None
    not_counted_above_section_id: str | None = None


class FormulaInfo(FrozenModel):
    """A spreadsheet formula, stored as text and never evaluated."""

    expression: str
    cached_result_available: bool


class Cell(FrozenModel):
    """One canonical cell. The original text, the typed interpretation and the normalized value
    are kept side by side; nothing overwrites the original.

    ``extraction_confidence`` is an engine-reported score for OCR/PDF sources only. Verbatim
    digital sources (XLSX, CSV) leave it ``None``: they were not "estimated", and showing an
    invented 1.0 would be a fake confidence number. Reviewer corrections never edit a cell in
    place: they create dataset revision N+1 (ADR 0001). How each kind of source content maps
    to these fields is defined once in :mod:`app.models.cell_rules`.

    ``marker`` is set exactly when ``parse_status`` is ``marker``: a conventional token such
    as "Incl." or "entfällt" in a numeric column, with its generic meaning.
    """

    raw_value: str | None  # original text as extracted; None when the source cell was empty
    parsed_value: CellValue | None = None  # typed interpretation of the source value
    normalized_value: CellValue | None = None  # after normalization (unit aliases, whitespace…)
    data_type: DataType
    parse_status: ParseStatus
    parse_note: str | None = None
    formula: FormulaInfo | None = None
    number_format: str | None = None  # source display format (e.g. Excel '#,##0.00 €')
    source: SourceLocation
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    marker: ValueMarker | None = None

    @model_validator(mode="after")
    def _marker_matches_status(self) -> Cell:
        if (self.marker is not None) != (self.parse_status is ParseStatus.MARKER):
            raise ValueError("Cell.marker must be set exactly when parse_status is 'marker'")
        return self

    @property
    def is_empty(self) -> bool:
        return self.data_type is DataType.EMPTY


class MappingMethod(StrEnum):
    HEADER_EXACT = "header_exact"
    HEADER_CONTAINS = "header_contains"
    HEADER_FUZZY = "header_fuzzy"
    USER = "user"


class ColumnMapping(FrozenModel):
    """Assignment of a column to a semantic field of the domain profile."""

    field_id: str
    method: MappingMethod
    matched_synonym: str | None = None
    # String similarity between header and synonym (difflib ratio). Not a probability.
    similarity: float | None = Field(default=None, ge=0, le=1)


class TypeProfile(FrozenModel):
    """Measured type distribution of a column's non-empty cells. Value markers ("Incl.",
    "Nil") are counted separately in ``marker_count`` and excluded from ``counts``,
    ``non_empty`` and the dominant share, so conventional tokens do not make a numeric column
    look like text."""

    counts: dict[DataType, int]
    non_empty: int = Field(ge=0)
    dominant_type: DataType
    dominant_share: float = Field(ge=0, le=1)  # share of non-empty cells with the dominant type
    marker_count: int = Field(default=0, ge=0)


class Column(FrozenModel):
    column_id: str
    position: int = Field(ge=0)
    source_column_number: int = Field(ge=1)
    original_header: str | None
    normalized_name: str
    inferred_type: DataType
    type_profile: TypeProfile
    mapping: ColumnMapping | None = None
    header_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    decimal_separator: Literal[".", ","] | None = None
    source_hidden: bool = False  # hidden in the source spreadsheet

    @computed_field  # type: ignore[prop-decorator]  # mypy cannot type a decorated property
    @property
    def mapped_semantic_field(self) -> str | None:
        return self.mapping.field_id if self.mapping else None


class HeaderMethod(StrEnum):
    PROFILE_SYNONYMS = "profile_synonyms"  # header row found by matching profile synonyms
    STRUCTURAL = "structural"  # text row followed by typed data rows
    FIRST_ROW = "first_row"  # fallback: first non-empty row
    NONE = "none"  # no header row; columns are named by position
    USER = "user"  # chosen by a reviewer


class HeaderDetection(FrozenModel):
    """Which source rows form the header (top to bottom; two-row headers list both)."""

    header_row_numbers: list[int] = Field(default_factory=list)
    method: HeaderMethod
    matched_fields: list[str] = Field(default_factory=list)
    note: str | None = None

    @field_validator("header_row_numbers")
    @classmethod
    def _sorted_positive(cls, value: list[int]) -> list[int]:
        if any(number < 1 for number in value) or value != sorted(set(value)):
            raise ValueError("header_row_numbers must be ascending, unique and >= 1")
        return value


class Row(FrozenModel):
    """One source row.

    Section hierarchy: ``section_path`` lists the enclosing SECTION rows, outermost first (for
    a SECTION row: its ancestors). ``closes_section_id`` is set on SUBTOTAL rows when
    normalization (or a reviewer) established which section the total sums; ``None`` means the
    scope is unknown and reconciliation detectors must establish or abstain.

    ``excluded`` means a reviewer marked the row as not data (e.g. a mis-detected header or
    footer line): it is skipped by every check and never counted in any sum.

    ``source_hidden`` and ``outline_level`` record the spreadsheet's hidden flag and outline
    (grouping) level. Hidden rows stay in the dataset and are checked; reconciliation treats
    them as an alternative reading (documents may total with SUBTOTAL(109, ...)).

    ``belongs_to_row_id`` links a TEXT continuation row (long text below an item) to the
    item it continues.
    """

    row_id: str
    position: int = Field(ge=0)
    source_row_number: int = Field(ge=1)
    cells: dict[str, Cell]  # keyed by column_id; every column of the table has an entry
    classification: RowClassification
    section_path: list[str] = Field(default_factory=list)
    closes_section_id: str | None = None
    excluded: bool = False
    source_hidden: bool = False
    outline_level: int | None = Field(default=None, ge=0, le=7)
    belongs_to_row_id: str | None = None

    @property
    def kind(self) -> RowKind:
        return self.classification.kind

    @computed_field  # type: ignore[prop-decorator]  # mypy cannot type a decorated property
    @property
    def section_row_id(self) -> str | None:
        """The innermost enclosing SECTION row, if any."""
        return self.section_path[-1] if self.section_path else None

    @property
    def counts_toward_totals(self) -> bool | None:
        return self.classification.counts_toward_totals


class Table(FrozenModel):
    table_id: str
    name: str
    source: SourceLocation  # sheet/page level location of the table
    header: HeaderDetection
    columns: list[Column]
    rows: list[Row]

    # Lookup caches. Excluded from equality (see __eq__) and from serialization.
    _columns_by_id: dict[str, Column] | None = PrivateAttr(default=None)
    _columns_by_field: dict[str, Column] | None = PrivateAttr(default=None)
    _rows_by_id: dict[str, Row] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _consistent(self) -> Table:
        column_ids = [c.column_id for c in self.columns]
        if len(set(column_ids)) != len(column_ids):
            raise ValueError(f"Table {self.table_id!r} has duplicate column ids")
        fields = [c.mapping.field_id for c in self.columns if c.mapping is not None]
        if len(set(fields)) != len(fields):
            duplicates = sorted({f for f in fields if fields.count(f) > 1})
            raise ValueError(
                f"Table {self.table_id!r} maps several columns to the same field: {duplicates}"
            )
        expected = set(column_ids)
        row_ids: set[str] = set()
        for row in self.rows:
            if row.row_id in row_ids:
                raise ValueError(f"Table {self.table_id!r} has duplicate row id {row.row_id!r}")
            row_ids.add(row.row_id)
            if row.cells.keys() != expected:
                raise ValueError(
                    f"Row {row.row_id!r} must have exactly one cell per column of the table"
                )
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Table):
            return NotImplemented
        return self.__dict__ == other.__dict__

    # Holds lists, so never hashable.
    __hash__ = None  # type: ignore[assignment]  # typeshed types __hash__ as a method only

    def column(self, column_id: str) -> Column:
        if self._columns_by_id is None:
            self._columns_by_id = {c.column_id: c for c in self.columns}
        try:
            return self._columns_by_id[column_id]
        except KeyError:
            raise NotFoundError(
                f"Column {column_id!r} not found in table {self.table_id!r}"
            ) from None

    def column_for_field(self, field_id: str) -> Column | None:
        """Column mapped to ``field_id``, or ``None`` when the field is not mapped."""
        if self._columns_by_field is None:
            self._columns_by_field = {
                c.mapping.field_id: c for c in self.columns if c.mapping is not None
            }
        return self._columns_by_field.get(field_id)

    def row(self, row_id: str) -> Row:
        if self._rows_by_id is None:
            self._rows_by_id = {r.row_id: r for r in self.rows}
        try:
            return self._rows_by_id[row_id]
        except KeyError:
            raise NotFoundError(f"Row {row_id!r} not found in table {self.table_id!r}") from None

    def has_row(self, row_id: str) -> bool:
        try:
            self.row(row_id)
        except NotFoundError:
            return False
        return True


class ExtractionQuality(StrEnum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"  # usable, but a reviewer should check the warnings first
    FAILED = "failed"


class ExtractionWarning(FrozenModel):
    """Something the extraction could not do reliably. ``code`` is stable, e.g.
    ``header_uncertain``, ``number_format_ambiguous``, ``formula_without_cached_result``.

    ``needs_review`` is True when the warning can affect values or structure (the dataset's
    quality then becomes ``needs_review``); purely informational notes set it to False.
    """

    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    message: str
    table_id: str | None = None
    source: SourceLocation | None = None
    count: int | None = Field(default=None, ge=0)
    needs_review: bool = True


class ExtractionReport(FrozenModel):
    adapter_id: str
    adapter_version: str
    quality: ExtractionQuality
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class Dataset(FrozenModel):
    """One revision of the canonical tables extracted from a document.

    Revision 1 is the original extraction. Corrections never mutate a revision; they create a
    new one with ``parent_revision`` set, preserving the audit trail.
    """

    dataset_id: str
    document_id: str
    revision: int = Field(default=1, ge=1)
    parent_revision: int | None = Field(default=None, ge=1)
    profile_id: str
    profile_version: str
    created_at: datetime
    tables: list[Table]
    extraction: ExtractionReport

    def table(self, table_id: str) -> Table:
        for table in self.tables:
            if table.table_id == table_id:
                return table
        raise NotFoundError(f"Table {table_id!r} not found in dataset {self.dataset_id!r}")


class CellRef(FrozenModel):
    """Stable reference to one canonical cell, plus a copy of its source location so a finding
    can be traced to the original document without loading the dataset."""

    table_id: str
    row_id: str
    column_id: str
    source: SourceLocation | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.table_id, self.row_id, self.column_id)
