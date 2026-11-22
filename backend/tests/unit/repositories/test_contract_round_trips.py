"""Round trips of the newer model fields on both adapters (NEXT_STEPS step 4).

Every check compares the stored record with the original twice: by model equality and by its
JSON dump, which also catches what equality hides (``Decimal("10.5") == Decimal("10.500")``,
``True == 1``, an enum member compared with its value). Datasets are decoded for real: the SQL
adapter's write-through cache is cleared first, and the in-memory adapter (which keeps the
dataset as given) is backed by the codec round trip of the same dataset.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select, update

from app.core.errors import InvalidInputError
from app.models.audit import AuditAction, EntityType
from app.models.dataset import Dataset, RowKind
from app.models.finding_category import FindingCategory
from app.models.issue import (
    Calculation,
    CalculationOperand,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    ReviewStatus,
    Severity,
    ValidationIssue,
)
from app.models.profile import DomainProfile
from app.models.run import DetectorExecutionStatus, DetectorRunReport, RunStatus
from app.models.schema import SchemaDecisions, TableDecisions
from app.models.values import ParseStatus, ValueMarker
from app.repositories.base import IssueQuery, UnitOfWorkFactory
from app.repositories.records import load_model, to_payload
from app.repositories.snapshot_codec import decode_dataset, encode_dataset
from app.repositories.sql import Database, SqlUnitOfWorkFactory
from app.repositories.sql.schema import issues as issue_table
from app.validation.contracts.issue_factory import money_impact
from tests.support.builders import make_context
from tests.unit.repositories.samples import (
    PROBE_SPEC,
    build_contract_dataset,
    make_document,
    make_event,
    make_issue,
    make_run,
    minutes,
)


def assert_same_record(stored: BaseModel, original: BaseModel) -> None:
    assert type(stored) is type(original)
    assert stored == original
    assert stored.model_dump(mode="json") == original.model_dump(mode="json")


def forget_decoded(factory: UnitOfWorkFactory) -> None:
    """Make the next dataset read decode the stored snapshot (SQL adapter)."""
    if isinstance(factory, SqlUnitOfWorkFactory):
        factory.database.dataset_cache.clear()


@pytest.fixture
def contract_dataset(boq_profile: DomainProfile) -> Dataset:
    return build_contract_dataset(boq_profile)


# ------------------------------------------------------------------------- datasets
def test_newer_dataset_fields_survive_storage(
    uow_factory: UnitOfWorkFactory, contract_dataset: Dataset
) -> None:
    with uow_factory() as uow:
        uow.documents.add(make_document())
        uow.datasets.add(contract_dataset)
    forget_decoded(uow_factory)
    with uow_factory() as uow:
        stored = uow.datasets.get(contract_dataset.dataset_id, 1)
    assert stored is not None
    assert_same_record(stored, contract_dataset)
    assert_same_record(decode_dataset(encode_dataset(contract_dataset)), contract_dataset)

    bill, recap = stored.tables
    rows = bill.rows
    kinds = [row.kind for row in rows]
    assert {RowKind.ADJUSTMENT, RowKind.CARRY_FORWARD, RowKind.TAX, RowKind.GROSS_TOTAL} <= set(
        kinds
    )
    assert recap.rows[0].kind is RowKind.SUMMARY_LINE
    # Markers: status, meaning and the raw text, no invented number.
    lump_sum = rows[3].cells[bill.column_for_field("quantity").column_id]
    included = rows[3].cells[bill.column_for_field("line_total").column_id]
    assert (lump_sum.parse_status, lump_sum.marker, lump_sum.raw_value) == (
        ParseStatus.MARKER,
        ValueMarker.LUMP_SUM,
        "psch",
    )
    assert type(included.marker) is ValueMarker
    assert included.marker is ValueMarker.INCLUDED_ELSEWHERE
    # Hidden and grouped rows, continuation rows.
    assert (rows[4].source_hidden, rows[4].outline_level) == (True, 1)
    assert type(rows[4].outline_level) is int
    assert (rows[1].source_hidden, rows[1].outline_level) == (False, None)
    assert rows[2].belongs_to_row_id == rows[1].row_id
    # Classification: code, undecided and not-counted items, an inherited decision.
    assert [rows[0].classification.code, rows[7].classification.code] == ["01", "01"]
    assert rows[4].counts_toward_totals is None
    assert rows[5].counts_toward_totals is False
    assert rows[9].classification.not_counted_above_section_id == rows[8].row_id
    # Columns: hidden in the source, header currency, decimal separator, marker count.
    hidden = [column.original_header for column in bill.columns if column.source_hidden]
    assert hidden == ["Intern"]
    amount = bill.column_for_field("line_total")
    assert (amount.header_currency, amount.decimal_separator, amount.type_profile.marker_count) == (
        "EUR",
        ",",
        1,
    )
    assert stored.extraction.warnings[0].needs_review is False


# ----------------------------------------------------------------------------- runs
REPORTS = [
    DetectorRunReport(
        detector_id="deterministic.line_total",
        detector_version="1.0.0",
        status=DetectorExecutionStatus.STOPPED,
        limit_reached="time",
        issues_found=3,
        duration_ms=60_000.5,
        config={"tolerance": "0.01", "rounding": {"places": 2, "mode": "half_up"}},
        notes=["Stopped after 2,048 rows."],
        coverage={"rows_checked": 2048, "rows_skipped_missing_inputs": 7},
    ),
    DetectorRunReport(
        detector_id="deterministic.subtotal",
        detector_version="1.1.0",
        status=DetectorExecutionStatus.COMPLETED,
        limit_reached="issues",
        issues_found=10_000,
        issues_dropped=12,
    ),
    DetectorRunReport(
        detector_id="deterministic.grand_total",
        detector_version="1.0.0",
        status=DetectorExecutionStatus.FAILED,
        error="ValueError (see server log ref 3f2a)",
    ),
    DetectorRunReport(
        detector_id="statistical.mad",
        detector_version="0.1.0",
        status=DetectorExecutionStatus.SKIPPED,
        skipped_reasons=["Fewer than 8 comparable items."],
    ),
]


def test_stopped_detectors_and_limits_survive_storage(uow_factory: UnitOfWorkFactory) -> None:
    running = make_run(status=RunStatus.RUNNING).evolve(profile_version="1.1.0")
    finished = running.evolve(
        status=RunStatus.COMPLETED_WITH_ERRORS,
        finished_at=minutes(2),
        detector_reports=REPORTS,
        issue_count=10_003,
        warnings=["A detector was stopped by the run time limit."],
    )
    with uow_factory() as uow:
        uow.runs.add(running)
    with uow_factory() as uow:
        uow.runs.update(finished)
    with uow_factory() as uow:
        stored = uow.runs.get(running.run_id)
    assert stored is not None
    assert_same_record(stored, finished)
    statuses = [(r.status, r.limit_reached) for r in stored.detector_reports]
    assert statuses[:2] == [
        (DetectorExecutionStatus.STOPPED, "time"),
        (DetectorExecutionStatus.COMPLETED, "issues"),
    ]


# --------------------------------------------------------------------------- issues
def _factory_issues(dataset: Dataset, profile: DomainProfile) -> list[ValidationIssue]:
    """Findings made by the real IssueFactory: a table-level finding identified only by its
    subject, two findings of one rule on one cell told apart by subject, and a confirmed
    arithmetic finding with a calculation and a financial impact in an explicit currency."""
    context = make_context(dataset, profile)
    bill = dataset.tables[0]
    item = bill.rows[1]
    quantity = context.cell_ref(bill, item, "quantity")
    rate = context.cell_ref(bill, item, "unit_price")
    total = context.cell_ref(bill, item, "line_total")

    def probe(**changes: Any) -> ValidationIssue:
        arguments: dict[str, Any] = {
            "rule_id": "probe",
            "category": IssueCategory.MISSING_VALUE,
            "severity": Severity.MEDIUM,
            "evidence_class": EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            "title": "Probe finding",
            "explanation": "Created by the round-trip test.",
            "evidence": [EvidenceItem(kind=EvidenceKind.NOTE, label="Probe", detail="Probe.")],
        }
        return context.issues.create(PROBE_SPEC, **{**arguments, **changes})

    calculation = Calculation(
        operation="product",
        operands=[
            CalculationOperand(label="quantity", value=Decimal("10.500"), cell=quantity),
            CalculationOperand(label="unit price", value=Decimal("12.50"), cell=rate),
        ],
        terms=2,
        exact_result=Decimal("131.2500"),
        rounding="2 decimal places, half up",
        rounded_result=Decimal("131.25"),
        reported=Decimal("131.30"),
        difference=Decimal("0.05"),
        allowed_difference=Decimal("0.01"),
    )
    return [
        probe(table=bill, subject="unit_price"),
        probe(cells=[quantity], subject="quantity:minimum"),
        probe(cells=[quantity], subject="quantity:maximum"),
        probe(
            rule_id="line_total",
            category=IssueCategory.ARITHMETIC,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            cells=[total],
            inputs=[quantity, rate],
            observed_value="131.30",
            expected_value="131.25",
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.CALCULATION,
                    label="Quantity × unit price",
                    detail="10.500 × 12.50 = 131.25",
                    cells=[quantity, rate],
                    data={"difference": Decimal("0.05")},
                    calculation=calculation,
                )
            ],
            financial_impact=money_impact(
                Decimal("0.05"),
                "EUR",
                "line total",
                reported=Decimal("131.30"),
                recomputed=Decimal("131.25"),
            ),
        ),
    ]


def test_factory_issues_with_subjects_and_impacts_survive_storage(
    uow_factory: UnitOfWorkFactory, contract_dataset: Dataset, boq_profile: DomainProfile
) -> None:
    issues = _factory_issues(contract_dataset, boq_profile)
    table_level, minimum, maximum, arithmetic = issues
    assert (table_level.affected_cells, table_level.row_id) == ([], None)
    assert len({issue.fingerprint for issue in issues}) == 4  # subjects keep them apart
    assert minimum.affected_cells == maximum.affected_cells
    assert arithmetic.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION  # verified cells
    with uow_factory() as uow:
        uow.runs.add(make_run())
        uow.issues.add_many(issues)
    with uow_factory() as uow:
        stored = [uow.issues.get(issue.issue_id) for issue in issues]
        found = uow.issues.reviewed_by_fingerprint("doc_000001", [i.fingerprint for i in issues])
    for loaded, original in zip(stored, issues, strict=True):
        assert loaded is not None
        assert_same_record(loaded, original)
    impact = stored[3].estimated_financial_impact
    assert impact is not None
    assert (impact.currency, str(impact.amount), str(impact.reported)) == ("EUR", "0.05", "131.30")
    calculation = stored[3].evidence[0].calculation
    assert calculation is not None
    assert str(calculation.exact_result) == "131.2500"
    assert stored[3].evidence[0].data == {"difference": "0.05"}
    assert found == {}  # nothing is reviewed yet


def test_review_versions_survive_storage(
    uow_factory: UnitOfWorkFactory, contract_dataset: Dataset, boq_profile: DomainProfile
) -> None:
    original = _factory_issues(contract_dataset, boq_profile)[3]
    with uow_factory() as uow:
        uow.runs.add(make_run())
        uow.issues.add_many([original])
    confirmed = original.with_review(
        ReviewStatus.CONFIRMED_ERROR, "Rate × quantity checked by hand.", at=minutes(10)
    )
    reopened = confirmed.with_review(ReviewStatus.PENDING_REVIEW, "Re-check.", at=minutes(20))
    with uow_factory() as uow:
        uow.issues.update(confirmed, expected_version=1)
    with uow_factory() as uow:
        after_first = uow.issues.get(original.issue_id)
        uow.issues.update(reopened, expected_version=2)
    with uow_factory() as uow:
        after_second = uow.issues.get(original.issue_id)
    assert after_first is not None
    assert after_second is not None
    assert_same_record(after_first, confirmed)
    assert_same_record(after_second, reopened)
    assert (after_first.version, after_second.version) == (2, 3)
    assert after_first.effective_evidence_class is EvidenceClass.HUMAN_CONFIRMED_ERROR
    assert after_second.reviewed_at == minutes(20)


def test_issues_stored_before_finding_categories_load(sql_database: Database) -> None:
    """A row written before ``finding_category`` existed has no such key in its payload. It
    loads unchanged and gets its category computed: the value a payload carries is never read
    back, so the category needs no migration and follows the mapping of the code that reads
    it, also over a stale value."""
    factory = SqlUnitOfWorkFactory(sql_database)
    issue = make_issue(
        "iss_000001", detector_id="deterministic.line_total", rule_id="line_total_mismatch"
    )
    with factory() as uow:
        uow.runs.add(make_run())
        uow.issues.add_many([issue])
    with sql_database.engine.begin() as connection:
        payload = connection.execute(select(issue_table.c.payload)).scalar_one()
        assert payload["finding_category"] == "error"  # written as serialized
        legacy = {key: value for key, value in payload.items() if key != "finding_category"}
        connection.execute(update(issue_table).values(payload=legacy))
        assert (
            "finding_category" not in connection.execute(select(issue_table.c.payload)).scalar_one()
        )
    with factory() as uow:
        stored = uow.issues.get(issue.issue_id)
        page = uow.issues.query(IssueQuery(run_id="run_000001"))
        every = list(uow.issues.iter_all(IssueQuery(run_id="run_000001")))
    assert stored is not None
    assert_same_record(stored, issue)
    assert stored.finding_category is FindingCategory.ERROR
    assert page.items == every == [stored]
    with sql_database.engine.begin() as connection:
        connection.execute(
            update(issue_table).values(payload={**legacy, "finding_category": "risk"})
        )
    with factory() as uow:
        stale = uow.issues.get(issue.issue_id)
    assert stale is not None and stale.finding_category is FindingCategory.ERROR


# ---------------------------------------------------------------------------- audit
@pytest.mark.parametrize("entity_type", list(EntityType), ids=lambda t: t.value)
def test_audit_events_keep_their_entity_type(
    uow_factory: UnitOfWorkFactory, entity_type: EntityType
) -> None:
    event = make_event(
        "aud_1", entity_type=entity_type, entity_id="ent_1", action=AuditAction.DATASET_CREATED
    )
    with uow_factory() as uow:
        uow.audit.append(event)
        uow.audit.append(make_event("aud_other", entity_id="ent_1").evolve(entity_type="issue"))
    with uow_factory() as uow:
        by_member = uow.audit.list_for_entity(entity_type, "ent_1")
        by_value = uow.audit.list_for_entity(entity_type.value, "ent_1")
    expected = ["aud_1"] if entity_type is not EntityType.ISSUE else ["aud_1", "aud_other"]
    assert [e.event_id for e in by_member] == [e.event_id for e in by_value] == expected
    assert_same_record(by_member[0], event)
    assert type(by_member[0].entity_type) is EntityType


def test_an_unknown_entity_type_is_refused(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow, pytest.raises(InvalidInputError, match="issues") as refused:
        uow.audit.list_for_entity("issues", "iss_000001")
    assert refused.value.details["allowed"] == sorted(t.value for t in EntityType)


# ------------------------------------------------------------------ schema decisions
def test_schema_decisions_survive_the_shared_payload_encoding() -> None:
    # No repository stores SchemaDecisions in Phase 1 (there is no port for them); this pins
    # that the payload rules both adapters use keep them, including integer-keyed maps.
    decisions = SchemaDecisions(
        tables=[
            TableDecisions(
                sheet_index=2,
                include_hidden_sheet=True,
                header_row_numbers=[3, 4],
                column_fields={1: "item_code", 7: None},
                row_kinds={12: RowKind.CARRY_FORWARD, 40: RowKind.SUMMARY_LINE},
                not_data_rows=[99],
                counts_toward_totals={15: None, 16: False},
                section_levels={5: 2},
                closes_section={20: 5, 21: None},
                unit_aliases={"lfdm": "m"},
            )
        ],
        decided_by="local",
        decided_at=minutes(5),
    )
    restored = load_model(SchemaDecisions, to_payload(decisions), what="schema decisions")
    assert_same_record(restored, decisions)
    table = restored.tables[0]
    assert table.include_hidden_sheet is True
    assert list(table.row_kinds) == [12, 40]
    assert table.counts_toward_totals == {15: None, 16: False}
