# Deployment

The workbench is one process: a FastAPI application that serves the REST API under `/api/v1`
and, when it is given the built interface, the web interface at `/`. It keeps its data in one
directory (uploaded originals) and one database (SQLite in that directory by default, or
PostgreSQL). This page covers the container image, configuration, authentication, logging,
background runs, database migrations, PostgreSQL and backups.

## Container

The repository root holds a multi-stage `Dockerfile` (Node 22 builds the interface; the
runtime is Python 3.13 slim with the backend installed from `backend/requirements.lock.txt`,
running as the unprivileged user `twb`), a `.dockerignore` and a `docker-compose.yml`.

```bash
docker compose up --build -d        # http://localhost:8000
docker compose logs -f app
docker compose down                 # the data volume stays
```

Without Compose:

```bash
docker build -t tabular-integrity-workbench .
docker run --rm -p 127.0.0.1:8000:8000 -v twb-data:/data tabular-integrity-workbench
```

The image sets `TWB_DATA_DIR=/data` (a volume), `TWB_FRONTEND_DIST_DIR=/app/frontend` (the
built interface), `TWB_ENVIRONMENT=production`, and allows the host names and origins of
`http://localhost:8000`. Its health check calls `GET /api/v1/health`. Uvicorn runs one process:
background runs and their recovery at start-up assume one application process per database.

Compose publishes the port on `127.0.0.1` only, because authentication is off until tokens are
configured. Its optional profiles:

| Profile | Starts | Use |
| --- | --- | --- |
| `postgres` | PostgreSQL 16 (`twb`/`twb`, volume `twb-postgres`) | `TWB_DATABASE_URL=postgresql+pg8000://twb:twb@postgres:5432/twb docker compose --profile postgres up --build -d` (set `TWB_POSTGRES_PASSWORD` and the same password in the URL outside a trial) |
| `ollama` | an Ollama server on `127.0.0.1:11434` | reserved for the local language model of a later step; this release only reports its status in the health check when configured (see Language model) |

The image was built and run on 2026-11-20 (the build added only the sandbox's proxy
certificate): its health check reported healthy, the process ran as `twb`, `python -m app.cli
db current` worked in the container, and the sample bill uploaded through the published port
gave its eight findings in a background run. That build's backend did not serve the interface
yet (contract K6), so check that `/` shows the interface after rebuilding.

## Configuration

Every setting is an environment variable prefixed `TWB_`, with `__` for nesting
(`backend/app/core/config.py` is the reference). A `.env` file in the working directory is read
as well; keep secrets out of the repository. Lists are JSON:
`TWB_ALLOWED_HOSTS='["localhost","workbench.example.org"]'`. Every group of settings, with its
defaults:

| Variable | Default | Meaning |
| --- | --- | --- |
| `TWB_DATA_DIR` | `var` (image: `/data`) | uploaded originals (`originals/`), upload spool (`tmp/`) and the SQLite database |
| `TWB_DATABASE_URL` | unset: `sqlite:///<data dir>/workbench.sqlite3` | any SQLAlchemy URL; PostgreSQL: `postgresql+pg8000://user:password@host:5432/db` |
| `TWB_ENVIRONMENT` | `development` (image: `production`) | `development`, `test` or `production` |
| `TWB_APP_NAME` | `Tabular Integrity Workbench` | the application's name |
| `TWB_ALLOWED_HOSTS` | `["localhost","127.0.0.1"]` | `Host` header allowlist (DNS-rebinding protection): add the name users open |
| `TWB_CORS_ORIGINS` | `["http://localhost:5173","http://127.0.0.1:5173"]`, the Vite dev server (image: `http://localhost:8000`) | origins allowed by CORS and by the origin check of unsafe requests: add the address users open, e.g. `["https://workbench.example.org"]` |
| `TWB_MAX_JSON_BODY_BYTES` | 1 MiB | the largest request body other than an upload (plans, review decisions) |
| `TWB_AUTH__TOKENS` | `[]` (off) | bearer tokens, see Authentication |
| `TWB_LOGGING__LEVEL`, `TWB_LOGGING__FORMAT` | `INFO`, `text` | see Logging |
| `TWB_OCR__ENABLED`, `TWB_OCR__LANGUAGES`, `TWB_OCR__DPI`, `TWB_OCR__WORKERS`, `TWB_OCR__MAX_PAGES` | `true`, `deu+eng`, `300`, `0` (one per core, at most 8), `300` | text recognition of scanned PDF pages with the local `tesseract` command (in the image; install it with German and English data elsewhere). `GET /health` reports whether it is available |
| `TWB_FRONTEND_DIST_DIR` | unset (image: `/app/frontend`) | a directory with the built interface (`index.html`), served at `/` |
| `TWB_DEFAULT_PROFILE_ID` | `boq` | the profile of uploads that name none |
| `TWB_EXTRA_PROFILE_DIRS` | `[]` | directories with your own profile files, read after the built-in ones; see below |
| `TWB_DETECTOR_PACKAGES` | `["app.validation.deterministic","app.validation.statistical","app.validation.semantic","app.validation.domain"]` | the Python packages searched for detectors; see below |
| `TWB_INGESTION__MAX_UPLOAD_BYTES` | 25 MiB | the largest upload |
| `TWB_INGESTION__MAX_ZIP_ENTRIES`, `__MAX_UNCOMPRESSED_BYTES`, `__MAX_COMPRESSION_RATIO` | `5000`, 200 MiB, `200` | XLSX container limits (zip bombs) |
| `TWB_INGESTION__MAX_SHEETS`, `__MAX_ROWS_PER_TABLE`, `__MAX_COLUMNS_PER_TABLE` | `64`, `200000`, `512` | workbook and table size |
| `TWB_INGESTION__MAX_CELLS_PER_SHEET`, `__MAX_CELLS_PER_WORKBOOK` | `1000000`, `1000000` | the memory budget of one file |
| `TWB_INGESTION__MAX_CELL_CHARS`, `__MAX_NUMBER_FORMAT_CHARS` | `32767`, `255` | text of one cell and of one number format |
| `TWB_NORMALIZATION__HEADER_SCAN_ROWS` | `30` | non-empty rows searched for the header |
| `TWB_NORMALIZATION__TYPE_DOMINANCE_THRESHOLD` | `0.8` | share of values that makes a column's type dominant |
| `TWB_NORMALIZATION__FUZZY_HEADER_THRESHOLD` | `0.85` | how close a header must be to a profile synonym to map |
| `TWB_PERSISTENCE__AUTO_UPGRADE` | `sqlite` | which older databases are upgraded at start-up, see Migrations |
| `TWB_PERSISTENCE__BACKUP_BEFORE_UPGRADE` | `true` | copy a SQLite file before upgrading it |
| `TWB_PERSISTENCE__BUSY_TIMEOUT_MS` | `30000` | how long a SQLite writer waits for the database before failing |
| `TWB_PERSISTENCE__DATASET_CACHE_ENTRIES` | `8` | decoded datasets kept in memory |
| `TWB_PERSISTENCE__LOCK_TIMEOUT_SECONDS` | `30` | lock wait of the in-memory storage used in tests |
| `TWB_VALIDATION__MAX_PLAN_STEPS`, `__MAX_STEPS_PER_DETECTOR` | `64`, `3` | the size of a plan |
| `TWB_VALIDATION__MAX_ISSUES_PER_DETECTOR`, `__MAX_ISSUES_PER_RUN` | `10000`, `50000` | issue caps; a detector that reaches one stops there |
| `TWB_VALIDATION__MAX_DETECTOR_SECONDS`, `__MAX_RUN_SECONDS` | `60`, `300` | time limits of one detector and of one run |
| `TWB_VALIDATION__LOW_CONFIDENCE_THRESHOLD` | `0.9` | extraction confidence below which a cell's value counts as unverified (cells from OCR or PDF; spreadsheet cells carry none) |
| `TWB_JOBS__WORKERS` | `2` | threads for background validation runs |
| `TWB_JOBS__MAX_WAITING` | `16` | background runs that may wait for a free worker; more are refused with `503 run_queue_full` |
| `TWB_JOBS__RECOVER_INTERRUPTED_RUNS` | `true` | at start-up, runs a crash left queued or running become failed |
| `TWB_LLM__PROVIDER` | `none` | `ollama` to use a local Ollama server, see Language model |
| `TWB_LLM__BASE_URL` | `http://127.0.0.1:11434` | the Ollama server; only this machine unless `TWB_LLM__ALLOW_REMOTE=true` |
| `TWB_LLM__MODEL` | unset | the model, as the server names it; must be on the allow-list |
| `TWB_LLM__CONNECT_TIMEOUT_SECONDS`, `TWB_LLM__REQUEST_TIMEOUT_SECONDS` | `3`, `180` | connecting (also the health probe) and a whole request |
| `TWB_LLM__CONTEXT_TOKENS`, `TWB_LLM__MAX_OUTPUT_TOKENS` | `8192`, `1024` | the model's context window and the longest answer |
| `TWB_LLM__ALLOW_REMOTE` | `false` | allow a `TWB_LLM__BASE_URL` on another host |
| `TWB_LLM__REUSE_CACHED` | `true` | reuse a stored answer for the same input, model and prompt |
| `TWB_BILL_REVIEW__ANTHROPIC_API_KEY` | unset (off) | the Anthropic key of the Claude bill review a reviewer starts for one bill, see [Claude bill review](#claude-bill-review) |

### Your own profiles and detector packages

A domain profile is a YAML file (`backend/app/profiles/boq.yaml` and `generic.yaml` are the
built-in ones and the best templates). `TWB_EXTRA_PROFILE_DIRS` names directories whose
`*.yaml` files are loaded as well; each profile id must be unique across all of them, or the
application does not start. At start-up every profile is checked against the detector
registry: an unknown detector id in `detector_defaults`, or a default
that the detector's parameters reject, stops the start with a message naming the profile.

`TWB_DETECTOR_PACKAGES` lists the Python packages whose modules are searched for detectors
(modules whose name starts with `_` are skipped). Setting it replaces the default list, so keep
the built-in packages in it. A package of your own must be importable by the backend's Python,
for example installed into the same virtual environment. A module whose optional dependency is
missing is reported in `GET /api/v1/health` (`unavailable_detectors`) instead of stopping the
start. A finding's category (`finding_category`) comes from `CATEGORY_BY_DETECTOR` in
`backend/app/models/finding_category.py`; a detector of your own that it does not list gives
findings without a category, which the interface shows under "Reading the file".

```bash
TWB_EXTRA_PROFILE_DIRS='["/srv/twb/profiles"]' \
TWB_DETECTOR_PACKAGES='["app.validation.deterministic","app.validation.statistical","app.validation.semantic","app.validation.domain","acme_checks"]' \
  .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

With Compose, mount the directory and pass the variables in `docker-compose.yml`; a detector
package then has to be installed into the image.

## Language model

The workbench runs fully without a language model. A local model is set up with the
`TWB_LLM__*` settings below; the Claude bill review, which a reviewer starts for one bill, has a
key of its own ([below](#claude-bill-review)). `GET /api/v1/health` answers `llm` with
`ready` and a `reason` (`not configured` by default), asking the server at most every 30
seconds with the connect timeout.

Two checks run at start-up and refuse to start the application with a clear message:

* `TWB_LLM__BASE_URL` must name this machine (`localhost`, `127.0.0.1` or `::1`), without a
  user name, password, query or fragment, unless `TWB_LLM__ALLOW_REMOTE=true`: document
  content must not leave the machine because of a typo. In Compose the application reaches
  the `ollama` service by its service name, which counts as another host.
* `TWB_LLM__MODEL` must be on the allow-list in `backend/app/agents/models.py`, which records
  each model's source and the licence of its weights (only Apache-2.0 or MIT can be listed).
  It lists `qwen2.5:7b-instruct` (Apache-2.0, added 2026-11-21); its answers are still being
  evaluated. To use it: `ollama pull qwen2.5:7b-instruct`, then `TWB_LLM__PROVIDER=ollama` and
  `TWB_LLM__MODEL=qwen2.5:7b-instruct`.

### Claude bill review

A reviewer can send one bill to Claude for review from the file page (Properties, "How the bill
was checked"). It is off by default, and nothing is sent without a key. To turn it on, install
the optional SDK into the backend's environment and set the key:

```bash
.venv/bin/pip install -e ".[llm]"
TWB_BILL_REVIEW__ANTHROPIC_API_KEY=... .venv/bin/uvicorn app.main:create_app --factory
```

`GET /api/v1/health` then answers `bill_review_available: true` and the button appears for a
person who may write. The key is never logged or returned. Each review sends the text and
numbers of the whole bill, with the findings of the app's own checks, to Anthropic's Messages
API three times at once (passes numbers, basis and text, model `claude-haiku-5-5` at medium
effort, as measured with the evaluation tool); the file name, the project and the people are not
sent. The requests are paid on the key's account. The answer is
stored under `<data_dir>/bill_reviews/`, one file per bill, and no later run calls the model
again. Only send bills the client allows to be sent to Anthropic.

## Authentication

Authentication is optional and off by default, for a single user on their own machine. Set
`TWB_AUTH__TOKENS` to a JSON list of long random tokens (for example from
`python -c "import secrets; print(secrets.token_urlsafe(32))"`) and every route under
`/api/v1` except `GET /api/v1/health` requires `Authorization: Bearer <token>`; a missing or
wrong token gets `401` with the error code `unauthorized`. The web interface asks for the token
once per browser session. Several tokens can be valid at once, so a token can be rotated
without downtime: add the new one, restart, hand it out, remove the old one, restart.

Tokens protect the API, not the network: put the application behind a reverse proxy that
terminates TLS (Caddy, nginx, Traefik) before publishing it beyond the loopback interface,
and add the public host and origin to `TWB_ALLOWED_HOSTS` and `TWB_CORS_ORIGINS`.

## Logging

Everything is logged through Python's `logging` in the `app` namespace, to standard error.
`TWB_LOGGING__LEVEL` sets the level (`DEBUG`, `INFO`, `WARNING`, ...);
`TWB_LOGGING__FORMAT=json` writes one JSON object per line for a log collector, `text` is for
people. Logs never contain file contents, tokens or personal data: they name ids (request,
document, dataset, run), counts and durations. Each validation run logs a start line and a
finish line with its run id, dataset, status, finding count, detector outcomes and duration;
background runs also log when they are queued, and failures with their cause.

## Background validation runs

`POST /api/v1/datasets/{id}/validation-runs` answers with the finished run by default. With
the header `Prefer: respond-async` it answers `202 Accepted` with the queued run and a
`Location` header; clients poll `GET /api/v1/validation-runs/{run_id}` until the status is
`completed`, `completed_with_errors` or `failed`. At most `TWB_JOBS__WORKERS` runs execute at
once and `TWB_JOBS__MAX_WAITING` more wait; a request beyond that gets `503 run_queue_full`
with `Retry-After`. At shutdown the server stops accepting background runs (`503
shutting_down`), fails the queued ones and waits for the running ones (each is bounded by the
run time limit, `TWB_VALIDATION__MAX_RUN_SECONDS`, 300 s by default). Give the container at
least that long to stop: `docker-compose.yml` sets `stop_grace_period: 330s`, because Docker's
default of 10 s would kill running validations. Runs that a crash left `queued` or `running`
are marked `failed` with a warning at the next start. When several application processes share one database, set
`TWB_JOBS__RECOVER_INTERRUPTED_RUNS=false` on all but one of them, or one process would fail
the others' runs.

## Migrations

The database records its schema version (5 in this release, which added the
`explanations` table). A database of an older version is upgraded in one transaction by the
steps in `backend/app/repositories/sql/migrations.py`; if a step fails, nothing changes. A
database written by a newer build is always refused, so an older build never misreads newer
records.

```bash
python -m app.cli db current            # recorded version, this build's version, pending steps
python -m app.cli db current --check    # exit status 1 when an upgrade is pending
python -m app.cli db upgrade            # apply them (SQLite: after copying the file)
python -m app.cli db upgrade --no-backup
```

Both commands use the configured database (`TWB_DATABASE_URL` or the data directory) unless
`--database-url` names another; in the container: `docker compose run --rm app python -m
app.cli db current`.

At start-up, `TWB_PERSISTENCE__AUTO_UPGRADE` decides: `sqlite` (the default) upgrades SQLite
files automatically, after writing a consistent copy next to the file
(`workbench.sqlite3.schema-v3-<UTC time>.bak`; turn it off with
`TWB_PERSISTENCE__BACKUP_BEFORE_UPGRADE=false`), and refuses an older PostgreSQL database with a
message naming `db upgrade`. A server database is shared and valuable, so it should be backed
up and upgraded once, deliberately, not by whichever instance starts first. `always` upgrades
every database at start-up (instances starting together take turns under an advisory lock),
`never` refuses every older database.

## PostgreSQL

Install the driver with the `postgres` extra (`pip install -c requirements.lock.txt -e
".[postgres]"`; the Compose build includes it) and set
`TWB_DATABASE_URL=postgresql+pg8000://user:password@host:5432/database`. The driver is pg8000
(pure Python, BSD-3-Clause); psycopg is not used because of its LGPL licence. The first start
creates the schema in an empty database. The user needs the rights to create tables and
indexes in it, and to alter them for upgrades.

The tests run against PostgreSQL when `TWB_TEST_DATABASE_URL` names a database they may wipe:

```bash
TWB_TEST_DATABASE_URL=postgresql+pg8000://postgres:postgres@localhost:5432/twb_test \
  .venv/bin/python -m pytest -q -k postgresql
```

## Multiplayer review behind the preview gate

Finding discussions use the same SQL database as documents and validation runs (schema 10).
Each browser chooses a shared reviewer name from the top bar. Names are **not authenticated
accounts**: anyone through the existing password/token gate can choose any name. Do not use
this mechanism for access control, confidential per-user permissions or verified attribution.
The server issues an opaque, HttpOnly, SameSite=Lax reviewer cookie lasting seven days;
HTTPS makes it Secure. The author and notification recipient come from this session, not
from user-supplied author ids. Names that have joined appear next to the name button: one
click switches the browser to that reviewer, handy for a demo on one machine. Use two browser
profiles, browsers or private windows for two reviewers at once; ordinary tabs in one profile
share cookies and therefore one reviewer identity.
The team's names (Imants, Larissa, Amin, Muhammad, Ziyu and Johan) are added at every start when
missing, so they exist even after the preview's `/data` is wiped; anyone can still join with
another name. Reviewer names are separate from the user accounts of ADR 0015: those carry a
role and a personal access token and decide what a request may do, while a reviewer name only
says who wrote a comment and who gets a mention.

Open a finding in the table's Risks panel, expand **Comments**, and type `@` to choose a
reviewer who has joined. Arrow keys and Enter also select suggestions. Sending persists the
comment and one notification per distinct mentioned teammate in one transaction. Mentioning
yourself does not notify you; unknown handles are rejected without saving the comment.
The bell polls every three seconds while visible, as do open threads; hidden tabs pause and
refresh on returning. Network failures retain the last data and show a retry status. The
inbox shows up to 100 entries, unread first. Clicking a mention marks it read and opens a
URL carrying the document, validation run, finding and comment, reveals the affected row,
and expands the thread. The URL also works after reload without a remembered open file.
Each finding also has a task: an assignee from the reviewer names, a due date and a type
(Check, Fix, Ask client, Discussion). Task progress (To do, In progress, Waiting, Done) is
hidden in the editor and risk list; its API field and historical values remain intact,
including when the assignee or date is changed. The task is separate from the review decision
(Open, In review, Approved, Rejected): approving a finding neither marks its task Done nor
clears its deadline. Assigned tasks with a deadline before today in the reviewer's local
calendar are overdue, using the same rule for the list and its overdue filter. Accepted
limitation: an assigned historical Done task can also appear overdue. Task changes appear in
the thread, assigning someone else notifies them, and the risk list shows each task. Opening a
notification reads the recipient's other unread notifications on the same finding.
Schema 9 adds the task table and the kind of each thread entry; existing comments are
upgraded automatically and keep their content.
Comments stay attached to the original finding/run; rerunning validation does not copy them
onto newly generated findings. Review-decision notes remain separate from discussions.

### Desvio, the review assistant

Tag `@desvio` in a finding's comments and ask in your own words. Desvio reads the finding,
the bill rows it points at, the task and the thread, and replies in the thread a few seconds
later. It can explain the finding, draft an email to the client or bidder (subject and body in
the `{ to, subject, body }` shape of the interface's email drafts; the address is left empty),
summarise the thread, change the task (assignee, status, type) and suggest next steps. Steps
that assign someone, set a status or open the draft are one click under the reply. Its task
changes are activity entries by Desvio naming who asked. Anything else, such as approving or
rejecting the finding, editing the bill or questions unrelated to the project, it declines and
says what it can do instead. It never changes the review decision or the findings: it has no
tool for that, and the validation pipeline does not call it.

Desvio uses Anthropic's Messages API from the backend. Set the key as the environment
variable `DECIVIO_BOT_ANTHROPIC_API_KEY` (a Fly secret on the preview; `DECIVIO_BOT_MODEL`
overrides the default model, `claude-sonnet-5-5`). The key is never logged or returned.
Without it, tagging `@desvio` gets a reply saying the server has no key, and the comments
panel says so. Tagging Desvio sends that finding's data, its bill rows and the thread to
Anthropic; nothing is sent otherwise. Prompt-injection guards: project text reaches the model
HTML-escaped inside data tags and marked as data, never instructions; the server applies only
the allowed task changes to the current finding, checks every value, and allows at most three
task changes per reply. Answers come from a background task in the one uvicorn process, using
the Messages API's streaming. The browser that tagged Desvio, or any that sees it working,
follows the answer as it is written over server-sent events
(`GET /api/v1/collaboration/issues/{id}/assistant-stream`, plain same-origin HTTP behind the
gate cookie and Fly's proxy, with a keep-alive comment every 15 seconds); task changes, the
email draft and next steps appear once the answer is stored. Other reviewers get the stored
reply through the usual polling. A restart while Desvio is answering loses that answer (tag
it again). Its email drafts and next
steps live in the `assistant_replies` table (schema 10, added by an automatic upgrade).
Live checks against the real API: `DECIVIO_BOT_LIVE_TESTS=1 pytest
tests/integration/test_decivio_bot.py`.

### Fly readiness

No websocket, SSE, Redis, mail provider or additional process is needed. Normal same-origin
HTTP requests work behind Fly's proxy and existing gate. Keep one machine and one uvicorn
worker, as required by background validation already. Polling while the page is open can
keep the machine awake; suspend/resume otherwise preserves the current process/filesystem.
The feature adds no heavy resident service; the existing 512 MB budget still needs measuring
against the actual bill/model workload rather than being treated as a capacity guarantee.

The checked-in Fly preview keeps `/data` on the 1 GB volume `twb_data` in `fra` (task #26),
so uploads, reviewer names, comments and notifications survive deploys. Fly mounts the volume
owned by root; the image starts as root only to hand `/data` to the runtime user (UID/GID
10001) and then runs the server as that user (`docker-entrypoint.sh`). Fly snapshots the volume
daily and keeps 7 snapshots; take one by hand (`flyctl volumes snapshots create <id>`) before a
deploy that changes the schema. Keep a single mounted machine; do not scale independent SQLite
disks horizontally. A volume lives on one host: if that host fails, restore the latest snapshot
into a new volume (`flyctl volumes create twb_data --snapshot-id <id>`). Demo projects are
created by fixed id, so a kept database does not get them twice, but a deleted demo project
comes back at the next start and changed demo files are not imported again into a ready one.
SQLite automatically upgrades schema 6 to 7 at startup under the default policy and writes
a backup first. PostgreSQL deployments must run the documented migration command when
automatic upgrades are disabled. Keep the site gate enabled and the browser's exact origin
in `TWB_CORS_ORIGINS`, including any custom domain.

For the demo, use a synthetic project and two separate browser contexts named Larissa and
Johan. Larissa opens a line-total finding and sends `@johan check this out`; Johan receives
the bell badge, clicks the notification from Projects, and lands on the selected table row
with the highlighted comment. A reply mentioning Larissa completes the round trip. The
real-backend browser regression is `npm run test:e2e -- e2e/collaboration.spec.js`.

## Backups

Everything the workbench keeps is in two places: the data directory and the database.

* SQLite (the default): the database is `workbench.sqlite3` in the data directory, next to
  `originals/`. Back up the whole directory. For a copy while the application runs, use
  SQLite's online backup, which is consistent in WAL mode. The image has no `sqlite3`
  program, so use Python's module, then copy the backup out of the volume (and delete it
  there) together with `originals/`:

  ```bash
  docker compose exec app python -c "import sqlite3; d = sqlite3.connect('/data/backup.sqlite3'); sqlite3.connect('/data/workbench.sqlite3').backup(d); d.close()"
  docker compose cp app:/data/backup.sqlite3 .
  ```

  Or stop the container (`docker compose stop app`) and copy the volume.
* PostgreSQL: `pg_dump --format=custom` of the database, plus a copy of the data directory's
  `originals/`.

Originals are write-once and named by their SHA-256, so copying them again only adds new
files. Restore by putting both back and starting the same or a newer build: an older database
is upgraded as described above. Keep the automatic `.bak` copies of SQLite upgrades until the
upgraded build has run for a while, then delete them.

## Upgrade notes

* **Custom profiles and yes/no cells.** Round 1 moved the words that mean yes or no into each
  profile (`boolean_words`, with `true_words` and `false_words`). A profile without them reads
  no yes/no text: such cells are reported as unreadable, never guessed. A custom profile written
  before round 1 must list them, as the built-in profiles do:

  ```yaml
  boolean_words:
    true_words: ["true", "yes", "ja", "wahr", "y", "j", "x"]
    false_words: ["false", "no", "nein", "falsch", "n"]
  ```

* **The duplicate check's severity setting.** Pull request #3 (merged on 2026-11-20) gave the
  exact-duplicates check (`deterministic.exact_duplicates`) a profile-only setting `severity`.
  It is now called `severity_exact_duplicate` (same default, `medium`), so `severity` always
  names a parameter that a plan may set, and the severities only a profile sets are called
  `severity_<rule>`. A custom profile that sets `severity` for this check under
  `detector_defaults` now stops the start with an unknown-field error:

  ```text
  Domain profiles do not match the detector catalogue: <profile id>: detector_defaults for 'deterministic.exact_duplicates' are invalid (severity: Extra inputs are not permitted)
  ```

  Rename the key to `severity_exact_duplicate`. No built-in profile sets it, and stored runs
  keep their configurations as plain JSON, so nothing stored breaks.

* **Frames and hidden files of the served interface.** The interface's files are sent with
  `Content-Security-Policy: frame-ancestors 'none'` and `X-Frame-Options: DENY`, so a page of
  another site, such as an intranet portal, can no longer show the workbench in a frame: open
  it in its own tab or window. Hidden files and directories of the build (a path segment that
  starts with `.`) get a `404`; the shipped build has none.

* **Detectors of your own packages and the issue policy.** A detector that catches the issue
  factory's `IssuePolicyError` and goes on is now reported `failed`, with an error naming how
  many findings were refused, instead of `completed`. It keeps the findings the factory
  accepted, and its run ends `completed_with_errors` (or `failed` when every detector that ran
  failed). The built-in detectors never swallow the error.

* **Databases** written by an older build are upgraded as described under Migrations.

## Without a container

Build the interface (`npm ci && npm run build` in `frontend/`), install the backend (see the
README), then from `backend/`:

```bash
TWB_DATA_DIR=/srv/twb TWB_FRONTEND_DIST_DIR=../frontend/dist \
  TWB_CORS_ORIGINS='["http://localhost:8000"]' \
  .venv/bin/uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000
```
