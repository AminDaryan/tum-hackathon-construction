"""Table definitions of the SQL adapter (SQLAlchemy Core, portable SQLite/PostgreSQL types).

Each record is stored whole as a JSON ``payload`` (datasets: a compressed snapshot) plus the
indexed columns projected by :mod:`app.repositories.records`; the payload is the source of
truth and the columns are rewritten from it on every write.

``seq`` is a monotonically increasing insertion sequence (allocated from ``sequence_counters``,
which works the same on SQLite and PostgreSQL without making ``seq`` the primary key) so that
"newest first" listings and the audit trail stay deterministic when timestamps are identical.
Bump :data:`SCHEMA_VERSION` whenever these tables change and add the step that upgrades the
previous version to :mod:`app.repositories.sql.migrations`; a database of an older version is
upgraded (automatically or with ``python -m app.cli db upgrade``), a newer one is refused.

Version history: 1, the first layout; 2, issues gained ``document_id`` (carrying review
decisions within a document), ``version`` (compare-and-set updates, ADR 0005),
``reviewed_at`` and ``seq`` (which reviewed issue is the most recent one); 3, datasets gained
``table_count`` and ``row_count`` (document listings read them instead of decoding snapshots);
4, issues gained ``rule_id`` and the run-order index follows the deterministic issue order
(detector, rule, fingerprint and insertion sequence after the source position); 5, the
``explanations`` table (language model explanations of a run's problems); 6, projects; 7, user
accounts; 8, reviewer sessions, finding comments and mention notifications; 9, finding tasks
and the kind of each finding-thread entry; 10, the review assistant's reply attachments; 11,
clarifications; 12, optional finding-task due dates; 13, clarifications gained the email they
were drafted as (``issue_id``, ``recipient``, ``subject``, ``body``) and ``sent_at``.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
)

SCHEMA_VERSION = 13
SCHEMA_VERSION_KEY = "schema_version"

# Deterministic constraint names on every backend (indexes are named explicitly below so that
# composite names stay within PostgreSQL's 63-character identifier limit).
metadata = MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
    }
)

schema_info = Table(
    "schema_info",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)

projects = Table(
    "projects",
    metadata,
    Column("project_id", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("user_id", String, primary_key=True),
    Column("token_digest", String, nullable=True),
    Column("payload", JSON, nullable=False),
    Index("ix_users_token_digest", "token_digest", unique=True),
)

# Reviewer names are shared identities behind the site gate, not authentication accounts.
reviewers = Table(
    "reviewers",
    metadata,
    Column("handle", String, primary_key=True),
    Column("name", String, nullable=False),
)
reviewer_sessions = Table(
    "reviewer_sessions",
    metadata,
    Column("token_hash", String, primary_key=True),
    Column("handle", String, ForeignKey("reviewers.handle"), nullable=False),
    Column("expires_at", String, nullable=False),
)
finding_comments = Table(
    "finding_comments",
    metadata,
    Column("comment_id", String, primary_key=True),
    Column("issue_id", String, ForeignKey("issues.issue_id"), nullable=False),
    Column("author", String, ForeignKey("reviewers.handle"), nullable=False),
    Column("kind", String, nullable=False),  # "comment", or "activity" for a task change
    Column("body", String, nullable=False),
    Column("created_at", String, nullable=False),
    Index("ix_finding_comments_issue", "issue_id", "created_at", "comment_id"),
)
mention_notifications = Table(
    "mention_notifications",
    metadata,
    Column("notification_id", String, primary_key=True),
    Column("recipient", String, ForeignKey("reviewers.handle"), nullable=False),
    Column("comment_id", String, ForeignKey("finding_comments.comment_id"), nullable=False),
    Column("is_read", Integer, nullable=False),
    Index("ix_mentions_recipient", "recipient", "is_read"),
)
finding_tasks = Table(
    "finding_tasks",
    metadata,
    Column("issue_id", String, ForeignKey("issues.issue_id"), primary_key=True),
    Column("assignee", String, ForeignKey("reviewers.handle")),
    Column("status", String, nullable=False),
    Column("task_type", String),
    Column("due_date", String),  # ISO calendar date, not a timestamp
    Column("updated_by", String, ForeignKey("reviewers.handle"), nullable=False),
    Column("updated_at", String, nullable=False),
)
# What Desvio, the review assistant, attached to one of its replies: an email draft and next
# steps (JSON), shown under the reply.
assistant_replies = Table(
    "assistant_replies",
    metadata,
    Column("comment_id", String, ForeignKey("finding_comments.comment_id"), primary_key=True),
    Column("payload", JSON, nullable=False),
)

# A project's questions to settle before the bid decision, each raised on a reminder of a risk
# report. Reports are computed on request and never stored, so ``risk_id`` references no table;
# ``tier`` is the reminder's review priority when the clarification was raised.
clarifications = Table(
    "clarifications",
    metadata,
    Column("clarification_id", String, primary_key=True),
    Column("project_id", String, ForeignKey("projects.project_id"), nullable=False),
    Column("document_id", String, nullable=False),  # the bill the reminder is in
    Column("risk_id", String, nullable=False),
    Column("tier", String, nullable=False),
    Column("kind", String, nullable=False),  # who is asked
    Column("title", String, nullable=False),
    Column("status", String, nullable=False),
    Column("due", String),  # the day the answer is needed (ISO date), when one is set
    Column("phase", String, nullable=False),
    Column("answer", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    # The email it was drafted as, when it was: the finding it is about, to whom, its text, and
    # when someone handed it to their email app or copied it (Amp cannot know it went out).
    Column("issue_id", String),
    Column("recipient", String),
    Column("subject", String),
    Column("body", String),
    Column("sent_at", String),
    Index("ix_clarifications_project", "project_id", "created_at", "clarification_id"),
)

sequence_counters = Table(
    "sequence_counters",
    metadata,
    Column("name", String, primary_key=True),  # the table whose ``seq`` it allocates
    Column("value", Integer, nullable=False),  # the last value handed out
)

documents = Table(
    "documents",
    metadata,
    Column("document_id", String, primary_key=True),
    Column("seq", Integer, nullable=False),
    Column("uploaded_at", DateTime(timezone=True), nullable=False),
    Column("processing_status", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Index("ix_documents_listing", "uploaded_at", "seq"),
)

datasets = Table(
    "datasets",
    metadata,
    Column("dataset_id", String, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("document_id", String, ForeignKey("documents.document_id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("profile_id", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("table_count", Integer, nullable=False),
    Column("row_count", Integer, nullable=False),
    Column("snapshot", LargeBinary, nullable=False),  # see app.repositories.snapshot_codec
    Column("snapshot_codec", String, nullable=False),  # e.g. "json+zlib/1"
    Column("snapshot_sha256", String, nullable=False),  # of ``snapshot``; validates the cache
    Index("ix_datasets_document", "document_id", "created_at", "seq"),
)

validation_runs = Table(
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

issues = Table(
    "issues",
    metadata,
    Column("issue_id", String, primary_key=True),
    Column("seq", Integer, nullable=False),
    Column("validation_run_id", String, ForeignKey("validation_runs.run_id"), nullable=False),
    Column("document_id", String, nullable=False),
    Column("dataset_id", String, nullable=False),
    Column("dataset_revision", Integer, nullable=False),
    Column("table_id", String, nullable=True),
    Column("row_id", String, nullable=True),
    Column("detector_id", String, nullable=False),
    Column("rule_id", String, nullable=False),
    Column("issue_category", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("severity_rank", Integer, nullable=False),
    Column("evidence_class", String, nullable=False),  # as assigned by the detector
    Column("effective_evidence_class", String, nullable=False),  # after review decisions
    Column("review_status", String, nullable=False),
    Column("reviewed_at", DateTime(timezone=True), nullable=True),
    # Compare-and-set key of updates; matched together with the primary key, so it needs no
    # index of its own.
    Column("version", Integer, nullable=False),
    Column("sort_sheet", Integer, nullable=True),
    Column("sort_row", Integer, nullable=True),
    Column("sort_column", Integer, nullable=True),
    Column("fingerprint", String, nullable=False),
    Column("payload", JSON, nullable=False),
    # Every filter is applied within a run (or a dataset), so the composite indexes lead with
    # it; the run-leading ones also serve as the index of the foreign key. The run-order index
    # holds the stored columns of ISSUE_ORDER (app.repositories.querying) in the same sequence;
    # its first term, style_finding, is derived from detector_id and rule_id.
    Index(
        "ix_issues_run_order",
        "validation_run_id",
        "severity_rank",
        "sort_sheet",
        "sort_row",
        "sort_column",
        "detector_id",
        "rule_id",
        "fingerprint",
        "seq",
        "issue_id",
    ),
    Index("ix_issues_run_severity", "validation_run_id", "severity"),
    Index("ix_issues_run_evidence", "validation_run_id", "effective_evidence_class"),
    Index("ix_issues_run_review", "validation_run_id", "review_status"),
    Index("ix_issues_run_detector", "validation_run_id", "detector_id"),
    Index("ix_issues_run_category", "validation_run_id", "issue_category"),
    Index("ix_issues_run_location", "validation_run_id", "table_id", "row_id"),
    Index("ix_issues_dataset", "dataset_id", "dataset_revision"),
    # Review decisions are carried forward within a document by fingerprint.
    Index("ix_issues_document_fingerprint", "document_id", "fingerprint"),
)

audit_events = Table(
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

# Language model explanations of a run's problems (problems are computed, not stored, so
# ``problem_id`` references none of these tables).
explanations = Table(
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

# Tables whose ``seq`` is allocated from ``sequence_counters`` (one counter row per table).
SEQUENCED_TABLES: tuple[Table, ...] = tuple(
    table for table in metadata.sorted_tables if "seq" in table.c
)
