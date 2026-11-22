# Desvio

Desvio (repository: tabular-integrity-workbench) is a local workbench that checks tabular documents for errors and lets a reviewer confirm, dismiss
or correct findings in-app, starting with construction Bills of Quantities (English BoQs and German
Leistungsverzeichnisse). It reads XLSX and CSV files, GAEB bills (DA XML 3.1–3.3 and GAEB 90),
printed bills in PDF (scans read by OCR) and Word documents (.docx: tables and item lists), turns them into a canonical table with every cell traced to its source
(down to the PDF page and position), exports it to Excel, runs deterministic checks
(arithmetic, totals and tax, units, duplicates, required values, references, currencies) and
explains each finding with its evidence. Amounts are exact decimals; formulas and macros in documents are never executed; the
checks use no paid service or LLM. An optional assistant, and a Claude review of one bill that a reviewer starts, call a hosted model API only when their key is set ([`docs/deployment.md`](docs/deployment.md#claude-bill-review)); the app works without them. Requirements: [`docs/product/brief.md`](docs/product/brief.md).

## Status

Phase 1 and its first round of fixes are merged into `main` (pull request #3). Working and tested: ingestion with
security checks, normalization, the 14 detectors, the REST API with optional sign-in and
background runs, exports (CSV, ZIP, JSON, XLSX and questions markdown), in-app correction revisions and review-finish workflow, versioned database migrations, a synthetic
benchmark, the web interface (served by the backend in the container image) and a browser
end-to-end test. Since then: older GAEB formats, PDF bills with OCR for scans, an Excel export,
and a tender review that every run on a bill now includes. The review looks for missing items,
unclear descriptions, contradictions and typing slips, and reports them as signals for the
reviewer ([ADR 0013](docs/decisions/0013-tender-review-checks.md)). The Projects page groups a bid's
bills and references, accepts several files at once and validates the whole project. Each file
still opens in the Workspace for its editable sheet, findings, review and exports. Not yet done: sorting, filtering and
search in the sheet. Phase B,
anomaly detection for bills of quantities, is approved and planned. See [progress](docs/handoff/PROGRESS.md), [known limitations](docs/known-limitations.md)
and the plan in [`docs/handoff/NEXT_STEPS.md`](docs/handoff/NEXT_STEPS.md).

## Set up

The exact versions of Python, pip, Node.js, PostgreSQL, Tesseract and Ollama are in
[`SYSTEM_REQUIREMENTS.md`](SYSTEM_REQUIREMENTS.md): Python 3.13.18 on macOS and Linux, Python
3.11.9 on Windows, Node.js 24.22.3.

macOS and Linux:

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/python -m pip install pip==26.3
.venv/bin/python -m pip install -c requirements.lock.txt -e ".[dev]"
```

Windows (PowerShell):

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install pip==26.3
.\.venv\Scripts\python -m pip install -c requirements.lock.txt -e ".[dev]"
```

Frontend (any system, from `frontend/`): `npm ci`.

## Run

API server (from `backend/`; data is stored in `backend/var/`):

```bash
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

On Windows use `.\.venv\Scripts\uvicorn` instead. Interactive API documentation:
`http://localhost:8000/docs`. The API is described in [`docs/api/rest-api.md`](docs/api/rest-api.md).

### Settings

Settings are environment variables prefixed `TWB_`, with `__` for nesting (lists as JSON); the
[configuration table](docs/deployment.md#configuration) lists every one with its default, and
`backend/app/core/config.py` is the reference. The groups:

| Settings | Defaults |
| --- | --- |
| `TWB_DATA_DIR`, `TWB_DATABASE_URL` | `var`; SQLite in the data directory |
| `TWB_ALLOWED_HOSTS`, `TWB_CORS_ORIGINS`, `TWB_MAX_JSON_BODY_BYTES` | `localhost` and `127.0.0.1`; the Vite dev server; 1 MiB |
| `TWB_AUTH__TOKENS` (sign-in) | `[]`: no sign-in |
| `TWB_LOGGING__*` | `INFO`, `text` |
| `TWB_FRONTEND_DIST_DIR` (serve the built interface) | unset |
| `TWB_DEMO_PROJECT_DIR` (private sources for ready-made projects) | unset; `/app/demo-set` in the container |
| `TWB_DEFAULT_PROFILE_ID` | `boq` |
| `TWB_EXTRA_PROFILE_DIRS` (your own profile files) | `[]` |
| `TWB_DETECTOR_PACKAGES` (your own detector packages) | the four built-in packages |
| `TWB_INGESTION__*` (upload limits) | 25 MiB per upload, and the limits in the table |
| `TWB_NORMALIZATION__*`, `TWB_VALIDATION__*` (run limits) | see the table; a run's time limit is 300 s |
| `TWB_PERSISTENCE__*` (database, upgrades) | SQLite files upgrade at start-up after a backup copy |
| `TWB_JOBS__*` (background runs) | 2 workers, 16 waiting |
| `TWB_ENVIRONMENT`, `TWB_APP_NAME` | `development`, `Desvio` |

Profiles and detector packages of your own: [deployment guide](docs/deployment.md#your-own-profiles-and-detector-packages).

Frontend (from `frontend/`): `npm run dev`, then open `http://localhost:5173`.

### Bill-wide what-if scenarios

Open a bill's **What-if** tab to compare all its tables without changing any BoQ cells.
Choose a material group from the searchable picker, review and adjust the matched
positions, then add a percentage unit-price rule. Multiple rules compound in order. Independently
include or exclude positions to try optional items or swap alternatives. The view shows each
position's before/after prices, contribution and change, plus the net bid comparison. It excludes
tax and bill-level adjustments; ambiguous inclusion, incomplete prices, mixed currencies and
inconsistent affected line totals prevent a reliable total rather than producing a partial one.

Named scenario versions are saved **only in this browser**, bound to the source dataset revision.
They are not shared server-side, project-wide aggregates or correction revisions. The reusable
literal matcher is `frontend/src/features/materials/materialMatching.js`; it does not infer
synonyms or classify materials automatically.
Picker groups reuse `frontend/src/features/materials/materialQuantities.js`: identical specifications,
section contexts and units, with optional or incomplete positions left to the manual controls.

### Projects and ready-made demos

For the presentation boundary and verified entry path, see
[D-8: Kalkufer-only demo scope](tools/showcase/README.md#d-8-presentation-scope-option-1).

Create a project, then choose or drop several bills in its compact Add files card. More options
contains supporting-reference roles, IFC targets and existing-file reuse. The dashboard's counters
filter files with pending findings, high/critical pending findings, or reading/check failures.
Unvalidated projects show no finding count rather than a misleading zero. Existing uploads can
belong to several projects without copying their originals.
IFC uploads require an explicit target bill; its Properties tab keeps the existing design-model
controls. Removing a file from a project does not delete its original or other memberships.

Validate project runs the existing checks on every readable bill in the background and compares
matching item numbers, descriptions and units across bills and references for quantity and unit
price differences. These are review signals, not confirmed errors; alternative representations
are never summed as project costs. Findings, corrections and exports remain traceable per file.
Revalidate after editing a file or replacing an IFC. This is not a general semantic comparison
of all text across unrelated trades.

For the gated hackathon demo, `npm run dev` / `npm run build` prepares gitignored copies in
`backend/demo-set`, outside the frontend's public directory. Set `TWB_DEMO_PROJECT_DIR` to its
absolute path when starting the backend. The container does this automatically. The three demo
projects of `backend/app/services/demo_projects.json`, and only their files, are copied there and
imported server-side on first start, without browser uploads; progress and failures
are visible in Projects. Subsequent starts resume incomplete imports and preserve ready projects.
The generated IFC and planted-fault workbook are test material, not a supplied design or a real
bid revision. Do not commit the demo sources or serve this deployment outside the hackathon gate.

Synthetic benchmark (from `backend/`): `.venv/bin/python -m app.evaluation`; see
[`docs/evaluation`](docs/evaluation/README.md).

## Deployment

`docker compose up --build -d` builds one image (the API plus the built web interface, running
as an unprivileged user) and serves it on `http://localhost:8000`, with the data in a volume.
Optional Compose profiles add PostgreSQL (`--profile postgres`, with `TWB_DATABASE_URL` set) and
an Ollama server reserved for a later phase. Before exposing it beyond your own machine, set
`TWB_AUTH__TOKENS` and put a TLS proxy in front. Database upgrades: `python -m app.cli db
current` and `db upgrade`. Configuration, authentication, logging, background runs, migrations,
PostgreSQL and backups: [`docs/deployment.md`](docs/deployment.md). To check a new
installation, upload [`samples/sample-bill.xlsx`](samples/README.md) and validate it: the run
should report the eight findings listed in `samples/README.md`.

## Test

Backend, from `backend/` (Windows: `.\.venv\Scripts\python` instead of `.venv/bin/python`):

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
```

`mypy` without arguments checks the `app` package in strict mode (configured in
`pyproject.toml`). `pytest -m integration` runs only the end-to-end tests (API, sample bills);
`pytest -m evaluation` only the benchmark tests. CI also measures coverage:
`pytest -q -m "not performance" --cov --cov-report=term --cov-fail-under=94.5`, and runs the
tests with time limits (`pytest -q -m performance`) in a separate step, because coverage tracing
slows the code several times over.

PostgreSQL tests: install the `postgres` extra, then point `TWB_TEST_DATABASE_URL` at a
database the tests may empty (each test empties it first, so give parallel runs their own
database). `TWB_TEST_REQUIRE_POSTGRESQL=1` turns a missing URL into an error instead of a skip:

```bash
.venv/bin/python -m pip install -c requirements.lock.txt -e ".[dev,postgres]"
TWB_TEST_DATABASE_URL=postgresql+pg8000://postgres:postgres@localhost:5432/twb_test \
  TWB_TEST_REQUIRE_POSTGRESQL=1 .venv/bin/python -m pytest -q -k postgresql tests/unit/repositories tests/integration
```

Interface, from `frontend/` (after `npm ci`):

```bash
npx vitest run
npm run build
npx playwright install chromium   # once, for the browser test
npm run test:e2e
```

`npm run test:e2e` builds the interface, starts its own backend (from `backend/.venv`, with a
temporary data directory) and the preview server, and runs the browser tests in Chromium. The
backend gets only the settings the test sets: no `TWB_*` variable of your shell reaches it.
Other ports, for example next to a running server: `TWB_E2E_BACKEND_PORT=8143
TWB_E2E_PREVIEW_PORT=4193 npm run test:e2e`; the other options are described at the top of
`frontend/playwright.config.js`.

## Documentation

| Topic | Where |
| --- | --- |
| Project challenge brief | [`docs/product/challenge-a.md`](docs/product/challenge-a.md) |
| Opening speech transcript and findings | [`docs/product/opening-speech.md`](docs/product/opening-speech.md) |
| Estimator interview transcript and findings | [`docs/product/estimator-interview.md`](docs/product/estimator-interview.md) |
| Requirements | [`docs/product/brief.md`](docs/product/brief.md) |
| Competitor research | [`docs/product/competitor-landscape.md`](docs/product/competitor-landscape.md) |
| Academic research | [`docs/product/research-frontier.md`](docs/product/research-frontier.md) |
| Real-world BoQ faults and benchmark design | [`docs/product/boq-fault-research.md`](docs/product/boq-fault-research.md) |
| Architecture | [`docs/architecture/overview.md`](docs/architecture/overview.md), [data model](docs/architecture/data-model.md), [validation engine](docs/architecture/validation-engine.md) |
| Detectors | [`docs/architecture/detector-catalogue.md`](docs/architecture/detector-catalogue.md) (generated from the code) |
| REST API | [`docs/api/rest-api.md`](docs/api/rest-api.md) |
| Decisions | [`docs/decisions/`](docs/decisions/README.md) |
| Evaluation | [`docs/evaluation/`](docs/evaluation/README.md) |
| Known limitations | [`docs/known-limitations.md`](docs/known-limitations.md) |
| Deployment and operations | [`docs/deployment.md`](docs/deployment.md) |
| Dependencies and licenses | [`LICENSES.md`](LICENSES.md) |
| Plan and progress | [`docs/handoff/NEXT_STEPS.md`](docs/handoff/NEXT_STEPS.md) (the plan), [`docs/handoff/PROGRESS.md`](docs/handoff/PROGRESS.md) (where each step stands) |
