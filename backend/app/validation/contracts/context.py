"""Read-only view of one dataset revision, handed to every detector.

Detectors never see files, workbooks or OCR output, only the canonical model. Accessors return
``None`` instead of guessing whenever a value is missing, ambiguous or not numeric, so detectors
abstain by default. Every accessor exists in two forms with identical rules: by semantic field
id (``number(table, row, "quantity")``) and by column id (``number_at(table, row, column_id)``)
for column-oriented detectors that also inspect unmapped columns. Detectors read values
through these accessors rather than ``cell.normalized_value``, so the usability rules (which
parse statuses count as a number, what a marker means, how a unit or a currency is
established) live in one place. ``value*`` returns the typed value of any type, for checks
that compare cells as written (duplicates) or report what a cell holds (an error literal);
checks that compute use ``number*`` and ``text*``. Reviewer corrections never change a
revision in place: they create dataset revision N+1
(docs/decisions/0001-corrections-create-revisions.md), which is validated like any other
revision.

Value markers ("Incl.", "Nil", "entfällt" in numeric columns) are not numbers: ``number*``
returns ``None`` for them and ``marker*`` says what they mean, so a detector can tell
"included elsewhere" from "missing".

:meth:`ValidationContext.rows` also enforces the detector's time limit while iterating; a
detector that does heavy work outside row loops calls :meth:`ValidationContext.checkpoint`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.clock import Clock
from app.core.config import ValidationLimits
from app.core.ids import IdFactory
from app.models.bill_review import BillReview
from app.models.dataset import Cell, CellRef, Column, Dataset, Row, RowKind, Table
from app.models.material_answers import MaterialAnswers
from app.models.model_takeoff import ModelTakeoff
from app.models.profile import DomainProfile, FieldRole, SemanticField
from app.models.tender import Tender
from app.models.values import CellValue, NumberValue, ParseStatus, TextValue, ValueMarker
from app.profiles.currency import CurrencyResolver
from app.profiles.units import UnitCatalog, UnitLookup
from app.validation.contracts.issue_factory import IssueFactory
from app.validation.contracts.limits import Deadline
from app.validation.contracts.scopes import (
    Basis,
    grand_total_bases,
    gross_total_bases,
    subtotal_bases,
)

USABLE_PARSE_STATUSES: frozenset[ParseStatus] = frozenset({ParseStatus.EXACT, ParseStatus.INFERRED})
ITEM_ROWS: frozenset[RowKind] = frozenset({RowKind.ITEM})
_DEADLINE_CHECK_EVERY = 256


@dataclass(frozen=True, slots=True)
class ValidationContext:
    dataset: Dataset
    document_id: str
    profile: DomainProfile
    run_id: str
    issues: IssueFactory
    units: UnitCatalog
    currencies: CurrencyResolver
    deadline: Deadline | None = None  # set per detector by the pipeline
    # The quantities of the model (IFC) attached to the document, if any.
    model: ModelTakeoff | None = None
    # The local model's stored answers on material matches (statistical.open_price_reference);
    # ``None`` when none are stored. Read only: no check calls a model.
    material_answers: MaterialAnswers | None = None
    # What Claude answered when a reviewer sent it this bill (llm.bill_review); ``None`` when
    # no review is stored. Read only: no check calls a model.
    bill_review: BillReview | None = None
    # The tender this bill answers, found in its project (``app.services.tenders``); ``None``
    # when the bill has no prices or its project holds no matching tender.
    tender: Tender | None = None
    # Lookups derived from the (immutable) dataset, built once and shared by the per-detector
    # copies of a run's context (``dataclasses.replace`` keeps it), e.g. the scope index.
    memo: dict[object, object] = field(default_factory=dict, repr=False, compare=False)

    def checkpoint(self) -> None:
        """Raise :class:`~app.validation.contracts.limits.TimeLimitReached` when the
        detector's time limit has passed."""
        if self.deadline is not None:
            self.deadline.check()

    # ----------------------------------------------------------------- structure
    def tables(self) -> list[Table]:
        return list(self.dataset.tables)

    def column(self, table: Table, field_id: str) -> Column | None:
        return table.column_for_field(field_id)

    def has_fields(self, table: Table, *field_ids: str) -> bool:
        return all(table.column_for_field(f) is not None for f in field_ids)

    def profile_field(self, field_id: str) -> SemanticField | None:
        return self.profile.field(field_id)

    def rows(
        self,
        table: Table,
        kinds: Collection[RowKind] | None = ITEM_ROWS,
        *,
        include_excluded: bool = False,
    ) -> Iterator[Row]:
        """Rows of the given kinds (default: item rows) in source order. ``kinds=None`` yields
        every row. Rows a reviewer marked as not data (``Row.excluded``) are skipped unless
        ``include_excluded``; they are never counted in sums either. Checks the detector's
        time limit every few hundred rows."""
        for index, row in enumerate(table.rows):
            if index % _DEADLINE_CHECK_EVERY == 0:
                self.checkpoint()
            if row.excluded and not include_excluded:
                continue
            if kinds is None or row.kind in kinds:
                yield row

    # --------------------------------------------------------------- by column id
    def cell_at(self, row: Row, column_id: str) -> Cell | None:
        return row.cells.get(column_id)

    def number_value_at(self, row: Row, column_id: str) -> NumberValue | None:
        """Normalized number of a cell, only if it was parsed exactly or by documented
        inference. Ambiguous, failed, unavailable and non-numeric cells return ``None``."""
        cell = self.cell_at(row, column_id)
        if cell is None or cell.parse_status not in USABLE_PARSE_STATUSES:
            return None
        value = cell.normalized_value
        return value if isinstance(value, NumberValue) else None

    def number_at(self, row: Row, column_id: str) -> Decimal | None:
        value = self.number_value_at(row, column_id)
        return value.value if value else None

    def value_at(self, row: Row, column_id: str) -> CellValue | None:
        """Typed value of a cell as normalization stored it: a number (only parsed exactly or
        by documented inference), text (also failed and marker cells, as written), a date, a
        yes/no value or a spreadsheet error. ``None`` for empty, ambiguous and unavailable
        cells. For comparing cells as written and for reporting what a cell holds; checks that
        compute use :meth:`number_at` and :meth:`text_at`."""
        cell = self.cell_at(row, column_id)
        return None if cell is None else cell.normalized_value

    def marker_at(self, row: Row, column_id: str) -> ValueMarker | None:
        """Meaning of a value-marker cell ("Incl.", "Nil", ...), else ``None``."""
        cell = self.cell_at(row, column_id)
        return cell.marker if cell is not None else None

    def text_at(self, row: Row, column_id: str) -> str | None:
        """Normalized text of a cell; falls back to the stripped raw text for non-text values
        (an item code typed as a number). Empty cells return ``None``."""
        cell = self.cell_at(row, column_id)
        if cell is None or cell.is_empty:
            return None
        if isinstance(cell.normalized_value, TextValue):
            return cell.normalized_value.value or None
        raw = (cell.raw_value or "").strip()
        return raw or None

    # ----------------------------------------------------------- by semantic field
    def cell(self, table: Table, row: Row, field_id: str) -> Cell | None:
        column = table.column_for_field(field_id)
        return None if column is None else self.cell_at(row, column.column_id)

    def cell_ref(self, table: Table, row: Row, field_id_or_column_id: str) -> CellRef:
        """Reference by semantic field id (preferred) or by column id."""
        column = table.column_for_field(field_id_or_column_id)
        column_id = column.column_id if column else field_id_or_column_id
        return self.issues.cell_ref(table, row, column_id)

    def number_value(self, table: Table, row: Row, field_id: str) -> NumberValue | None:
        column = table.column_for_field(field_id)
        return None if column is None else self.number_value_at(row, column.column_id)

    def number(self, table: Table, row: Row, field_id: str) -> Decimal | None:
        value = self.number_value(table, row, field_id)
        return value.value if value else None

    def value(self, table: Table, row: Row, field_id: str) -> CellValue | None:
        column = table.column_for_field(field_id)
        return None if column is None else self.value_at(row, column.column_id)

    def text(self, table: Table, row: Row, field_id: str) -> str | None:
        column = table.column_for_field(field_id)
        return None if column is None else self.text_at(row, column.column_id)

    def marker(self, table: Table, row: Row, field_id: str) -> ValueMarker | None:
        column = table.column_for_field(field_id)
        return None if column is None else self.marker_at(row, column.column_id)

    # ------------------------------------------------------------ units, currency
    def unit_field_id(self) -> str | None:
        """The profile field with role ``unit`` (``None`` when the profile has none)."""
        fields = self.profile.fields_with_role(FieldRole.UNIT)
        return fields[0].field_id if fields else None

    def unit(self, table: Table, row: Row, field_id: str | None = None) -> UnitLookup | None:
        """The row's unit after reviewer decisions, with a leading multiplier ("100 St")
        when the unit text has one; ``None`` when the unit cell is empty or not a known unit.

        Normalization stores the canonical ``unit_id`` as the unit cell's normalized value
        (also for units a reviewer aliased); the raw text is consulted for the multiplier."""
        field = field_id or self.unit_field_id()
        if field is None:
            return None
        cell = self.cell(table, row, field)
        if cell is None or cell.is_empty:
            return None
        lookup = self.units.lookup(cell.raw_value)
        if lookup is not None:
            return lookup
        normalized = cell.normalized_value
        if isinstance(normalized, TextValue):
            unit = self.units.get(normalized.value)
            if unit is not None:
                return UnitLookup(unit)
        return None

    def currency_evidence(self, table: Table, row: Row, field_ids: Iterable[str]) -> str | None:
        """The single currency explicitly marked for the given monetary cells: markers on the
        cells, currency codes in their column headers, and the row's currency column (the
        profile field with role ``currency``). ``None`` when nothing is marked *or* when the
        markers disagree, so a financial impact never carries a guessed currency."""
        found: set[str] = set()
        for field_id in field_ids:
            column = table.column_for_field(field_id)
            if column is None:
                continue
            if column.header_currency:
                found.add(column.header_currency)
            value = self.number_value(table, row, field_id)
            if value is not None and value.currency:
                found.add(value.currency)
        for currency_field in self.profile.fields_with_role(FieldRole.CURRENCY):
            text = self.text(table, row, currency_field.field_id)
            if text:
                code = self.currencies.resolve_token(text)
                if code is None:
                    return None  # an unreadable currency column entry: do not guess
                found.add(code)
        return found.pop() if len(found) == 1 else None

    # ----------------------------------------------------------------- total scopes
    def rows_in_scope(self, table: Table, total_row: Row, field_id: str) -> list[Basis]:
        """Candidate bases (member sets) of a SUBTOTAL, GRAND_TOTAL or GROSS_TOTAL row, per the
        "Total scopes" rules in ``docs/architecture/validation-engine.md``; empty for other
        rows. Judge a reported amount against them with :func:`scopes.judge`."""
        if total_row.kind is RowKind.SUBTOTAL:
            return subtotal_bases(self, table, total_row, field_id)
        if total_row.kind is RowKind.GRAND_TOTAL:
            return grand_total_bases(self, table, total_row, field_id)
        if total_row.kind is RowKind.GROSS_TOTAL:
            return gross_total_bases(self, table, total_row, field_id)
        return []


def build_validation_context(
    *,
    dataset: Dataset,
    profile: DomainProfile,
    run_id: str,
    limits: ValidationLimits,
    ids: IdFactory,
    clock: Clock,
    document_id: str | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    model: ModelTakeoff | None = None,
    material_answers: MaterialAnswers | None = None,
    bill_review: BillReview | None = None,
    tender: Tender | None = None,
) -> ValidationContext:
    """The one way a validation context and its issue factory are wired (the pipeline and
    the test helpers both use it), so caps, review caveats and deadlines behave the same in
    unit tests and in real runs. The deadline set here covers one detector; the pipeline
    replaces it before each step."""
    document = document_id or dataset.document_id
    return ValidationContext(
        dataset=dataset,
        document_id=document,
        profile=profile,
        run_id=run_id,
        issues=IssueFactory(
            dataset=dataset,
            document_id=document,
            run_id=run_id,
            ids=ids,
            clock=clock,
            low_confidence_threshold=limits.low_confidence_threshold,
            review_tables=review_tables(dataset),
            max_issues_per_detector=limits.max_issues_per_detector,
            max_issues_total=limits.max_issues_per_run,
        ),
        units=UnitCatalog.from_profile(profile),
        currencies=CurrencyResolver.from_profile(profile),
        deadline=Deadline(limits.max_detector_seconds, clock=monotonic),
        model=model,
        material_answers=material_answers,
        bill_review=bill_review,
        tender=tender,
    )


def review_tables(dataset: Dataset) -> dict[str | None, list[str]]:
    """Table id (``None`` = whole dataset) -> codes of extraction warnings that need review."""
    tables: dict[str | None, list[str]] = {}
    for warning in dataset.extraction.warnings:
        if warning.needs_review:
            tables.setdefault(warning.table_id, []).append(warning.code)
    return tables
