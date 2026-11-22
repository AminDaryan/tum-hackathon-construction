export const meta = {
  name: 'phase1-build-persistence',
  description: 'Build the in-memory and SQLAlchemy Core repositories (SQLite now, PostgreSQL-ready) with contract tests',
  phases: [{ title: 'Build', detail: 'repositories, unit of work, dataset snapshot codec and cache' }],
}

const ROOT = '/home/user/tabular-integrity-workbench'
const PROMPT = `You are a senior Python engineer on the "Tabular Integrity Workbench" hackathon project (Phase 1: foundation). Repository: ${ROOT} (git repo; do NOT run any git command that changes state: no commit, add, checkout, stash, reset).
Read first: ${ROOT}/docs/product/brief.md (requirements), ${ROOT}/docs/architecture/overview.md, ${ROOT}/docs/architecture/data-model.md, ${ROOT}/docs/api/rest-api.md (the REST API that services will build on your repositories, especially the issue filters and ordering), and the persistence ports in ${ROOT}/backend/app/repositories/base.py.

Other engineers are editing other parts of the repository at the same time. YOUR OWNERSHIP: new modules under ${ROOT}/backend/app/repositories/ (everything except base.py, which is a shared contract you must not edit; you may add exports to repositories/__init__.py and repositories/sql/__init__.py) and new tests under ${ROOT}/backend/tests/unit/repositories/ (create the package with an __init__.py). Do not touch any other file. If base.py or a model needs to change, do not edit it: describe the change in your report.
Environment: venv at ${ROOT}/backend/.venv with SQLAlchemy 2.x installed (no new dependencies). Run ONLY your own tests: cd ${ROOT}/backend && .venv/bin/python -m pytest -q tests/unit/repositories . Run ruff only on your own files: .venv/bin/ruff format <your files> and .venv/bin/ruff check <your files> (never on the whole tree, other people's files are in flight).

TASK: implement both persistence adapters behind the protocols in repositories/base.py.

1. repositories/memory.py: InMemoryDatabase holding dicts, InMemoryUnitOfWork (copy-on-enter snapshot of the dicts, commit on clean exit, restore on exception; models are immutable so shallow copies suffice) and a factory callable satisfying UnitOfWorkFactory. Same observable behaviour as the SQL adapter (ordering, filters, paging, counts).

2. repositories/sql/: SQLAlchemy Core (not ORM), portable SQLite/PostgreSQL types only (String, Integer, Float, Boolean, DateTime(timezone=True), LargeBinary, Text/JSON).
   - A Database class: create_engine from a URL; for SQLite set check_same_thread=False, enable PRAGMA foreign_keys=ON, journal_mode=WAL (file databases only) and busy_timeout via a connect event; create parent directories for file paths; create_all for the schema plus a schema_info table storing schema_version=1 (refuse to start with a clear error if an existing database has another version). In-memory SQLite (for tests) must work with StaticPool.
   - Tables: documents (document_id PK, uploaded_at, processing_status, payload JSON), datasets (dataset_id + revision composite PK, document_id FK, profile_id, created_at, snapshot LargeBinary = zlib-compressed canonical JSON of Dataset.model_dump(mode="json"), snapshot_codec string e.g. "json+zlib/1"), validation_runs (run_id PK, dataset_id, dataset_revision, status, started_at, finished_at, payload JSON), issues (issue_id PK, validation_run_id FK indexed, dataset_id, dataset_revision, table_id, row_id, detector_id, issue_category, severity, severity_rank int, evidence_class, effective_evidence_class, review_status, sort_sheet int nullable, sort_row int nullable, sort_column int nullable, fingerprint indexed, payload JSON) with composite indexes supporting the filters, audit_events (event_id PK, occurred_at, entity_type + entity_id indexed, action, payload JSON). Keep a monotonically increasing insertion sequence where needed so "newest first" and audit ordering are deterministic even with identical timestamps.
   - Repositories implementing every protocol method. Serialization via model_dump(mode="json") / model_validate (Decimals travel as strings; the FrozenModel base drops computed fields on load). effective_evidence_class and review_status columns must be recomputed on update(). Issue ordering for query(): severity_rank DESC, sort_sheet ASC (nulls last), sort_row ASC (nulls first, so table-level issues lead their table), sort_column ASC (nulls first), issue_id ASC; sort keys come from the first affected cell's source (sheet_index, row_number, column_number). documents.list newest first by uploaded_at then insertion order; runs list_for_dataset newest first; latest_for_dataset = newest started run; audit list_for_entity oldest first.
   - IssueQuery semantics exactly as documented: AND across filters, OR within one filter, empty = no filter, evidence_classes matches effective_evidence_class. counts() returns IssueCounts for the same filters (effective evidence class). Paging: offset/limit with total count of all matches.
   - A dataset snapshot codec module (encode/decode with a codec version tag, refuse unknown codecs) shared by the SQL adapter, and a small thread-safe LRU cache (default 8 entries, configurable) keyed by (dataset_id, revision) so repeated reads of a large dataset do not decompress and re-validate it each time (get() with revision=None must still resolve the latest revision from the database first). Cached objects are immutable models, so sharing them is safe.
   - SqlUnitOfWork: one connection and one transaction per "with" block, commit on success, rollback on exception, repositories bound to that connection; a factory callable satisfying UnitOfWorkFactory. Must be safe to use from FastAPI's thread pool (one unit of work per request, never shared).

3. Tests (pytest, parametrized over BOTH adapters with a fixture, SQL using in-memory SQLite plus at least one file-based test in tmp_path): add/get/update/list for every repository; paging totals; every IssueQuery filter alone and combined (OR within, AND across); effective_evidence_class filter and counts after a review update (review_status confirmed_error makes it human_confirmed_error); ordering rules above including table-level issues; iter_all; audit ordering; dataset revisions (latest when revision is None, specific revision, list_for_document); snapshot round trip equality (loaded Dataset == original, including Decimal values and source locations); rollback on exception leaves nothing behind; the LRU cache serves the second read without decoding (prove it with a counter or monkeypatch); schema version mismatch is refused; a dataset of about 20,000 cells round-trips in well under a few seconds. Build datasets with ${ROOT}/backend/tests/support/builders.py (DatasetBuilder, make_context) and the boq_profile fixture in tests/conftest.py, and issues through the IssueFactory available on the context (context.issues.create(...) with a DetectorSpec you define in the test) or by constructing ValidationIssue directly. Tests must be fast.

Quality bar (Part M of the brief): small single-responsibility modules, docstrings, no duplicated logic, no silent failure, honest reporting; never silently skip a failing test.
Final answer: a concise report with files created/changed, what was implemented, exact test commands and results (pass/fail counts), known limitations, and any contract changes you recommend for repositories/base.py.`

phase('Build')
const result = await agent(PROMPT, {
  label: 'build:persistence',
  phase: 'Build',
  schema: {
    type: 'object',
    properties: {
      report: { type: 'string' },
      tests_passed: { type: 'boolean' },
      contract_change_requests: { type: 'array', items: { type: 'string' } },
    },
    required: ['report', 'tests_passed', 'contract_change_requests'],
  },
})
return result
