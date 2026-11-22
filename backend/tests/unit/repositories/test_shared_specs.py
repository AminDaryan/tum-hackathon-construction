"""Consistency of the specs both adapters share with the IssueQuery contract and the schema."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.models.audit import EntityType
from app.models.dataset import Dataset
from app.models.issue import EvidenceClass, ReviewStatus
from app.repositories import querying
from app.repositories.base import IssueCounts, IssueQuery
from app.repositories.errors import PersistenceError
from app.repositories.querying import (
    AUDIT_ORDER,
    COUNT_COLUMNS,
    COUNT_DIMENSIONS,
    DATASET_ORDER,
    DOCUMENT_ORDER,
    FINDING_CATEGORY,
    FINDING_CATEGORY_SOURCES,
    ISSUE_FILTER_COLUMNS,
    ISSUE_ORDER,
    REVIEWED_ORDER,
    REVIEWED_STATUSES,
    RUN_ORDER,
    STYLE_FINDING,
    finding_category_key,
    issue_column_value,
    issue_conditions,
    reviewed_conditions,
)
from app.repositories.records import (
    audit_columns,
    dataset_columns,
    document_columns,
    issue_columns,
    run_columns,
)
from app.repositories.sql import schema
from tests.unit.repositories.samples import (
    cell_at,
    make_document,
    make_event,
    make_issue,
    make_run,
)

BERLIN = timezone(timedelta(hours=2))


def test_every_issue_query_field_maps_to_an_issue_column() -> None:
    """Every filter names a stored column, except the finding category: it is derived from
    stored columns and has no column of its own."""
    assert set(ISSUE_FILTER_COLUMNS) == {f.name for f in fields(IssueQuery)}
    assert set(ISSUE_FILTER_COLUMNS.values()) - {FINDING_CATEGORY} <= set(schema.issues.c.keys())
    assert FINDING_CATEGORY not in schema.issues.c
    assert set(FINDING_CATEGORY_SOURCES) <= set(schema.issues.c.keys())


def test_count_dimensions_cover_issue_counts() -> None:
    assert {name for name, _ in COUNT_DIMENSIONS} == {
        f.name for f in fields(IssueCounts) if f.name != "total"
    }


def test_counts_group_by_stored_columns_only() -> None:
    """The finding category is counted from the columns it is derived from, so no backend has
    to group by an expression."""
    dimension_columns = {column for _, column in COUNT_DIMENSIONS}
    assert set(COUNT_COLUMNS) == dimension_columns - {FINDING_CATEGORY} | set(
        FINDING_CATEGORY_SOURCES
    )
    assert len(COUNT_COLUMNS) == len(set(COUNT_COLUMNS))
    assert set(COUNT_COLUMNS) <= set(schema.issues.c.keys())


@pytest.mark.parametrize(
    ("detector_id", "rule_id", "evidence_class", "key"),
    [
        ("deterministic.line_total", "line_total_mismatch", "confirmed_rule_violation", "error"),
        # Downgraded by the evidence policy (a PDF value): still an error.
        ("deterministic.line_total", "line_total_mismatch", "extraction_uncertainty", "error"),
        ("deterministic.subtotal", "subtotal_display_rounding", "extraction_uncertainty", "none"),
        (
            "deterministic.unit_compatibility",
            "same_description_dimension",
            "semantic_warning",
            "inconsistency",
        ),
        ("deterministic.unit_vocabulary", "unknown_unit", "needs_external_context", "none"),
        ("test.alpha", "default", "confirmed_rule_violation", "none"),
    ],
)
def test_the_finding_category_is_derived_from_stored_columns(
    detector_id: str, rule_id: str, evidence_class: str, key: str
) -> None:
    issue = make_issue(
        "iss_1",
        detector_id=detector_id,
        rule_id=rule_id,
        evidence_class=EvidenceClass(evidence_class),
        review_status=ReviewStatus.CONFIRMED_ERROR,  # the effective class does not matter
    )
    columns = issue_columns(issue)
    assert issue_column_value(columns, FINDING_CATEGORY) == key
    assert finding_category_key(issue.finding_category) == key
    assert issue_column_value(columns, "detector_id") == detector_id  # stored columns as stored
    assert FINDING_CATEGORY not in columns  # derived, never projected or stored


def test_a_query_attribute_without_a_column_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    reduced = {k: v for k, v in ISSUE_FILTER_COLUMNS.items() if k != "row_id"}
    monkeypatch.setattr(querying, "ISSUE_FILTER_COLUMNS", reduced)
    assert issue_conditions(IssueQuery(table_id="tbl_1")) == [("table_id", frozenset({"tbl_1"}))]
    with pytest.raises(PersistenceError, match="row_id"):
        issue_conditions(IssueQuery(row_id="row_1"))


def test_projections_match_the_sql_columns(dataset: Dataset) -> None:
    projections = [
        (schema.documents, document_columns(make_document())),
        (schema.datasets, dataset_columns(dataset)),
        (schema.validation_runs, run_columns(make_run())),
        (schema.issues, issue_columns(make_issue("iss_1", cells=[cell_at(0, 3, 2)]))),
        (schema.audit_events, audit_columns(make_event("aud_1"))),
    ]
    for table, columns in projections:
        stored_elsewhere = {"seq", "payload", "snapshot", "snapshot_codec", "snapshot_sha256"}
        assert set(columns) == set(table.c.keys()) - stored_elsewhere, table.name


@pytest.mark.parametrize(
    ("table", "order"),
    [
        (schema.documents, DOCUMENT_ORDER),
        (schema.datasets, DATASET_ORDER),
        (schema.validation_runs, RUN_ORDER),
        (schema.issues, ISSUE_ORDER),
        (schema.issues, REVIEWED_ORDER),
        (schema.audit_events, AUDIT_ORDER),
    ],
    ids=lambda value: getattr(value, "name", None) or "order",
)
def test_orderings_use_existing_columns_with_matching_nullability(table, order) -> None:
    for term in order:
        if term.column == STYLE_FINDING:  # derived from detector_id and rule_id, never NULL
            assert term.nulls is None
            continue
        column = table.c[term.column]
        assert (term.nulls is not None) == column.nullable, term.column
    assert order[-1].column in {"seq", *table.primary_key.columns.keys()}  # total order


def test_issue_sort_keys_come_from_the_first_affected_cell() -> None:
    issue = make_issue("iss_1", cells=[cell_at(2, 14, 5), cell_at(0, 1, 1)])
    columns = issue_columns(issue)
    assert (columns["sort_sheet"], columns["sort_row"], columns["sort_column"]) == (2, 14, 5)
    assert (columns["severity_rank"], columns["effective_evidence_class"]) == (
        2,
        "confirmed_rule_violation",
    )


def test_reviewed_issues_are_selected_with_shared_columns() -> None:
    conditions = reviewed_conditions("doc_1", ["fp_1", "fp_2"])
    assert {column for column, _ in conditions} <= set(schema.issues.c.keys())
    assert ReviewStatus.PENDING_REVIEW.value not in REVIEWED_STATUSES
    assert len(REVIEWED_STATUSES) == len(ReviewStatus) - 1


def test_new_projections_are_plain_values() -> None:
    reviewed = make_issue("iss_1").with_review(
        ReviewStatus.FALSE_POSITIVE, None, at=datetime(2026, 3, 1, 10, 30, tzinfo=BERLIN)
    )
    columns = issue_columns(reviewed)
    assert (columns["document_id"], columns["version"]) == ("doc_000001", 2)
    assert columns["reviewed_at"] == datetime(2026, 3, 1, 8, 30, tzinfo=UTC)  # ordered in UTC
    assert issue_columns(make_issue("iss_2"))["reviewed_at"] is None
    entity_type = audit_columns(make_event("aud_1", entity_type=EntityType.VALIDATION_RUN))[
        "entity_type"
    ]
    assert type(entity_type) is str  # stored as the value, never as the enum member
    assert entity_type == "validation_run"
