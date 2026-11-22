"""Schema migrations: a database of every earlier version, holding records, is upgraded in one
transaction and its records read back through the repositories; the command line reports and
applies upgrades; newer, unreadable and refused databases are left untouched."""

from __future__ import annotations

import io
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, inspect, make_url, select

from app.cli import main
from app.core.config import Settings
from app.models.audit import AuditEvent, EntityType
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.issue import FinancialImpact, ReviewStatus, Severity, ValidationIssue
from app.models.profile import DomainProfile
from app.models.run import ValidationRun
from app.repositories.base import DatasetCounts, IssueQuery
from app.repositories.errors import PersistenceError, SchemaVersionError
from app.repositories.sql import SCHEMA_VERSION, Database, SqlUnitOfWorkFactory, migrations
from app.repositories.sql import schema as sql_schema
from app.repositories.sql.database import (
    UPGRADE_COMMAND,
    schema_status,
    upgrades_automatically,
)
from tests.unit.repositories.legacy_schemas import (
    LEGACY_VERSIONS,
    legacy_issue_payload,
    write_legacy_database,
)
from tests.unit.repositories.postgres import POSTGRESQL, backends, fresh_postgres_url
from tests.unit.repositories.samples import (
    Boom,
    build_dataset,
    cell_at,
    make_document,
    make_event,
    make_explanation,
    make_issue,
    make_run,
    minutes,
)


@dataclass(frozen=True)
class Records:
    document: Document
    dataset: Dataset
    run: ValidationRun
    issues: tuple[ValidationIssue, ...]  # as stored by the current build
    event: AuditEvent


def _records(profile: DomainProfile) -> Records:
    impact = FinancialImpact(amount=Decimal("12.50"), currency="EUR", basis="line total")
    reviewed = make_issue(
        "iss_000002", severity=Severity.MEDIUM, cells=[cell_at(0, 4, 1)], fingerprint="fp_2"
    ).with_review(ReviewStatus.FALSE_POSITIVE, "Geprüft: korrekt", at=minutes(5))
    return Records(
        document=make_document(),
        dataset=build_dataset(profile),
        run=make_run(issue_count=3),
        issues=(
            make_issue(
                "iss_000001",
                severity=Severity.HIGH,
                cells=[cell_at(0, 3, 2)],
                rule_id="quantity_minimum",
                fingerprint="fp_1",
            ),
            reviewed,
            make_issue(
                "iss_000003", severity=Severity.HIGH, cells=[cell_at(0, 3, 2)], fingerprint="fp_3"
            ).evolve(estimated_financial_impact=impact),
        ),
        event=make_event("aud_000001", entity_id="iss_000002"),
    )


def _write(url: str, version: int, records: Records) -> None:
    payloads = {}
    if version < 2:  # version 1 allowed an impact without a currency
        payload = legacy_issue_payload(records.issues[2], version)
        payload["estimated_financial_impact"]["currency"] = None
        payloads["iss_000003"] = payload
    engine = create_engine(url)
    try:
        write_legacy_database(
            engine,
            version,
            documents=[records.document],
            datasets=[records.dataset],
            runs=[records.run],
            issues=records.issues,
            events=[records.event],
            issue_payloads=payloads,
        )
    finally:
        engine.dispose()


def _as_upgraded(records: Records, version: int) -> list[ValidationIssue]:
    """The issues as the current build reads them after upgrading from ``version``."""
    first, reviewed, with_impact = records.issues
    if version < 2:
        reviewed = reviewed.evolve(version=1)  # version 1 recorded no versions: the first one
        with_impact = with_impact.evolve(estimated_financial_impact=None)  # no currency
    return [with_impact, first, reviewed]  # same place: rule "default" before "quantity_minimum"


def _layout(connection: Connection) -> dict[str, object]:
    """Columns (nullability), primary key, foreign keys and indexes of every table."""
    inspector = inspect(connection)
    layout: dict[str, object] = {}
    for name in sorted(inspector.get_table_names()):
        layout[name] = (
            {column["name"]: column["nullable"] for column in inspector.get_columns(name)},
            tuple(inspector.get_pk_constraint(name)["constrained_columns"]),
            sorted(
                (tuple(fk["constrained_columns"]), fk["referred_table"])
                for fk in inspector.get_foreign_keys(name)
            ),
            {index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes(name)},
        )
    return layout


def _expected_layout() -> dict[str, object]:
    return {
        table.name: (
            {column.name: column.nullable for column in table.columns},
            tuple(table.primary_key.columns.keys()),
            sorted(
                ((fk.parent.name,), fk.column.table.name)
                for fk in table.foreign_keys  # every foreign key has one column
            ),
            {index.name: tuple(c.name for c in index.columns) for index in table.indexes},
        )
        for table in sql_schema.metadata.sorted_tables
    }


@pytest.fixture
def sqlite_legacy_url(file_database_url: str) -> str:
    Path(file_database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True)
    return file_database_url


@pytest.fixture(params=backends("sqlite"))
def legacy_url(request: pytest.FixtureRequest, file_database_url: str) -> str:
    if request.param == POSTGRESQL:
        return fresh_postgres_url()
    Path(file_database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True)
    return file_database_url


def test_every_earlier_version_has_one_step_in_order() -> None:
    assert [step.from_version for step in migrations.MIGRATIONS] == list(range(1, SCHEMA_VERSION))
    assert migrations.pending(SCHEMA_VERSION) == ()
    assert [step.to_version for step in migrations.pending(2)] == list(range(3, SCHEMA_VERSION + 1))
    for unknown in (0, SCHEMA_VERSION + 1):
        with pytest.raises(PersistenceError, match="cannot upgrade"):
            migrations.pending(unknown)


@pytest.mark.parametrize("version", LEGACY_VERSIONS)
def test_an_older_database_is_upgraded_and_reads_back(
    legacy_url: str, boq_profile: DomainProfile, version: int
) -> None:
    records = _records(boq_profile)
    _write(legacy_url, version, records)
    assert schema_status(legacy_url).stored == str(version)

    with Database(legacy_url, auto_upgrade="always", backup_before_upgrade=False) as database:
        applied = [step.from_version for step in database.migrations_applied]
        assert applied == list(range(version, SCHEMA_VERSION))
        factory = SqlUnitOfWorkFactory(database)
        with factory() as uow:
            assert uow.documents.get("doc_000001") == records.document
            assert uow.documents.list().total == 1
            assert uow.datasets.get("ds_000001") == records.dataset
            assert uow.datasets.latest_counts_for_document("doc_000001") == DatasetCounts.of(
                records.dataset
            )
            assert uow.runs.get("run_000001") == records.run
            expected = _as_upgraded(records, version)
            assert uow.issues.query(IssueQuery(run_id="run_000001")).items == expected
            assert uow.issues.reviewed_by_fingerprint("doc_000001", ["fp_2"]) == {
                "fp_2": expected[2]
            }
            assert uow.audit.list_for_entity(EntityType.ISSUE, "iss_000002") == [records.event]
        with factory() as uow:  # writes continue: compare-and-set and insertion sequences
            reviewed = expected[2]
            again = reviewed.with_review(ReviewStatus.PENDING_REVIEW, None, at=minutes(9))
            uow.issues.update(again, expected_version=reviewed.version)
            uow.issues.add_many([make_issue("iss_000004", cells=[cell_at(0, 9, 1)])])
            uow.documents.add(make_document("doc_000002"))
            uow.explanations.add(make_explanation())  # the table of version 5
        with factory() as uow:
            assert uow.explanations.list_for_run("run_000001") == [make_explanation()]
        with database.connect() as connection:
            assert _layout(connection) == _expected_layout()
            seqs = dict(
                connection.execute(
                    select(sql_schema.issues.c.issue_id, sql_schema.issues.c.seq)
                ).all()
            )
            if not database.is_sqlite:  # SQLite keeps the fill defaults (see migrations.py)
                for table in sql_schema.metadata.sorted_tables:
                    defaults = [c["default"] for c in inspect(connection).get_columns(table.name)]
                    assert defaults == [None] * len(defaults), table.name
    assert sorted(seqs.values()) == [1, 2, 3, 4] and seqs["iss_000004"] == 4
    assert schema_status(legacy_url).up_to_date


def test_sqlite_files_are_copied_before_an_automatic_upgrade(
    sqlite_legacy_url: str, boq_profile: DomainProfile
) -> None:
    legacy_url = sqlite_legacy_url
    _write(legacy_url, 3, _records(boq_profile))
    path = Path(legacy_url.removeprefix("sqlite:///"))
    Database(legacy_url).dispose()  # the default policy upgrades SQLite files
    [copy] = path.parent.glob(f"{path.name}.schema-v3-*.bak")
    with closing(sqlite3.connect(copy)) as backup:
        assert backup.execute("SELECT value FROM schema_info").fetchall() == [("3",)]
        assert "rule_id" not in {row[1] for row in backup.execute("PRAGMA table_info(issues)")}
    assert schema_status(legacy_url).up_to_date


def test_automatic_upgrades_can_be_turned_off(
    legacy_url: str, boq_profile: DomainProfile, tmp_path: Path
) -> None:
    _write(legacy_url, 2, _records(boq_profile))
    with pytest.raises(SchemaVersionError, match="written by an older build") as refused:
        Database(legacy_url, auto_upgrade="never")
    assert UPGRADE_COMMAND in refused.value.message
    assert refused.value.details == {"found": "2", "expected": SCHEMA_VERSION}
    if not legacy_url.startswith("sqlite"):  # the default policy leaves PostgreSQL alone
        with pytest.raises(SchemaVersionError, match=UPGRADE_COMMAND):
            Database(legacy_url)
    assert schema_status(legacy_url).stored == "2"
    assert list(tmp_path.rglob("*.bak")) == []


def test_the_default_policy_upgrades_only_sqlite_at_start_up() -> None:
    assert upgrades_automatically("sqlite", is_sqlite=True)
    assert not upgrades_automatically("sqlite", is_sqlite=False)
    assert upgrades_automatically("always", is_sqlite=False)
    assert not upgrades_automatically("never", is_sqlite=True)
    assert Settings().persistence.auto_upgrade == "sqlite"


def test_a_failing_step_leaves_the_database_as_it_was(
    legacy_url: str, boq_profile: DomainProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(legacy_url, 2, _records(boq_profile))
    *earlier, last = migrations.MIGRATIONS

    def fails_after_its_changes(apply: Callable[[Connection], None]) -> Callable:
        def step(connection: Connection) -> None:
            apply(connection)
            raise Boom("the upgrade failed half-way")

        return step

    # The steps from version 2 apply their changes, then the last one fails after its own.
    broken = migrations.Migration(
        last.from_version, last.summary, fails_after_its_changes(last.apply)
    )
    monkeypatch.setattr(migrations, "MIGRATIONS", (*earlier, broken))
    with pytest.raises(Boom):
        Database(legacy_url, auto_upgrade="always", backup_before_upgrade=False)
    assert schema_status(legacy_url).stored == "2"
    engine = create_engine(legacy_url)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            datasets = {column["name"] for column in inspect(connection).get_columns("datasets")}
            issues = {column["name"] for column in inspect(connection).get_columns("issues")}
    finally:
        engine.dispose()
    assert [step.from_version for step in earlier[1:]] == [
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
    ] and last.from_version == 12
    assert "table_count" not in datasets and "rule_id" not in issues
    assert "explanations" not in tables
    assert "projects" not in tables and "users" not in tables
    assert "finding_comments" not in tables and "assistant_replies" not in tables
    assert "clarifications" not in tables


def test_a_schema_8_discussion_keeps_its_comments_and_gains_tasks(sqlite_legacy_url: str) -> None:
    # Schema 8 as the multiplayer release wrote it: comments without a kind, no task table.
    Database(sqlite_legacy_url).dispose()
    path = sqlite_legacy_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as legacy, legacy:
        legacy.execute("DROP TABLE clarifications")  # of schema 11
        legacy.execute("DROP TABLE assistant_replies")  # of schema 10
        legacy.execute("DROP TABLE finding_tasks")
        legacy.execute("ALTER TABLE finding_comments DROP COLUMN kind")
        legacy.execute(
            "INSERT INTO finding_comments (comment_id, issue_id, author, body, created_at) "
            "VALUES ('c1', 'i1', 'larissa', 'Check row 43 @johan', '2026-11-21T17:00:00Z')"
        )
        legacy.execute("UPDATE schema_info SET value = '8' WHERE key = 'schema_version'")

    Database(sqlite_legacy_url).dispose()  # the default policy upgrades SQLite files

    assert schema_status(sqlite_legacy_url).up_to_date
    with closing(sqlite3.connect(path)) as upgraded:
        assert upgraded.execute(
            "SELECT comment_id, kind, body FROM finding_comments"
        ).fetchall() == [("c1", "comment", "Check row 43 @johan")]
        columns = {row[1] for row in upgraded.execute("PRAGMA table_info(finding_tasks)")}
    assert columns == {
        "issue_id",
        "assignee",
        "status",
        "task_type",
        "due_date",
        "updated_by",
        "updated_at",
    }


def test_a_schema_10_database_keeps_its_projects_and_gains_clarifications(
    sqlite_legacy_url: str,
) -> None:
    # Schema 10 as the review-assistant release wrote it: projects, no clarifications table.
    Database(sqlite_legacy_url).dispose()
    path = sqlite_legacy_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as legacy, legacy:
        legacy.execute("DROP TABLE clarifications")
        legacy.execute("ALTER TABLE finding_tasks DROP COLUMN due_date")
        legacy.execute("INSERT INTO projects (project_id, payload) VALUES ('prj_1', '{}')")
        legacy.execute("UPDATE schema_info SET value = '10' WHERE key = 'schema_version'")

    with Database(sqlite_legacy_url) as database:  # the default policy upgrades SQLite files
        assert [step.from_version for step in database.migrations_applied] == [10, 11, 12]
        with database.connect() as connection:
            assert _layout(connection) == _expected_layout()

    with closing(sqlite3.connect(path)) as upgraded:
        assert upgraded.execute("SELECT project_id FROM projects").fetchall() == [("prj_1",)]
        assert upgraded.execute("SELECT count(*) FROM clarifications").fetchone() == (0,)


def test_schema_11_tasks_keep_their_fields_and_gain_nullable_due_dates(
    legacy_url: str,
    boq_profile: DomainProfile,
) -> None:
    _write(legacy_url, 6, _records(boq_profile))
    Database(legacy_url, auto_upgrade="always").dispose()
    engine = create_engine(legacy_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE finding_tasks DROP COLUMN due_date")
            for name in ("issue_id", "recipient", "subject", "body", "sent_at"):
                connection.exec_driver_sql(f"ALTER TABLE clarifications DROP COLUMN {name}")
            connection.execute(sql_schema.reviewers.insert().values(handle="amin", name="Amin"))
            connection.exec_driver_sql(
                "INSERT INTO finding_tasks "
                "(issue_id, assignee, status, task_type, updated_by, updated_at) VALUES "
                "('iss_000001', 'amin', 'waiting', 'ask_client', 'amin', '2026-11-21T12:00:00Z')"
            )
            connection.exec_driver_sql("UPDATE schema_info SET value = '11'")
        with Database(legacy_url, auto_upgrade="always") as database:
            assert [step.from_version for step in database.migrations_applied] == [11, 12]
            with database.connect() as connection:
                assert _layout(connection) == _expected_layout()
                task = connection.execute(select(sql_schema.finding_tasks)).mappings().one()
                assert (task["assignee"], task["status"], task["task_type"], task["due_date"]) == (
                    "amin",
                    "waiting",
                    "ask_client",
                    None,
                )
                connection.execute(sql_schema.finding_tasks.update().values(due_date="2026-12-03"))
                assert (
                    connection.scalar(select(sql_schema.finding_tasks.c.due_date)) == "2026-12-03"
                )
    finally:
        engine.dispose()


def test_a_schema_12_clarification_is_kept_with_no_email(sqlite_legacy_url: str) -> None:
    # Schema 12 as the finding-task due-date release wrote it: no email columns.
    Database(sqlite_legacy_url).dispose()
    path = sqlite_legacy_url.removeprefix("sqlite:///")
    email = ("issue_id", "recipient", "subject", "body", "sent_at")
    with closing(sqlite3.connect(path)) as legacy, legacy:
        for name in email:
            legacy.execute(f"ALTER TABLE clarifications DROP COLUMN {name}")
        legacy.execute("INSERT INTO projects (project_id, payload) VALUES ('prj_1', '{}')")
        legacy.execute(
            "INSERT INTO clarifications (clarification_id, project_id, document_id, risk_id, "
            "tier, kind, title, status, phase, answer, created_at, updated_at) VALUES ('clr_1', "
            "'prj_1', 'doc_1', 'risk_1', 'high', 'bidder_question', 'Rock?', 'sent', 'bid', '', "
            "'2026-11-20T09:00:00Z', '2026-11-20T09:00:00Z')"
        )
        legacy.execute("UPDATE schema_info SET value = '12' WHERE key = 'schema_version'")

    with Database(sqlite_legacy_url) as database:
        assert [step.from_version for step in database.migrations_applied] == [12]
        with database.connect() as connection:
            assert _layout(connection) == _expected_layout()

    with closing(sqlite3.connect(path)) as upgraded:
        assert upgraded.execute(
            f"SELECT title, status, {', '.join(email)} FROM clarifications"
        ).fetchall() == [("Rock?", "sent", None, None, None, None, None)]


def test_the_command_line_reports_and_applies_pending_migrations(
    legacy_url: str, boq_profile: DomainProfile, tmp_path: Path
) -> None:
    _write(legacy_url, 1, _records(boq_profile))
    settings = Settings(data_dir=tmp_path, database_url=legacy_url)

    def run(*args: str) -> tuple[int, str]:
        out = io.StringIO()
        return main(["db", *args], settings=settings, out=out, err=out), out.getvalue()

    status, text = run("current")
    assert status == 0
    assert f"Schema version: 1 (this build: {SCHEMA_VERSION})" in text
    assert "12 migration(s) pending" in text and "3 -> 4: issues gain rule_id" in text
    assert "4 -> 5: the explanations table" in text
    assert run("current", "--check")[0] == 1
    status, text = run("upgrade", "--no-backup")
    assert status == 0
    assert "Applied 1 -> 2" in text and f"Now at schema version {SCHEMA_VERSION}." in text
    up_to_date = f"Schema version: {SCHEMA_VERSION} (this build: {SCHEMA_VERSION})\nUp to date.\n"
    shown = make_url(legacy_url).render_as_string(hide_password=True)  # never the password
    assert run("current", "--check") == (0, f"Database: {shown}\n{up_to_date}")
    if password := make_url(legacy_url).password:
        assert f":{password}@" not in text and "***" in text
    assert "nothing to upgrade" in run("upgrade")[1]
    assert list(tmp_path.rglob("*.bak")) == []


def test_db_current_creates_nothing_and_db_upgrade_creates_the_schema(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'new.sqlite3').as_posix()}"
    out = io.StringIO()
    assert main(["db", "current", "--database-url", url], settings=Settings(), out=out) == 0
    assert "No workbench schema yet" in out.getvalue()
    assert not (tmp_path / "new.sqlite3").exists()
    out = io.StringIO()
    assert main(["db", "upgrade", "--database-url", url], settings=Settings(), out=out) == 0
    assert f"Created the workbench schema, version {SCHEMA_VERSION}." in out.getvalue()
    assert schema_status(url).up_to_date


def test_the_command_line_refuses_a_newer_database(file_database_url: str) -> None:
    Database(file_database_url).dispose()
    with closing(sqlite3.connect(file_database_url.removeprefix("sqlite:///"))) as connection:
        connection.execute(f"UPDATE schema_info SET value = '{SCHEMA_VERSION + 1}'")
        connection.commit()
    for action in ("current", "upgrade"):
        out, err = io.StringIO(), io.StringIO()
        arguments = ["db", action, "--database-url", file_database_url]
        assert main(arguments, settings=Settings(), out=out, err=err) == 2
        assert "newer build" in out.getvalue() + err.getvalue()
    assert schema_status(file_database_url).stored == str(SCHEMA_VERSION + 1)


def test_the_command_line_refuses_a_database_it_cannot_open(tmp_path: Path) -> None:
    # Exit status 2 with a message, never a traceback: its exit status 1 would tell a script
    # using --check that an upgrade is pending.
    damaged = tmp_path / "damaged.sqlite3"
    damaged.write_bytes(b"not a database " * 100)
    sqlite_url = f"sqlite:///{damaged.as_posix()}"
    unreachable = "postgresql+pg8000://twb:s3cret@127.0.0.1:1/twb"  # no server (or no driver)
    for url, arguments in (
        (sqlite_url, ["current", "--check"]),
        (sqlite_url, ["upgrade"]),
        (unreachable, ["current", "--check"]),
        (unreachable, ["upgrade"]),
    ):
        out, err = io.StringIO(), io.StringIO()
        command = ["db", *arguments, "--database-url", url]
        assert main(command, settings=Settings(), out=out, err=err) == 2, command
        assert "error: cannot use the database" in err.getvalue()
        assert "s3cret" not in out.getvalue() + err.getvalue()
    assert damaged.read_bytes() == b"not a database " * 100
    assert [path.name for path in tmp_path.iterdir()] == ["damaged.sqlite3"]  # no copy made
