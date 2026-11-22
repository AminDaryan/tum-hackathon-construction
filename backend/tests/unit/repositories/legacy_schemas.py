"""Databases in the layouts of earlier schema versions, for the migration tests.

The layouts are reconstructed from the history of ``app/repositories/sql/schema.py``: version 1
as of commit 0e18142, version 2 as of c2bb268, version 3 as of c04042e and version 4 as of
3db6c69. Records are written
the way those builds wrote them: the current column projections without the columns their
version lacks, and payloads without the fields their models lacked (version 1 issues have no
``version``); a test may pass payloads of its own for anything else an old build wrote.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    insert,
)

from app.models.audit import AuditEvent
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.issue import ValidationIssue
from app.models.run import ValidationRun
from app.repositories.records import (
    audit_columns,
    dataset_columns,
    document_columns,
    issue_columns,
    run_columns,
    to_payload,
)
from app.repositories.snapshot_codec import encode_dataset
from app.repositories.sql.schema import metadata as current_metadata

LEGACY_VERSIONS = (1, 2, 3, 4, 5, 6)
ADDED_IN_2 = ("seq", "document_id", "reviewed_at", "version")  # issues
ADDED_IN_3 = ("table_count", "row_count")  # datasets
ADDED_IN_4 = ("rule_id",)  # issues
ADDED_IN_5 = ("explanations",)  # tables


def legacy_metadata(version: int) -> MetaData:
    """The tables of schema ``version`` (1 to 6)."""
    if version not in LEGACY_VERSIONS:
        raise ValueError(f"no legacy layout for schema version {version}")
    metadata = MetaData(naming_convention=current_metadata.naming_convention)
    if version >= 6:
        Table(
            "projects",
            metadata,
            Column("project_id", String, primary_key=True),
            Column("payload", JSON, nullable=False),
        )
    Table(
        "schema_info",
        metadata,
        Column("key", String, primary_key=True),
        Column("value", String, nullable=False),
    )
    Table(
        "sequence_counters",
        metadata,
        Column("name", String, primary_key=True),
        Column("value", Integer, nullable=False),
    )
    Table(
        "documents",
        metadata,
        Column("document_id", String, primary_key=True),
        Column("seq", Integer, nullable=False),
        Column("uploaded_at", DateTime(timezone=True), nullable=False),
        Column("processing_status", String, nullable=False),
        Column("payload", JSON, nullable=False),
        Index("ix_documents_listing", "uploaded_at", "seq"),
    )
    counts = (
        [
            Column("table_count", Integer, nullable=False),
            Column("row_count", Integer, nullable=False),
        ]
        if version >= 3
        else []
    )
    Table(
        "datasets",
        metadata,
        Column("dataset_id", String, primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("document_id", String, ForeignKey("documents.document_id"), nullable=False),
        Column("seq", Integer, nullable=False),
        Column("profile_id", String, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        *counts,
        Column("snapshot", LargeBinary, nullable=False),
        Column("snapshot_codec", String, nullable=False),
        Column("snapshot_sha256", String, nullable=False),
        Index("ix_datasets_document", "document_id", "created_at", "seq"),
    )
    Table(
        "validation_runs",
        metadata,
        Column("run_id", String, primary_key=True),
        Column("seq", Integer, nullable=False),
        Column("dataset_id", String, nullable=False),
        Column("dataset_revision", Integer, nullable=False),
        Column("status", String, nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        Column("payload", JSON, nullable=False),
        Index("ix_validation_runs_dataset", "dataset_id", "started_at", "seq"),
    )
    v2 = version >= 2
    v4 = version >= 4
    run_order = (
        ("detector_id", "rule_id", "fingerprint", "seq", "issue_id") if v4 else ("issue_id",)
    )
    Table(
        "issues",
        metadata,
        Column("issue_id", String, primary_key=True),
        *([Column("seq", Integer, nullable=False)] if v2 else []),
        Column("validation_run_id", String, ForeignKey("validation_runs.run_id"), nullable=False),
        *([Column("document_id", String, nullable=False)] if v2 else []),
        Column("dataset_id", String, nullable=False),
        Column("dataset_revision", Integer, nullable=False),
        Column("table_id", String, nullable=True),
        Column("row_id", String, nullable=True),
        Column("detector_id", String, nullable=False),
        *([Column("rule_id", String, nullable=False)] if v4 else []),
        Column("issue_category", String, nullable=False),
        Column("severity", String, nullable=False),
        Column("severity_rank", Integer, nullable=False),
        Column("evidence_class", String, nullable=False),
        Column("effective_evidence_class", String, nullable=False),
        Column("review_status", String, nullable=False),
        *(
            [
                Column("reviewed_at", DateTime(timezone=True), nullable=True),
                Column("version", Integer, nullable=False),
            ]
            if v2
            else []
        ),
        Column("sort_sheet", Integer, nullable=True),
        Column("sort_row", Integer, nullable=True),
        Column("sort_column", Integer, nullable=True),
        Column("fingerprint", String, nullable=False),
        Column("payload", JSON, nullable=False),
        Index(
            "ix_issues_run_order",
            "validation_run_id",
            "severity_rank",
            "sort_sheet",
            "sort_row",
            "sort_column",
            *run_order,
        ),
        Index("ix_issues_run_severity", "validation_run_id", "severity"),
        Index("ix_issues_run_evidence", "validation_run_id", "effective_evidence_class"),
        Index("ix_issues_run_review", "validation_run_id", "review_status"),
        Index("ix_issues_run_detector", "validation_run_id", "detector_id"),
        Index("ix_issues_run_category", "validation_run_id", "issue_category"),
        Index("ix_issues_run_location", "validation_run_id", "table_id", "row_id"),
        Index("ix_issues_dataset", "dataset_id", "dataset_revision"),
        Index("ix_issues_document_fingerprint", "document_id", "fingerprint")
        if v2
        else Index("ix_issues_fingerprint", "fingerprint"),
    )
    Table(
        "audit_events",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("seq", Integer, nullable=False),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column("entity_type", String, nullable=False),
        Column("entity_id", String, nullable=False),
        Column("action", String, nullable=False),
        Column("payload", JSON, nullable=False),
        Index("ix_audit_events_entity", "entity_type", "entity_id", "occurred_at", "seq"),
    )
    if version >= 5:
        Table(
            "explanations",
            metadata,
            Column("explanation_id", String, primary_key=True),
            Column("seq", Integer, nullable=False),
            Column("run_id", String, ForeignKey("validation_runs.run_id"), nullable=False),
            Column("problem_id", String, nullable=False),
            Column("status", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("finished_at", DateTime(timezone=True), nullable=True),
            Column("payload", JSON, nullable=False),
            Index("ix_explanations_problem", "run_id", "problem_id", "created_at", "seq"),
        )
    return metadata


def legacy_issue_payload(issue: ValidationIssue, version: int) -> dict[str, Any]:
    payload = to_payload(issue)
    if version < 2:
        del payload["version"]  # optimistic concurrency arrived with version 2
    return payload


def write_legacy_database(
    engine: Engine,
    version: int,
    *,
    documents: Sequence[Document],
    datasets: Sequence[Dataset],
    runs: Sequence[ValidationRun],
    issues: Sequence[ValidationIssue],
    events: Sequence[AuditEvent],
    issue_payloads: Mapping[str, dict[str, Any]] | None = None,
) -> None:
    """Create the layout of ``version`` and store the records as that build stored them."""
    metadata = legacy_metadata(version)
    metadata.create_all(engine)
    tables = metadata.tables
    payloads = issue_payloads or {}

    def columns(table: str, values: Mapping[str, Any]) -> dict[str, Any]:
        return {name: value for name, value in values.items() if name in tables[table].c}

    rows: dict[str, list[dict[str, Any]]] = {
        "documents": [
            {**document_columns(d), "seq": n, "payload": to_payload(d)}
            for n, d in enumerate(documents, 1)
        ],
        "datasets": [],
        "validation_runs": [
            {**run_columns(r), "seq": n, "payload": to_payload(r)} for n, r in enumerate(runs, 1)
        ],
        "issues": [
            columns(
                "issues",
                {
                    **issue_columns(issue),
                    "seq": n,
                    "payload": payloads.get(issue.issue_id) or legacy_issue_payload(issue, version),
                },
            )
            for n, issue in enumerate(issues, 1)
        ],
        "audit_events": [
            {**audit_columns(e), "seq": n, "payload": to_payload(e)}
            for n, e in enumerate(events, 1)
        ],
    }
    for n, dataset in enumerate(datasets, 1):
        snapshot = encode_dataset(dataset)
        rows["datasets"].append(
            columns(
                "datasets",
                {
                    **dataset_columns(dataset),
                    "seq": n,
                    "snapshot": snapshot.data,
                    "snapshot_codec": snapshot.codec,
                    "snapshot_sha256": hashlib.sha256(snapshot.data).hexdigest(),
                },
            )
        )
    with engine.begin() as connection:
        connection.execute(
            insert(tables["schema_info"]).values(key="schema_version", value=str(version))
        )
        for name in ("documents", "datasets", "validation_runs", "issues", "audit_events"):
            if rows[name]:
                connection.execute(insert(tables[name]), rows[name])
            if "seq" in tables[name].c:
                connection.execute(
                    insert(tables["sequence_counters"]).values(name=name, value=len(rows[name]))
                )
