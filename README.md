# Desvio

Desvio helps a bidding team check a construction bill of quantities (BoQ, in German
*Leistungsverzeichnis*) before the bid goes out. You put a tender's files into a project, Desvio
checks every position of its bills, and your team reviews and fixes what it finds.

[![Desvio demo video](docs/media/desvio-demo.gif)](docs/media/desvio-demo.mp4)

## Features

### Projects and users

- **Create a project** for each bid, with a name and a description. The Projects page lists every
  project with its status, and you can search and filter the list.
- **Assign users** to a project, the people who check its bills. You can do this when you create
  the project, or later in the projects table.
- **Manage users** on the Users page. An administrator creates the accounts and gives each one a
  role: a viewer reads, a reviewer also checks and edits, and an administrator also manages the
  users. Each user signs in with a personal access token.

### Files

A project takes several files at once.

| File | What Desvio does with it |
| --- | --- |
| **Bill of quantities** in GAEB DA XML 3.1 to 3.3 (`.x81`, `.x83`, `.x84`, `.x86`), GAEB 90 (`.d81`, `.d83`, `.d84`, `.d86`), Excel, CSV, PDF or Word | Reads it into a table and checks it. Scanned PDFs are read by OCR. |
| **Reference**, such as the tender or another version of the bill | Compares the bill with it. |
| **Supporting document**, such as a geotechnical report or a drawing | Shows it as it is. It is not checked. |
| **3D model** (IFC), linked to a bill | Compares the bill's quantities with the model. |

Every value in the table keeps a link to its source, down to the page and position in a PDF.

### Checks

**Validate project** runs every check on every bill in the background, and compares the bills
with the project's references. The checks combine fixed rules, rules for German bills of
quantities, price statistics and text comparison. They run on your machine and call no language
model. Each finding is of one of six kinds:

| Kind | Examples |
| --- | --- |
| **Error** | A line total that is not quantity × unit price. Totals or tax that do not add up. Units that do not fit. Missing values. Zero or token prices. Typing slips. |
| **Inconsistency** | The bid differs from its tender. Identical positions have different unit prices. A position is there twice. A quantity differs from the 3D model. |
| **Omission** | A gap in the numbering. Work that is paid separately, but no position pays for it. |
| **Ambiguity** | An unclear or contradictory description. A missing material grade or standard. |
| **Risk** | A unit price far from comparable positions. Contingency positions and hourly work. Clauses that put a cost or a risk on the bidder. |
| **Change-order opportunity** | A condition stated as an assumption. A decision left until after the award. |

A finding is a signal for the reviewer, not a proven fault. The
[check catalogue](docs/architecture/detector-catalogue.md) lists every check, what it needs and
where its limits are.

### Review

A bill opens in the Workspace: the bill as a table (or as its original PDF) on one side, its
findings on the other. For each finding, Desvio shows:

- **what is wrong**, and the positions it concerns;
- **the evidence**: the cells, the calculation and the place in the source file;
- **the money at stake**, when it can be calculated;
- **what to do** about it.

The reviewer decides on each finding: **Approve**, **Reject** or **Needs clarification**, with an
optional note. Every decision is recorded with the name of the person who made it.

Teams review together. A finding can be given to a teammate as a task with a type (Check, Fix,
Ask client or Discussion) and a due date. Teammates discuss it in comments, and a mention with
`@` sends a notification.

### Fixes

- **Correct the bill in the app.** Edit a cell in the table, or try a new unit price beside the
  finding and save it.
- **Every correction makes a new version of the bill.** The uploaded file is never changed, older
  versions stay readable, and each changed cell is recorded.
- **Validate again** to check the corrected version.
- **Try prices before you change them.** The What-if tab raises or lowers the unit prices of a
  group of materials by a percentage, or leaves positions out, and shows the bid total before
  and after. The bill stays as it is.
- **Add up quantities.** The Quantities tab groups positions with the same specification and
  unit, adds up their quantities and exports them as CSV.

### Language models (optional)

Desvio works without a language model. You can turn on three kinds of help:

| Help | What it does | Needs |
| --- | --- | --- |
| **Claude bill review** | A reviewer sends one bill to Claude. What Claude suspects joins the findings, marked as a suspicion. | An Anthropic API key |
| **Desvio assistant** | Mention `@desvio` in a finding's comments. It explains the finding, drafts an email to the client or a bidder, sums up the discussion and suggests next steps. | An Anthropic API key |
| **Local model** | Looks for more risks in a bill, and suggests the materials of priced positions. It runs on your machine. Its answers are still being evaluated. | [Ollama](https://ollama.com) with an allowed model |

A language model never changes the bill and never decides a finding. Both stay with the reviewer.
Without a key, nothing is sent to a model. To turn them on, see
[Language model](docs/deployment.md#language-model) in the deployment guide.

### Follow-ups

Open questions become follow-ups of the project: a question to the client, to a subcontractor or
to management, raised from a finding. Each has a status (draft, sent, answered or decided) and the
day its answer is needed. Desvio drafts the email, and you send it from your own email app.

### Reports and exports

- **Reports** for a project or for one bill: a PDF report, an Excel workbook or a CSV file of
  the findings, and a bid risk report as a PDF.
- **The bill itself** as an Excel workbook, with your corrections.
- **Data** for other tools: the findings as CSV or JSON, and the tables as a ZIP file.

### Good to know

- Amounts are exact decimals, never rounded floating-point numbers.
- Formulas and macros in uploaded files are never run.
- The checks use no paid service, and without a language model Desvio needs no network access.
- The interface is in English and German, with light and dark appearance and settings for text
  size, contrast and motion.

## Status

Reading files, the checks, review, corrections, projects, follow-ups, reports and the web
interface are in `main`. Not done yet: sorting, filtering and search in the bill's table. More
detail is in [progress](docs/handoff/PROGRESS.md), [known limitations](docs/known-limitations.md)
and the plan in [`docs/handoff/NEXT_STEPS.md`](docs/handoff/NEXT_STEPS.md). The requirements are
in [`docs/product/brief.md`](docs/product/brief.md).

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

Web interface (from `frontend/`): `npm run dev`, then open `http://localhost:5173`.

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
| `TWB_DEFAULT_PROFILE_ID` | `boq` |
| `TWB_EXTRA_PROFILE_DIRS` (your own profile files) | `[]` |
| `TWB_DETECTOR_PACKAGES` (your own detector packages) | the four built-in packages |
| `TWB_INGESTION__*` (upload limits) | 25 MiB per upload, and the limits in the table |
| `TWB_NORMALIZATION__*`, `TWB_VALIDATION__*` (run limits) | see the table; a run's time limit is 300 s |
| `TWB_PERSISTENCE__*` (database, upgrades) | SQLite files upgrade at start-up after a backup copy |
| `TWB_JOBS__*` (background runs) | 2 workers, 16 waiting |
| `TWB_ENVIRONMENT`, `TWB_APP_NAME` | `development`, `Desvio` |

Profiles and detector packages of your own: [deployment guide](docs/deployment.md#your-own-profiles-and-detector-packages).

## Deployment

`docker compose up --build -d` builds one image (the API plus the built web interface, running
as an unprivileged user) and serves it on `http://localhost:8000`, with the data in a volume.
Optional Compose profiles add PostgreSQL (`--profile postgres`, with `TWB_DATABASE_URL` set) and
an Ollama server for the optional local model. Before exposing it beyond your own machine, set
`TWB_AUTH__TOKENS` and put a TLS proxy in front. Database upgrades: `python -m app.cli db
current` and `db upgrade`. Configuration, authentication, logging, background runs, migrations,
PostgreSQL and backups: [`docs/deployment.md`](docs/deployment.md).

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
npm run typecheck
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
`frontend/playwright.config.ts`.

Synthetic benchmark, from `backend/`: `.venv/bin/python -m app.evaluation`; see
[`docs/evaluation`](docs/evaluation/README.md).

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
