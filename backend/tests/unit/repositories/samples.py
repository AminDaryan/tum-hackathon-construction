"""Deterministic sample records and small helpers for the repository tests.

Datasets come from :class:`tests.support.builders.DatasetBuilder`. Issues are mostly built
directly so a test controls exactly the attributes it filters or orders on; tests that need
realistic issues use the ``IssueFactory`` of :func:`tests.support.builders.make_context`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from app.models.audit import AuditAction, AuditEvent, EntityType
from app.models.dataset import CellRef, Column, Dataset, ExtractionWarning, Row, RowKind, Table
from app.models.document import Document, DocumentFormat, ProcessingStatus, StoredFile
from app.models.explanation import Claim, DroppedClaim, Explanation, ExplanationStatus
from app.models.issue import (
    EvidenceClass,
    IssueCategory,
    ReviewStatus,
    Severity,
    ValidationIssue,
)
from app.models.plan import PlannerKind, ValidationPlan
from app.models.profile import DomainProfile
from app.models.run import RunStatus, ValidationRun
from app.models.source import SourceKind, SourceLocation
from app.repositories.base import UnitOfWork, UnitOfWorkFactory
from app.validation.contracts.detector import DetectorCategory, DetectorSpec
from tests.support.builders import DatasetBuilder, ambiguous_cell, number_cell

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class Boom(Exception):
    """Raised inside a unit of work to force a rollback."""


def fail_after(factory: UnitOfWorkFactory, action: Callable[[UnitOfWork], object]) -> None:
    """Run ``action`` in a unit of work, then raise :class:`Boom` inside the block."""
    with factory() as uow:
        action(uow)
        raise Boom


BOQ_COLUMNS = [
    ("Item", "item_code"),
    ("Description", "description"),
    ("Qty", "quantity"),
    ("Unit", "unit"),
    ("Rate", "unit_price"),
    ("Amount", "line_total"),
]

# A detector spec for issues created through the IssueFactory in tests.
PROBE_SPEC = DetectorSpec(
    detector_id="test.repository_probe",
    name="Repository probe",
    version="1.0.0",
    category=DetectorCategory.DETERMINISTIC,
    description="Creates findings for persistence tests.",
    applicability="always",
    evidence_classes=(
        EvidenceClass.CONFIRMED_RULE_VIOLATION,
        EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
    ),
    issue_categories=(IssueCategory.ARITHMETIC, IssueCategory.MISSING_VALUE),
)


def minutes(n: float) -> datetime:
    """``T0`` plus ``n`` minutes."""
    return T0 + timedelta(minutes=n)


def make_document(
    document_id: str = "doc_000001",
    *,
    uploaded_at: datetime = T0,
    status: ProcessingStatus = ProcessingStatus.PROCESSED,
    failure_reason: str | None = None,
) -> Document:
    digest = hashlib.sha256(document_id.encode()).hexdigest()
    return Document(
        document_id=document_id,
        original_filename=f"{document_id}.xlsx",
        format=DocumentFormat.XLSX,
        uploaded_at=uploaded_at,
        source_file=StoredFile(
            storage_key=digest,
            sha256=digest,
            size_bytes=48_211,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        processing_status=status,
        failure_reason=failure_reason,
        profile_id="boq",
    )


def build_dataset(
    profile: DomainProfile, *, document_id: str = "doc_000001", dataset_id: str = "ds_000001"
) -> Dataset:
    """Two tables on two sheets with exact decimals, unicode text, a currency-tagged formula
    cell and an ambiguous cell, so a round trip has something to lose."""
    builder = DatasetBuilder(profile, document_id=document_id, dataset_id=dataset_id)
    bill = builder.table("LV", BOQ_COLUMNS)
    bill.row([None, "Erdarbeiten", None, None, None, None], kind=RowKind.SECTION)
    bill.row(["01.001", "Aushub – Bodenklasse 3", "10.500", "m³", "12.50", "131.25"])
    bill.row(
        [
            "01.002",
            "Verfüllung",
            "0.0001",
            "m3",
            number_cell("1234.5678", currency="EUR", formula="=C4*E4"),
            ambiguous_cell("1,234"),
        ]
    )
    bill.row([None, "Summe Erdarbeiten", None, None, None, "1E+3"], kind=RowKind.SUBTOTAL)
    other = builder.table("Preliminaries", [("Item", "item_code"), ("Amount", "line_total")])
    other.row(["00.001", "-2500.00"])
    return builder.build()


def make_run(
    run_id: str = "run_000001",
    *,
    document_id: str = "doc_000001",
    dataset_id: str = "ds_000001",
    revision: int = 1,
    started_at: datetime = T0,
    status: RunStatus = RunStatus.COMPLETED,
    finished_at: datetime | None = None,
    issue_count: int = 0,
) -> ValidationRun:
    return ValidationRun(
        run_id=run_id,
        document_id=document_id,
        dataset_id=dataset_id,
        dataset_revision=revision,
        profile_id="boq",
        status=status,
        plan=ValidationPlan(planner=PlannerKind.BASELINE, steps=[]),
        started_at=started_at,
        finished_at=finished_at,
        issue_count=issue_count,
    )


def cell_at(
    sheet: int | None,
    row: int | None,
    column: int | None,
    *,
    table_id: str = "tbl_000001",
    row_id: str = "row_000001",
    column_id: str = "col_000001",
) -> CellRef:
    """A cell reference whose source sits at ``(sheet_index, row_number, column_number)``;
    ``row=None`` makes it a table-level (sheet) location."""
    return CellRef(
        table_id=table_id,
        row_id=row_id,
        column_id=column_id,
        source=SourceLocation(
            kind=SourceKind.SPREADSHEET,
            sheet_name=f"Sheet {sheet}",
            sheet_index=sheet,
            row_number=row,
            column_number=column,
        ),
    )


def make_issue(
    issue_id: str,
    *,
    run_id: str = "run_000001",
    document_id: str = "doc_000001",
    dataset_id: str = "ds_000001",
    fingerprint: str | None = None,
    severity: Severity = Severity.MEDIUM,
    evidence_class: EvidenceClass = EvidenceClass.CONFIRMED_RULE_VIOLATION,
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW,
    detector_id: str = "test.alpha",
    rule_id: str = "default",
    category: str = IssueCategory.ARITHMETIC,
    table_id: str | None = "tbl_000001",
    row_id: str | None = "row_000001",
    cells: Sequence[CellRef] = (),
) -> ValidationIssue:
    return ValidationIssue(
        issue_id=issue_id,
        fingerprint=fingerprint or hashlib.sha256(issue_id.encode()).hexdigest()[:32],
        validation_run_id=run_id,
        document_id=document_id,
        dataset_id=dataset_id,
        dataset_revision=1,
        table_id=table_id,
        row_id=row_id,
        affected_cells=list(cells),
        detector_id=detector_id,
        detector_version="1.0.0",
        rule_id=rule_id,
        issue_category=category,
        severity=severity,
        evidence_class=evidence_class,
        title=f"Finding {issue_id}",
        explanation="Synthetic finding for the repository tests.",
        review_status=review_status,
        created_at=T0,
    )


def make_explanation(
    explanation_id: str = "exp_000001",
    *,
    run_id: str = "run_000001",
    problem_id: str = "prb_line_total_1",
    created_at: datetime = T0,
    status: ExplanationStatus = ExplanationStatus.COMPLETED,
) -> Explanation:
    """An explanation in ``status``; a completed one has a claim, a dropped claim, its prompt
    and output (with non-ASCII text), a failed one an error."""
    finished = status in (ExplanationStatus.COMPLETED, ExplanationStatus.FAILED)
    completed = status is ExplanationStatus.COMPLETED
    return Explanation(
        explanation_id=explanation_id,
        run_id=run_id,
        problem_id=problem_id,
        status=status,
        created_at=created_at,
        finished_at=created_at + timedelta(seconds=12) if finished else None,
        provider="ollama",
        model="example-model:7b",
        model_digest="0123abcd" if finished else None,
        server_version="0.9.0" if finished else None,
        prompt_version="explain-1",
        input_digest=hashlib.sha256(problem_id.encode()).hexdigest(),
        claims=[
            Claim(
                section="summary",
                text="Der Gesamtpreis {F1.line_total} passt nicht zu "
                "{F1.quantity} × {F1.unit_price}.",
                rendered="Der Gesamtpreis 1.822,50 € passt nicht zu 12,5 m³ × 154,80 €.",
                cites=["iss_000001"],
            ),
            Claim(
                section="next_check",
                text="Prüfen Sie den Einheitspreis.",
                rendered="Prüfen Sie den Einheitspreis.",
                cites=[],
            ),
        ]
        if completed
        else [],
        dropped=[
            DroppedClaim(text="Der Preis ist 12 % zu hoch.", reason="a number outside the slots")
        ]
        if completed
        else [],
        prompt="Erkläre das Problem: {F1} …" if finished else None,
        raw_output='{"summary": ["…"]}' if finished else None,
        error="The model did not answer in time." if status is ExplanationStatus.FAILED else None,
        duration_ms=12_000 if finished else None,
    )


def make_event(
    event_id: str,
    *,
    entity_id: str = "iss_000001",
    entity_type: EntityType = EntityType.ISSUE,
    occurred_at: datetime = T0,
    action: AuditAction = AuditAction.ISSUE_REVIEWED,
) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        actor="system",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=f"Event {event_id}",
        before={"review_status": "pending_review"},
        after={"review_status": "confirmed_error", "comment": "Prüfung: Menge × Preis"},
        context={"amount": "12.50", "items": [1, 2, 3]},
    )


def review_state(issue: ValidationIssue) -> dict[str, object]:
    """What a review audit event records about an issue before and after a decision."""
    return {
        "review_status": issue.review_status.value,
        "reviewer_comment": issue.reviewer_comment,
        "version": issue.version,
    }


def review_event(event_id: str, before: ValidationIssue, after: ValidationIssue) -> AuditEvent:
    """The audit event of the decision that turned ``before`` into ``after``."""
    assert after.reviewed_at is not None
    return AuditEvent(
        event_id=event_id,
        occurred_at=after.reviewed_at,
        actor="local",
        action=AuditAction.ISSUE_REVIEWED,
        entity_type=EntityType.ISSUE,
        entity_id=after.issue_id,
        summary=f"{before.review_status.value} -> {after.review_status.value}",
        before=review_state(before),
        after=review_state(after),
    )


# ------------------------------------------------------------- newer model fields
CONTRACT_COLUMNS = [*BOQ_COLUMNS, ("Intern", None)]  # the last column is hidden in the source


def build_contract_dataset(
    profile: DomainProfile, *, document_id: str = "doc_000001", dataset_id: str = "ds_000001"
) -> Dataset:
    """A dataset that uses every newer model field, so a round trip has them to lose: value
    markers, the row kinds adjustment / carry_forward / summary_line (and tax, gross and
    grand totals), hidden and grouped rows, a continuation row, classification codes,
    undecided and inherited not-counted items, a hidden column, column currency and decimal
    separator, and an informational extraction warning."""
    hidden_rows = ExtractionWarning(
        code="hidden_rows_present",
        message="1 hidden row was extracted.",
        table_id="tbl_000001",
        count=1,
        needs_review=False,
    )
    builder = DatasetBuilder(
        profile, warnings=[hidden_rows], document_id=document_id, dataset_id=dataset_id
    )
    bill = builder.table("LV", CONTRACT_COLUMNS)
    bill.row(["01", "Erdarbeiten", None, None, None, None, None], kind=RowKind.SECTION, code="01")
    bill.row(["01.001", "Aushub", "10.500", "m³", "12.50", "131.25", "x"], code="01.001")  # 1
    bill.row(
        [None, "inkl. Abfuhr des Aushubs", None, None, None, None, None],
        kind=RowKind.TEXT,
        belongs_to=1,
    )
    bill.row(["01.002", "Verbau", "psch", "psch", "500.00", "Incl.", None], code="01.002")
    bill.row(
        ["01.003", "Wasserhaltung (Bedarfsposition)", "1", "St", "800.00", "800.00", None],
        in_totals=None,
        hidden=True,
    )  # 4
    bill.row(
        ["01.004", "Alternativ: Spundwand", "5", "m", "90.00", "450.00", None], in_totals=False
    )
    bill.row([None, "Übertrag", None, None, None, "931.25", None], kind=RowKind.CARRY_FORWARD)
    bill.row([None, "Summe 01", None, None, None, "931.25", None], kind=RowKind.SUBTOTAL, code="01")
    bill.row(["02", "Optionale Leistungen", None, None, None, None, None], kind=RowKind.SECTION)
    bill.row(["02.001", "Option", "2", "m2", "10.00", "20.00", None], in_totals=False)  # 9
    bill.row([None, "Nachlass 3 %", None, None, None, "-27.94", None], kind=RowKind.ADJUSTMENT)
    bill.row([None, "Summe netto", None, None, None, "903.31", None], kind=RowKind.GRAND_TOTAL)
    bill.row([None, "MwSt 19 %", None, None, None, "171.63", None], kind=RowKind.TAX)
    bill.row([None, "Summe brutto", None, None, None, "1074.94", None], kind=RowKind.GROSS_TOTAL)
    recap = builder.table(
        "Zusammenstellung",
        [("Item", "item_code"), ("Description", "description"), ("Amount", "line_total")],
    )
    recap.row(["01", "Erdarbeiten", "931.25"], kind=RowKind.SUMMARY_LINE)
    dataset = builder.build()
    bill_table, recap_table = dataset.tables
    return dataset.evolve(tables=[_contract_details(bill_table), recap_table])


def _contract_details(table: Table) -> Table:
    """Fields the builder does not set: outline levels, an inherited not-counted section, a
    hidden column, column currency and decimal separator."""
    optional_section = table.rows[8].row_id
    rows = list(table.rows)
    rows[4] = rows[4].evolve(outline_level=1)
    rows[9] = _not_counted_above(rows[9], optional_section)
    columns = [_column_details(column) for column in table.columns]
    return table.evolve(rows=rows, columns=columns)


def _not_counted_above(row: Row, section_id: str) -> Row:
    classification = row.classification.evolve(
        not_counted_above_section_id=section_id, totals_rule="optional_section"
    )
    return row.evolve(classification=classification)


def _column_details(column: Column) -> Column:
    if column.original_header == "Intern":
        return column.evolve(source_hidden=True)
    if column.mapped_semantic_field == "line_total":
        return column.evolve(
            header_currency="EUR",
            decimal_separator=",",
            type_profile=column.type_profile.evolve(marker_count=1),
        )
    return column
