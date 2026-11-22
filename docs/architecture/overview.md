# Architecture overview

The Tabular Integrity Workbench is a modular monorepo: a Python/FastAPI backend that owns all
business logic and a React/Vite frontend that presents evidence to reviewers. There is one
deployable backend process (no microservices) with strict internal layering.

```
                ┌──────────────────────────── backend/app ────────────────────────────┐
  HTTP ──► middleware ──► api/routes ──► services/ ──► ingestion/ ──► normalization/ ──► models/
 (REST,     (request id,     │  ▲           │  │        (format          (headers, types,   (canonical)
  /api/v1)   access log,     │  └ schemas/  │  │         adapters)        units, row kinds)
             host, CORS,     │   (request   │  ├──► validation/ (registry ─► plan ─► pipeline ─► detectors)
             origin, sign-in,│    and       │  ├──► repositories/ (SQLAlchemy Core: SQLite or PostgreSQL,
             body limits)    │    response) │  │                    versioned migrations)
                             │              │  ├──► storage/ (write-once originals, content-addressed)
                             │              │  ├──► exporters/ (issues CSV, tables ZIP, JSON, XLSX)
                             │              │  └──► jobs (thread pool for background runs)
  /  ──► api/interface.py: the built web interface, for paths no route matches (never /api)
  python -m app.cli db current | db upgrade ──► repositories/sql/migrations.py
                └───────────────────────────────────────────────────────────────────────┘
frontend/src: app shell ─► features/* (pages) ─► hooks ─► services/* (only place that calls HTTP)
```

## Layer rules

| Layer | May depend on | Never depends on |
| --- | --- | --- |
| `models` | `core` | everything else |
| `profiles` | `models`, `core` | ingestion, validation, api |
| `validation` | `models`, `profiles`, `core` | ingestion, repositories, api |
| `ingestion` | `models`, `core` | normalization, validation, api |
| `normalization` | `ingestion.base`, `models`, `profiles`, `core` | validation, api |
| `repositories` | `models`, `core` | services, api |
| `services` | all of the above through protocols | `api` (FastAPI) |
| `schemas` | `models`, `validation` (registry descriptors), `core` | `services`, `repositories`, `api` |
| `api` | `services`, `schemas`, `core` | detectors, repositories directly |

## The flow of a document

1. **Upload** (`POST /documents`): the stream is spooled with a hard size limit; extension and
   content sniffing must agree; XLSX containers are inspected for zip bombs, encryption and
   path tricks before any parser runs; GAEB DA XML files must be XML without a DOCTYPE. Only then is the original committed to write-once,
   content-addressed storage. It is never modified.
2. **Extraction** (`ingestion/`): a format adapter turns the file into raw cell grids with exact
   coordinates. Formulas are kept as text with their cached results; nothing is evaluated.
   A GAEB DA XML file is validated against the pinned official schema of its version, a GAEB 90
   file against the record rules, and either is flattened into one table whose row kinds and
   column mapping the file itself declares (`RawSheet.declared`).
3. **Normalization** (`normalization/`): header detection, locale-aware parsing that abstains on
   ambiguity, column-to-field mapping through the domain profile, unit normalization and row
   classification produce the canonical `Dataset` (revision 1) plus an extraction report.
4. **Planning** (`validation/planner.py`): every run is planned by the workbench's planner
   (`Workbench.planner`, the `Planner` protocol); clients cannot choose checks. The baseline
   planner, the default, plans every registered detector. A later LLM planner will emit the same
   `ValidationPlan` shape; the planner's `kind`, not the plan's label, is the source the plan
   validator trusts.
5. **Validation** (`validation/pipeline.py`): the plan is validated against the registry (plans
   from clients may set only plannable parameters; tolerances and patterns stay with the
   profile), each detector runs in isolation against a read-only context, and issues are created
   through one factory that applies the evidence policy. A dataset whose extraction failed is
   not validated, and findings on tables whose extraction needs review carry that caveat.
6. **Review** (`POST /issues/{id}/review`): decisions are versioned updates of the issue plus an
   audit event. The dataset is never changed by a finding.
7. **Export**: every export names its validation run and dataset revision.

## Around the flow

* **Schemas** (`schemas/`): the request and response models of the REST API, built from the
  canonical models (for example a run with its issue counts, an issue with
  `allowed_review_actions`). The routes answer with these models, so the OpenAPI document
  describes what is sent.
* **Middleware** (`api/middleware.py`, `api/auth.py`), outermost first: a request id on every
  request and response, one access-log line per request, the `Host` allowlist, CORS, the origin
  check of state-changing requests, optional sign-in and body-size limits. Every failure gets
  the one error envelope (`api/errors.py`).
* **Optional sign-in** (`api/auth.py`): with `TWB_AUTH__TOKENS` set, every route under `/api/v1`
  except `GET /api/v1/health` needs `Authorization: Bearer <token>`. Tokens carry no user
  identity, so the audit actor stays `local`.
* **The served interface** (`api/interface.py`): with `TWB_FRONTEND_DIST_DIR` naming a build of
  the web interface, the backend serves it at `/` (client-side routes get `index.html`), only
  for `GET` and `HEAD` requests that no route matched, never under `/api` in any spelling and
  never a hidden file or directory, behind the same host and origin checks; its files forbid
  framing by other sites. The container image does this; in development Vite serves it.
* **Logging** (`core/logging.py`): every module logs through `logging.getLogger(__name__)` in
  the `app` namespace, to standard error, as text or JSON lines. Logs name ids, counts and
  durations, never file contents, tokens or personal data.
* **Background runs** (`services/jobs.py`): a run started with `Prefer: respond-async` is queued
  (`202 Accepted`) and executed by a small thread pool (`TWB_JOBS__WORKERS`, with a bounded
  queue); clients poll the run. At shutdown queued runs fail and running ones finish; at the
  next start, runs a crash left `queued` or `running` are marked `failed`.
* **The db command line** (`cli.py`): `python -m app.cli db current` reports the schema version
  of a database and the pending migrations; `db upgrade` applies them in one transaction
  (`repositories/sql/migrations.py`, see [data model](data-model.md#storage-and-schema-versions)).

## Where the domain lives

Nothing in `validation/contracts`, `validation/pipeline.py` or `normalization` knows about
construction. BoQ knowledge (header synonyms such as `Einheitspreis`, subtotal wording, unit
aliases, advisory unit rules, reference patterns, tolerances) is data in
`backend/app/profiles/boq.yaml`, with four exceptions in code: the readers of construction
formats (`ingestion/gaeb/`, and `ingestion/pdf/bill.py`, which finds a printed bill's columns,
sections and totals by their German words), the GAEB formats and source kinds in
`models/document.py` and `models/source.py`, the six finding categories with the table that
assigns them to the checks (`models/finding_category.py`, ADR 0010), and the default patterns of
the BoQ checks of step B2 in `validation/domain/boq/` (German bill phrases such as
"Stundenlohnarbeiten" or "nicht angeboten"; they are detector parameters, which a profile may
override). A different challenge means a new profile file and, if needed, new detector modules
with their category entries, and new readers.

## Extension points

| To add | Do this | Core changes |
| --- | --- | --- |
| A detector or research algorithm | One module in a detector package (`validation/<category>/`) with a `DetectorSpec` and a strict config model | None: discovered automatically |
| A domain | A profile YAML file | None |
| A spreadsheet-like input format (XLS, ODS) | An `IngestionAdapter` registered in `ingestion/registry.py` | None in normalization/validation |
| A structured format that states its own layout (another GAEB phase or version, IFC quantities) | An adapter that fills `RawSheet.declared` (row kinds, column fields); pinned schemas next to it, as in `ingestion/gaeb/` | None: reviewer decisions are laid over the declared ones |
| OCR of image files (photos, TIFF); PDF pages are read by `ingestion/pdf/`, from the text layer or, on pages without a usable one, by Tesseract OCR where it is installed (`ingestion/pdf/ocr.py`, [ADR 0012](../decisions/0012-ocr-for-scanned-pdfs.md)) | An adapter that fills the page number, bounding box and engine confidence that raw cells already carry, as `ingestion/pdf/` does for scanned pages | Additive: storing the raw extraction for review needs new raw-layer types; a bill that spans pages and its reading order are already handled inside `ingestion/pdf/` (one declared table, every cell with its page and box) |
| An export format | An exporter adapter in `exporters/` | None |
| An LLM provider / planner | A `Planner` implementation in `agents/` producing `ValidationPlan`, passed to `build_workbench(planner=...)` | None: same plan validator |
| PostgreSQL | Set `TWB_DATABASE_URL` | None |

See also: [data model](data-model.md), [validation engine](validation-engine.md),
[REST API](../api/rest-api.md), [decision records](../decisions/).
