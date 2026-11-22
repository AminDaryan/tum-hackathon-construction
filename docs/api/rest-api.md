# REST API (v1)

Base path: `/api/v1`. JSON everywhere except the multipart upload and the export downloads.

**The reference for every field is the OpenAPI document** that the backend generates from its
response models (`backend/app/schemas/`): `/openapi.json`, browsable at `/docs` (Swagger UI).
Every route has a response schema there, and every error response is the envelope below. This
page explains what a schema cannot show: conventions, rules and behaviour.

## Conventions

* Decimals are **strings** (`"1250.00"`) so no precision is lost. Timestamps are ISO 8601 UTC
  (`…Z`). Identifiers are opaque strings (`doc_…`, `ds_…`, `tbl_…`, `col_…`, `row_…`, `run_…`,
  `iss_…`).
* Lists are pages: `{"items": [...], "total": n, "offset": n, "limit": n}`. `offset` is at
  most 2^63 − 1, the largest value every database can bind; a larger one is `422
  request_validation_failed`.
* Canonical records are returned as the model defines them (`backend/app/models/`): a run,
  an issue, a row, a column, an audit event. Computed fields such as `effective_evidence_class`,
  `section_row_id`, `mapped_semantic_field` and a source location's `a1` are included.
* Every response carries an `X-Request-ID` header: the client's own value when it is a short
  token of letters, digits, `-` and `_` (at most 64), otherwise a new id. Log lines of the
  request carry the same id.

## Errors

Every rejected or failed request gets one envelope (`ErrorResponse` in the OpenAPI document),
whatever rejected it: a route, request validation, a security check or a middleware.

```json
{"error": {"code": "file_rejected", "message": "Human-readable explanation.",
           "details": {}, "request_id": "b3f0c2…"}}
```

`code` is stable and meant for programs; `message` is for people; `details` depends on the code.

| Code | HTTP | When |
| --- | --- | --- |
| `not_found` | 404 | Unknown document, dataset, table, run, issue, detector, export format or route |
| `method_not_allowed` | 405 | The path exists, the method does not |
| `request_validation_failed` | 422 | Malformed query, body or multipart form (`details.errors[]` with `loc`, `msg`, `type`) |
| `invalid_input` | 422 | Semantically invalid request: an unknown `profile_id` (`details.profile_id`, `details.available`), a review decision to `corrected` (`details.allowed`) |
| `file_rejected` | 422 | The upload failed a security check (zip bomb, encryption, path tricks…); nothing is stored |
| `unsupported_format` | 415 | Extension or content not supported, or they disagree |
| `file_too_large` | 413 | The upload exceeds `ingestion.max_upload_bytes` (`details.max_bytes` or `details.limit`) |
| `request_too_large` | 413 | Another body exceeds `max_json_body_bytes` (`details.limit`) |
| `invalid_validation_plan` | 422 | The planner's plan was rejected before anything ran (clients cannot send plans; this concerns an injected or, later, an adaptive planner); `details.errors[]` lists each problem with its step index (when it concerns one step) and a `code`: `unknown_detector`, `invalid_detector_config`, `parameter_not_plannable` (with `parameters`), `duplicate_step`, `too_many_steps_for_detector`, `baseline_step_with_parameters`, `check_missing` (with `detector_ids`). A plan over the step limit (`TWB_VALIDATION__MAX_PLAN_STEPS`) carries `details.steps` and `details.limit`; an empty plan carries only its message. More than 256 steps make the plan malformed (`invalid_input`) |
| `invalid_review_transition` | 409 | The review status cannot change from the current status to the target (`details.current`, `details.target`, `details.allowed`) |
| `conflict` | 409 | The decision was made on a stale version of the issue (`details.issue_id`, `details.expected_version`, `details.current_version`) |
| `unauthorized` | 401 | Sign-in is required and the bearer token is missing, malformed or wrong (header `WWW-Authenticate: Bearer`) |
| `origin_not_allowed` | 403 | A state-changing request from a browser origin that is not allowed, or marked `Sec-Fetch-Site: cross-site` (CSRF protection; `details.origin` when the request names its origin) |
| `origin_not_allowed` | 400 | A CORS preflight request from an origin that is not allowed (`details.origin`, `details.rejected`) |
| `preflight_rejected` | 400 | A CORS preflight request from an allowed origin asked for a method or headers that are not allowed (`details.rejected`) |
| `host_not_allowed` | 400 | The `Host` header is not in `allowed_hosts` (DNS-rebinding protection; `details.host`) |
| `shutting_down` | 503 | A background run (`Prefer: respond-async`) was asked for while the server shuts down; start it again once the server is back |
| `run_queue_full` | 503 | A background run was asked for while every worker is busy and `jobs.max_waiting` runs already wait; header `Retry-After: 30` |
| `internal_error` | 500 | Unexpected failure; the message is generic, the details are logged on the server only |

## Security

* **Sign-in (optional).** With `auth.tokens` empty (the default) the API is open: it is meant
  for one reviewer on their own machine. With tokens (`TWB_AUTH__TOKENS='["<token>", …]'`),
  every route under `/api/v1` except `GET /api/v1/health` needs `Authorization: Bearer <token>`
  naming one of them; anything else gets `401 unauthorized`. Tokens are compared in constant
  time and are never logged. `GET /health` reports `auth_required`, so a client knows whether
  to ask for a token. `/docs` and `/openapi.json` stay open, and the OpenAPI document then
  declares the bearer scheme so `/docs` can send a token. Create a token with, for example,
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
* **Users and roles** ([ADR 0015](../decisions/0015-users-and-roles.md)). Besides the
  configured tokens (which act as the administrator), user accounts sign in with a personal
  access token that an administrator issues. A role decides what a request may do: `viewer`
  every `GET` and `HEAD`, `reviewer` also every other method, `admin` also `/users`; anything
  else gets `403 forbidden` (`details.role`, `details.required_role`). Without configured tokens
  a request that carries no known user token acts as the local administrator, as before; a user
  token then names who acts and applies their role. Audit events name the user (`actor`) and
  keep the id in `context.actor_id`.
* **Hosts.** A request whose `Host` is not in `allowed_hosts` (default `localhost`,
  `127.0.0.1`; `*.example.org` allows sub-domains) gets `400 host_not_allowed`.
* **CORS.** Only `cors_origins` (default: the Vite dev server) may read responses; a refused
  preflight gets the envelope. `X-Request-ID`, `Content-Disposition`, `Location` and
  `Preference-Applied` are exposed.
* **CSRF.** `POST`, `PUT`, `PATCH` and `DELETE` requests whose `Origin` is not in
  `cors_origins`, or that carry `Sec-Fetch-Site: cross-site`, get `403 origin_not_allowed`.
  Requests without `Origin` (command-line clients, tests) are accepted.
* **Body limits.** Uploads are streamed into the file store and stopped at
  `ingestion.max_upload_bytes`; other bodies at `max_json_body_bytes`. A declared
  `Content-Length` over the limit is rejected before the body is read.
* **Downloads.** `Content-Disposition: attachment; filename="<ASCII fallback>";
  filename*=UTF-8''<percent-encoded name>`, from the sanitized document name. Exported text
  that a spreadsheet would read as a formula is neutralized.
* Uploaded files and cell contents are untrusted: nothing from a document is executed, and the
  original is stored unchanged under its SHA-256. Logs carry ids, sizes, statuses and error
  codes, never file contents, file names, review comments or tokens.

## Endpoints

| Method and path | Response (OpenAPI schema) |
| --- | --- |
| `GET /health` | `HealthResponse` |
| `GET /profiles` | `ProfileList` |
| `GET /detectors`, `GET /detectors/{detector_id}` | `DetectorList`, `CatalogueDetector` |
| `POST /documents` (multipart) | **201** `DocumentDetail` |
| `GET /documents?offset&limit` | `DocumentPage` (newest first; `limit` ≤ 500, default 50) |
| `GET /documents/{document_id}` | `DocumentDetail` |
| `PUT /documents/{document_id}/model` (multipart), `DELETE /documents/{document_id}/model` | `DocumentDetail` |
| `GET /datasets/{dataset_id}` | `DatasetSummary` |
| `GET /datasets/{dataset_id}/tables/{table_id}/rows?offset&limit&row_id` | `RowPage` (`limit` ≤ 1000, default 100) |
| `POST /datasets/{dataset_id}/corrections` | `CorrectionsResult` |
| `GET /datasets/{dataset_id}/summary?run_id` | `WorkspaceSummary` |
| `POST /datasets/{dataset_id}/validation-runs` | **201** (or **202**, see below) `ValidationRunDetail` |
| `GET /datasets/{dataset_id}/validation-runs` | `ValidationRunList` (newest first) |
| `GET /validation-runs/{run_id}` | `ValidationRunDetail` |
| `POST /validation-runs/{run_id}/review-finish`, `DELETE /validation-runs/{run_id}/review-finish` | `ValidationRunDetail` |
| `GET /validation-runs/{run_id}/issues?…` | `IssuePage` |
| `GET /validation-runs/{run_id}/problems` | `ProblemList`: the run's findings joined into problems (same cell, same position, or the same exact difference carried into a total), the most money at stake first; computed on request, never stored |
| `GET /validation-runs/{run_id}/export/{format}` | a file: `issues.csv`, `tables.zip`, `json` (`JsonExport`), `xlsx`, `questions.md`, `pdf` |
| `GET /validation-runs/{run_id}/risks?sort_by&sort_order&discovery_run_id` | `RiskReport` |
| `POST /validation-runs/{run_id}/risks/discovery-runs` | **201** (**202** with `Prefer: respond-async`, **200** when an existing run is returned) `DiscoveryRun` |
| `GET /validation-runs/{run_id}/risks/discovery-runs` | `DiscoveryRunList` (newest first) |
| `GET /validation-runs/{run_id}/risks/discovery-runs/{discovery_run_id}` | `DiscoveryRun` |
| `GET /validation-runs/{run_id}/risk-reviews` | `RiskReviewList`: the latest decision on each reminder without a finding in the run's document |
| `PUT /validation-runs/{run_id}/risk-reviews/{risk_id}` | `RiskReview` |
| `GET /projects/{project_id}/risk-report?limit` | `BidReport`: the project's bid risk report, one row per position that drives price and risk (`limit` ≤ 100, default 20); computed on request, never stored |
| `GET /projects/{project_id}/risk-report/pdf?limit` | The same bid risk report as a PDF attachment (`application/pdf`, `<project>-bid-risk-report.pdf`) |
| `GET /issues/{issue_id}` | `IssueDetail` |
| `POST /issues/{issue_id}/review` | `IssueDetail` |
| `POST /issues/{issue_id}/corrections` | `IssueCorrectionResult` |
| `GET /me`, `PATCH /me` | `Me`: who the request acts for (`kind` `user`, `service` or `local`), the role, its `permissions` and, for a user, the `account`; the PATCH changes one's own `first_name`, `last_name`, `email`, `job_title` and `phone` (any role; 409 without a user account) |
| `GET /users` (admin) | an array of user accounts (UserView), by name |
| `POST /users` (admin) | **201** `IssuedToken`: the account and its first token, shown once |
| `PATCH /users/{user_id}` (admin) | `UserView`; `name`, `email`, `role`, `active`; one's own role and active flag cannot be changed (409) |
| `DELETE /users/{user_id}` (admin) | the accounts that remain, as for `GET /users`; not one's own (409) |
| `POST /users/{user_id}/token` (admin) | `IssuedToken`: a new token; the previous one stops working |

### System and catalogue

`GET /health` answers `status`, `version`, `detector_count`, the loaded `profiles`,
`default_profile_id` (the profile an upload that names none is checked against),
`auth_required`, `ai_planner` (`configured` is `false`: adaptive AI planning is not available
in this version, and the baseline deterministic plan is used)
and `unavailable_detectors`: detector modules that could not be loaded because an optional
package is missing (`module`, `missing_package`, `message`), so a missing package is visible
instead of silently shrinking the catalogue, and `ocr`: whether text recognition of scanned PDF
pages is `available`, the `engine` version, the configured `languages` and the `reason` when it
is not (not installed, language data missing, turned off).

`bill_review_available` is `true` when a reviewer can send a bill to Claude for review: the
server has an Anthropic key (`TWB_BILL_REVIEW__ANTHROPIC_API_KEY`) and the optional `anthropic`
package. Nothing is sent to find out.

`llm` reports the local language model: `provider` (`none` or `ollama`), `model`, `ready`,
`reason` when it is not ready (`not configured`, `no model configured`, `server not
reachable`, `model not installed`, `unexpected server response`), and the `server_version` and
`model_digest` the server reported. The server is asked at most every 30 seconds, with the
connect timeout, so the health check stays fast; with provider `none` (the default) nothing is
asked and `llm` is `{"provider": "none", "ready": false, "reason": "not configured", ...}`.
Only risk discovery runs (started explicitly) use it over HTTP (see Risk reminders).

`GET /profiles` lists each domain profile with its version, its fields (`field_id`, `label`,
`data_type`, `role`, `required`) and the size of its unit catalogue (`unit_count`).

`GET /detectors` describes each registered detector: its `spec` (id, version, category,
required fields, evidence classes and issue categories it may emit, limitations, licence,
references), its `parameters_schema`, the `default_config` and the
`plannable_parameters`: the only parameters a later adaptive (LLM) plan may set. Tolerances, rounding, regular expressions and switches stay with the domain profile
and are rejected with `parameter_not_plannable`.

Both `GET /detectors` and `GET /detectors/{detector_id}` take an optional query parameter
`profile_id`. With it, each descriptor also carries `profile_config`: the configuration a run on
that profile uses for the detector when the plan sets nothing, that is `default_config` with
the profile's `detector_defaults` for that detector merged over it, resolved and validated as
the plan validator resolves a step, and serialised like `default_config`. The list response
then also names the `profile_id`. Without the parameter, `profile_config` and the list's
`profile_id` are `null` and nothing else changes. An unknown profile id answers
`422 invalid_input` with `details.profile_id` and `details.available` (the sorted ids of the
loaded profiles), as an upload naming an unknown profile does; so does an empty one
(`?profile_id=`), which an upload would read as none. `GET /detectors/{detector_id}` answers
`404 not_found` for an unknown detector before it looks at the profile. The run configuration
of the web interface asks for the dataset's profile, so every parameter starts at the value the
run would use.

```http
GET /api/v1/detectors?profile_id=boq
```

```json
{
  "profile_id": "boq",
  "items": [
    {
      "spec": {"detector_id": "deterministic.line_total", "...": "..."},
      "parameters_schema": {"...": "..."},
      "default_config": {"...": "..."},
      "plannable_parameters": ["..."],
      "profile_config": {"...": "the defaults with the boq profile's detector_defaults merged over them"}
    }
  ]
}
```

### Projects

* `GET /projects` returns the project array (not a paginated document list). Each project has
  `status` (`in_progress` or `finished`, set by hand) and `assignees`, the reviewer names of the
  people who check its bills (the sign-in rule: a letter, then letters, digits or `_`, at most
  32 characters; at most 20 names, the same name in other case is kept once).
* `POST /projects` accepts `{ "name": "Tender", "description": "...", "assignees": ["Amin"] }`
  and returns 201 with `status` `in_progress`.
* `PATCH /projects/{id}` changes `name`, `description`, `assignees`, `status` or
  `decision_cutoff` (the day of the bid decision, `YYYY-MM-DD`; `null` clears it); fields left
  out stay as they are. Files and validation are not changed.
* `GET /projects/{id}` returns `{ "project": {...}, "documents": [...], "review_counts": {...} }`
  with document summaries and live pending-review counts per bill in the latest project run.
  Each count has `to_review`, `high_priority` (pending high/critical findings only) and
  `findings` (every finding of that run, decided or not); references have no bill count. Review
  decisions are reflected on the next read without revalidation.
* `PUT /projects/{id}/documents` accepts `{ "document_id": "doc_...", "role": "bill" }`;
  `reference` is the other role. Upload each selected file through `POST /documents` first.
  Membership is idempotent and the same document can belong to several projects.
* `DELETE /projects/{id}/documents/{document_id}` removes only the membership, not source bytes.
* Adding, removing or moving a file (`PUT`, `DELETE` or `PATCH /projects/{id}/documents/...`)
  queues a background validation (`TWB_JOBS__AUTO_VALIDATE`) of that file and of the
  project's bills whose inputs it changed: a bill with prices is compared with the unpriced
  bill in its project whose positions match it (`domain.boq_tender_comparison`).
* `POST /projects/{id}/validation` returns 202 and queues validation of every readable bill,
  followed by quantity/price comparison with the project's readable references. Poll the project
  detail for status, per-document run IDs, skipped files and cross-file differences. Membership
  changes and duplicate validation requests return 409 while the project is running.
* `GET /projects/{id}/export/{format}` returns the findings of every bill in the project's last
  completed validation, in the order of the project's files, as an attachment named after the
  project: `pdf` (`<name> report.pdf`, a findings report with one section per bill, laid
  out like the run's `pdf` export), `xlsx` (`<name> issues.xlsx`, one `Issues` sheet with
  a leading `File` column, then the run export's issue columns) or `issues.csv`
  (`<name> issues.csv`, a leading `file` column, then `ISSUE_COLUMNS`, with the same
  protection). 409 while the project has no completed validation; 404 for another format.
* `GET /projects/{id}/top-issues?limit=5&offset=0` (`limit` 1 to 100) returns
  `{ "items": [IssueView], "total": n }`: a page of the findings still to review
  (`pending_review`) over every bill of the last validation, the most severe first, then the
  largest financial impact (by its size; a `reference_deviation` comparison is not money lost
  and ranks with the findings without one), then in file order; `total` counts them all. 409
  before the project is validated or while it runs.
* `POST /projects/{id}/reports` with `{ "format": "pdf" | "xlsx" | "issues.csv" | "bid-risk.pdf", "document_id"? }`
  generates a report on the last completed validation, of the whole project (no `document_id`,
  as `GET /projects/{id}/export/{format}`) or of one bill of it (as that run's export), or the
  bid risk report (`bid-risk.pdf`, as `GET /projects/{id}/risk-report/pdf`; the whole project
  only, 422 with a `document_id`; also after a validation that stopped part-way, on the bills it
  validated), keeps its file in the file store and returns **201** with the
  `ProjectReport` (`report_id`, `created_at`, `format`, `document_id`, `filename`, `media_type`,
  `size_bytes`, `storage_key`, `validated_at`). 409 before the project is validated; 404 for a bill not in that validation;
  422 for another format. `GET /projects/{id}/reports` lists them, newest first, and
  `GET /projects/{id}/reports/{report_id}/file` downloads one again. The project keeps them in
  `reports`.

Cross-file matching requires the same item code, normalized description and unit, and returns
at most 500 differences. It does not sum alternative formats, infer omissions from extraction
failures, or call differing source values confirmed faults. Existing per-run review and export
endpoints remain the source of file-level findings. Revalidate after file corrections or IFC
changes; a finished project result describes its run, not a continuously updated assessment.
Interrupted project jobs become failed on restart and can be requested again.

#### Clarifications

The questions a project has to settle before the bid decision, each raised on a risk reminder of
one of its bills. They need the SQL database (422 with the in-memory repositories).

* `GET /projects/{id}/clarifications` returns one page, `{ "items": [...], "total", "offset",
  "limit" }`, of the project's clarifications and of the questions the reminders of its last
  validation ask that are not raised yet, from each bill's risk report without the reminders
  reviewers rejected. A question not raised yet has `clarification_id` null and reads as a draft
  bidder question (`title` = the question). The most urgent `tier` comes first; within one, the
  clarifications in the order they were raised, then the questions in file order. `offset`
  (default 0) and `limit` (1 to 100, default 10) choose the page; `total` counts every page.
  `search` keeps the items whose title, bill name, recipient or answer hold every word (case
  and accents ignored); `phase`, `kind` and `status` (`suggested` for a question not raised yet)
  keep one value; `due_by` (`YYYY-MM-DD`) keeps what is not decided and needed by that day.
  Each has `clarification_id`, `document_id` (the bill), `risk_id`, `tier` (the reminder's review
  priority when it was raised), `kind` (`bidder_question`, `subcontractor` or `management`: who
  is asked), `title`, `status` (`draft`, `sent`, `answered`, `decided`), `due` (the day the
  answer is needed, or null), `phase` (`bid` or `after_award`) and `answer`. The questions of a
  finished run are kept in memory once read (and read when a project validation finishes) until
  a reviewer decides on one of its findings.
* `POST /projects/{id}/clarifications` accepts `{ "document_id", "risk_id", "tier", "title" }`
  and optionally `kind` (default `bidder_question`), `status`, `due`, `phase` and `answer`. It
  returns 201, or 200 with the existing one while the reminder has an undecided clarification of
  that kind, so asking twice lists the question once. The document must be a file of the project
  (422).
* `PUT /clarifications/{clarification_id}` replaces all a reviewer sets:
  `{ "kind", "title", "status", "due", "phase", "answer" }`. A field left out goes back to its
  default; the reminder, its tier and the project stay as they are.

### Documents

`POST /documents` takes `multipart/form-data` with `file` (required: `.xlsx`, `.csv`, GAEB
DA XML 3.1–3.3 `.x81`, `.x83`, `.x84`, `.x86`, GAEB 90 `.d81`, `.d83`, `.d84`, `.d86`, a
printed bill of quantities as `.pdf`, scanned pages read by OCR, or a Word document `.docx`,
format `docx`, whose cells have the source kind `word`; a legacy `.doc` is `415` with the
advice to save it as `.docx`) and `profile_id`
(optional; `default_profile_id` when absent or empty). The file part is written to the file
store while it arrives. The fields may come in any order; exactly one file part (named
`file`), at most 16 parts, text fields up to 1 KiB. A body that breaks these rules or is not
multipart is `422 request_validation_failed`; an unknown `profile_id` is `422 invalid_input`.
A file that fails a security or format check is rejected (4xx). Nothing is stored in any of
these cases. A stored file whose extraction fails still answers 201, with
`document.processing_status = "failed"`, a `failure_reason` and `dataset = null`. This includes
a GAEB file of an unsupported version, one that fails the official schema (DA XML) or the
record checks (GAEB 90), or whose phase does not match its extension; the reason names the
problem and its line.

`processing_status` is `stored`, `processed`, `needs_review` (a dataset exists but extraction
warnings need a reviewer) or `failed`. The document summary carries the stored file's
`size_bytes` and `sha256`, the latest dataset's `dataset_id`, `table_count` and `row_count`,
and `last_run` (`null` until a validation run exists).

`GET /documents/{document_id}/original` returns the unchanged uploaded bytes as an attachment,
with their stored media type, `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
It uses the same authentication as document metadata; an unknown document is `404 not_found`.
The UI fetches PDF originals with its bearer token before displaying them via a temporary
object URL. No storage key, filesystem path or public asset copy is exposed.

`PUT /documents/{document_id}/model` attaches a design model to a bill: `multipart/form-data`
with `file`, an IFC STEP file (ISO 10303-21; IFC2X3, IFC4 or IFC4X3). It replaces a model
attached before. The model's elements link to the bill's positions by classification
references whose identification is the item number (IfcRelAssociatesClassification), and their
base quantities (IfcElementQuantity) are summed per item number when the file is read
(`backend/app/ingestion/ifc.py`). A file that is not IFC is `422 invalid_input`, and nothing
changes. The document summary's `model` (`ModelInfo`: file name, `sha256`, schema, project,
`elements`, `linked_positions`, `unlinked_elements`) describes the attached model; it is `null`
without one. Every validation run of the document then runs `domain.model_quantities`, which
compares the bill with the model (see the detector catalogue). `DELETE` detaches the model.

### Datasets

`GET /datasets/{dataset_id}` is the dataset without its rows: the extraction report (adapter,
`quality`, `warnings`), each table's `source`, detected `header`, `row_count`,
`row_kind_counts` and canonical `columns`, and `required_fields_missing` (table id → required
profile fields that no column is mapped to). Extraction `quality` is `needs_review` when any
warning has `needs_review: true`.

`GET …/tables/{table_id}/rows` pages the canonical rows of one table in source order; a table
of another dataset is `404`. A row has its `classification` (kind, rule, section level, code,
`counts_toward_totals`: `true`, `false` or `null` = undecided), its `section_path` and
`section_row_id`, and `cells` keyed by `column_id` with the raw, parsed and normalized value,
`parse_status`, `marker`, formula, number format, source location and
`extraction_confidence` (`null` for XLSX, CSV and GAEB: values are read, not estimated).
Rows are always those of the latest revision. With `row_id`, the page holding that row is
returned (`offset` is ignored; the response's `offset` says which page it is); an unknown row is
`404`.

`POST …/corrections` stores corrected cell texts as the dataset's **next revision** (ADR 0001):
`{"expected_revision": 1, "corrections": [{"table_id", "row_id", "column_id", "raw_value"}]}`
(1 to 200 cells; `raw_value` `""` empties a cell). Each new text is read the way an upload reads
a text cell of that column (numbers, units, markers; an ambiguous number takes the column's
decimal separator). The answer is `CorrectionsResult`: the new `revision`, `parent_revision`,
`changed` (cells whose text changed) and the changed `rows` in full. Ids stay the same, older
revisions stay readable by the runs that used them, one `correction_applied` audit event is
written per cell, and the uploaded file is never changed. A text equal to the cell's current
text changes nothing (`changed: 0`, same revision). Errors: `409 conflict` when
`expected_revision` is not the latest revision (`details.current_revision`), `404` for an
unknown dataset, table, row or column, `422 invalid_input` for the same cell twice. Row
classification, sections and column profiles are not derived again. Validation runs started
afterwards check the new revision.

`GET …/summary` summarizes the dataset for the workspace and the finding counts of a run (the
latest when `run_id` is omitted): `counts` has the total, one count per *effective* evidence
class (a finding a reviewer confirmed counts as `human_confirmed_error`) and the findings still
`pending_review`. `run` is `null` and all counts are 0 before the first run.

### Validation runs

`POST /datasets/{dataset_id}/validation-runs`, with an optional body (below). Every run runs every registered
check ([ADR 0010](../decisions/0010-boq-anomaly-detection.md)); a client cannot choose checks or
set parameters. A check that does not apply to the dataset reports itself as skipped, with the
reason, in the run's `detector_reports`.

* By default the run is synchronous and the answer is **201** with the finished run.
* With the header `Prefer: respond-async` (RFC 7240) the answer is **202 Accepted** with the
  same run object, whose `status` is `queued` or `running`, and a `Location` header pointing
  at `/api/v1/validation-runs/{run_id}`. The run continues in a background worker; poll that
  URL until the status is `completed`, `completed_with_errors` or `failed`. A browser on another
  allowed origin can read `Location` and `Preference-Applied` (both are exposed through CORS).
* The optional body `{"match_materials": true}` first asks the configured local model (Ollama on
  this machine, `llm.*`) to suggest a price-reference product for each priced row whose text the
  keywords of `statistical.open_price_reference` cannot match: one request per row, at most 300
  requests and 30 minutes, nothing more once the server cannot be reached. The answers are stored
  per dataset under `<data_dir>/material_matches/` and every later run, and every read of a run,
  its findings or its risks, uses them without calling a model. The check verifies each answer
  (catalogue code, quotes in the text, a scope that buys the material: supply only, or supply
  and install with the material's value as a floor; a unit rule of code, a published value,
  EUR) before it compares; a finding from a suggestion has the rule
  `model_matched_below_published_material_value`, is low severity and `needs_external_context`,
  says so in its title and evidence, and is rejected with the usual review. Without a configured
  model the run uses the keywords only and its report says that the rows were not processed by a
  model (`model_rows_*` coverage counts and notes).
* The optional body `{"bill_review": true}` sends the bill to Claude for review before the
  checks run (Anthropic's Messages API, only when the server has a key: `bill_review.*`, and
  `GET /health` answers `bill_review_available`). Without a key the answer is **409** `conflict`,
  nothing is sent and no run is stored. The run first runs the checks once, then sends the
  whole bill with their findings under the positions they name, once per pass (numbers, basis,
  text) at the same time; the file name, the project and the people are not sent. The answer is
  stored per dataset under `<data_dir>/bill_reviews/` and replaces the one before; every later
  run reads it without calling a model. The check `llm.bill_review` lists the claims the model
  rates as certain (`semantic_warning`, medium severity, rule `r<issue type>` such as `r081`),
  each on the position it names, with the model's reason and its quote; claims it rates lower
  are counted (`claims_less_certain`). After a correction, a claim on a changed position is left
  out and `positions_checked` is not counted until the review is started again. When no pass
  answered (no connection, a refused key), the check is skipped with the reason. A request with
  `bill_review` always starts a run of its own, also while a run with the same inputs is
  unfinished.
* A background run is refused with **503** when the server is shutting down (`shutting_down`)
  or when `jobs.workers` runs are running and `jobs.max_waiting` more are waiting
  (`run_queue_full`, with `Retry-After`). The check comes before the run is stored, so a refused
  request normally leaves nothing behind; only when another request takes the last place at the
  same moment is the run already stored, and it is then marked `failed` with the reason.

`ValidationRunDetail` is the canonical run (plan, profile version, timestamps, one report per
detector with its effective `config`, `coverage` counters and `notes`, warnings) plus
`issue_counts` (by effective evidence class, severity, review status, detector and finding
category, `none` counting the findings without one). `coverage` says what was and
was not checked, so silence is never mistaken for a clean result. A run also carries
`review_status` (`in_progress` or `finished`) and `review_finished_at` (set only while
`review_status` is `finished`).

Run `status`: `queued` (a background run waiting for a worker); `running`; `completed`;
`completed_with_errors` (a detector failed or was stopped by a run limit; a stopped detector
keeps its findings so far, a failed one as said below); `failed` (every detector that executed
failed, the extraction failed, or the server shut down while the run waited or crashed while it
waited or ran; such a run is not resumed, ADR 0006). A detector report's `status` is
`completed`, `skipped` (with `skipped_reasons`), `failed` (with a sanitized `error`: the
exception type and a log reference, or a message written for users; never document content) or
`stopped` (time limit), with `limit_reached` (`time`, `issues` or `null`). A detector that
raised, or returned a finding that breaks an issue rule, keeps no findings. One that went on
after the issue policy refused some of its findings (it caught the refusal itself) is `failed`
too: its `error` counts the refused findings by reason, and the findings the policy accepted
are kept, so a `failed` report can come with `issues_found` above 0.

Review decisions are carried into a new run for findings whose fingerprint *and* evidence digest
both match a reviewed finding of the same document; the carry is recorded in the issue's audit
history.

`POST /validation-runs/{run_id}/review-finish` marks the run review as finished and timestamps
it (`review_finished_at`). It is accepted only after the run finished and only when no finding
is left in `pending_review`; otherwise the route answers `422 invalid_input` with details.
`DELETE /validation-runs/{run_id}/review-finish` reopens the run review (`review_status` back
to `in_progress`, marker cleared).

### Risk reminders

`GET /validation-runs/{run_id}/risks` builds the ranked risk reminders of a finished run from
its findings and the bill's text, on every request; nothing is stored and **no model is
called**. Four parts have separate roles:

* **Checks and grading** (rules, detectors, merge, tiers): always run, deterministic. A
  condition a check of the issue register reports is not checked again by a risk rule: its
  reminder is the finding, with the risk type and the question `findings.yaml` gives its rule.
* **Discovery**: a budgeted local-model search for problems no rule raised. It runs only when a
  client starts it (`POST .../risks/discovery-runs`) and is stored; a report applies a stored
  run when `discovery_run_id` names it. Reading, refreshing, polling and sorting never start it.
* **Model review**: a bounded local-model look at a few open `cannot_tell` reminders the
  rules already raised; it is not discovery and finds nothing new. It has no HTTP entry in this
  version: `model_review=true` is refused (`422`, with a migration note), `false` changes
  nothing.
* **Explanations and actions**: template texts of the risk tables; a model may only reword them.

A finding a reviewer rejected (`false_positive`, `dismissed`) is no reminder: it is not counted,
asks no question and is not graded with the rest, but its reminder is listed after the others of
its list (`risks` or `record`), so a client can show it as rejected and undo the decision.

If the GAEB reader shortened long texts at its length limit, the report's `notes` state how
many were cut. The checks saw only their beginnings; the stored source file remains complete.

`sort_by` (`priority`, default; `price_impact`; `confidence`) and `sort_order` (`desc`, default;
`asc`) reorder `risks` and `record`, each on its own. `priority_rank` keeps a reminder's default
place; `rank` is its displayed place. `price_impact` orders an exact amount by its absolute
value and an estimate by the larger absolute end of its range, with no evidence weight; a
comparison amount (`money.reference`) is never a loss; another or a missing currency is not
converted; unknown money goes last in both directions (a known 0 is an amount). `confidence`
orders by evidence certainty (confirmed, suspected, semantic, unclear), never by a model's own
confidence. Ties keep the default order, then `risk_id`. `open_questions` keep their order.
`display` states the order used and its `policy_version`.

**Experimental supplements** (report format 0.6). A reminder made only of model hypotheses
(`methods` is `["guided_llm"]`) is a supplement to verify, not a task of the checks: it is never
in `risks`, it stays `cannot_tell` with `money.kind` `unknown`, and it is placed after every
reminder of the checks in `record`, in each order and direction (each part is sorted on its own;
the supplements are ranked from the number after the last check reminder). Its question is an
`open_questions` entry with `experimental: true`, listed after every question of the checks and
never grouped with them; `counts.open_questions_from_discovery` counts them. So applying a
stored discovery run leaves the main list, the checks' questions and the checks' record entries
(order, tier, evidence, money) as they were without it. A hypothesis the model named as the same
cause as a check's reminder is attached to that reminder as a `model_hint` counter-evidence
entry: one more source, not an independent confirmation, and it raises no tier. `source: "both"`
is kept in the schema but is no longer produced, because a model hypothesis never joins a
check's reminder. Format 0.6 is part of a discovery run's inputs, so runs stored under 0.5 read
as `outdated`. Any other value is a
`422 validation_error`; `discovery=<anything but off>` and `model_review=true` are a
`422 invalid_input` that says what to use instead.

`POST .../risks/discovery-runs` with `{"strategy": "paths" | "sample", "rerun": false}` runs one
discovery and stores it, bound to its inputs (validation run, dataset revision, profile, bill
text digest, table versions, prompt and checks version, strategy, model) and to
`selection_and_context`: a digest of the positions it chooses, with route and reason, and of
each request it sends, with the known reminders shown. Reviews change the reminders (a rejected
finding is left out, a check's track record changes), so a review that changes what a run
would choose or send changes this input; one that changes neither does not. A second request for
the same inputs returns the queued, running or finished run with **200** and starts nothing
(double clicks and repeated submits included); `rerun: true` starts a new one. With
`Prefer: respond-async` it is queued on the job runner and answers **202**; poll the
`Location` until `status` is `finished` or `failed`. A run left `queued` or `running` by a
restart reads as `failed`. Each run keeps every hypothesis checked, every rejection with its
stage and reason, each request as sent with the raw answer or why none came, `seconds_total`
(end to end) and `seconds_model`. Each entry in `calls` also records the server's `stop_reason`
(for example `stop` or `length`), or `null` when unavailable, including older stored runs.
This diagnostic does not change the call's status or the findings. The budget of the risk
tables applies. A timeout stops the client waiting; whether the model server also stopped
generating is not checked
(`timeout_note`). A report whose inputs changed shows the stored run as `outdated`, with the
changed inputs named, and applies none of it; the run stays readable at its own address, and
the next start for the new inputs makes a new run (**201**, or **202** in the background).

```http
POST /api/v1/validation-runs/run_ab12/risks/discovery-runs
Prefer: respond-async
Content-Type: application/json

{"strategy": "paths"}
```

```json
{"discovery_run_id": "disc_3f9c2a71d0e84b55", "run_id": "run_ab12", "strategy": "paths",
 "status": "queued", "fingerprint": "9d2e…", "requested_at": "2026-11-21T20:14:03Z",
 "inputs": {"validation_run": "run_ab12", "dataset": "ds_77@1", "profile": "boq@1.3.0",
            "prompt_and_checks": "discovery-5", "selection_and_context": "4be1…",
            "strategy": "paths",
            "model": "ollama:qwen2.5:7b-instruct", "…": "…"},
 "timeout_note": "A timeout means the client stopped waiting and closed the connection; …"}
```

```http
GET /api/v1/validation-runs/run_ab12/risks?discovery_run_id=disc_3f9c2a71d0e84b55&sort_by=price_impact&sort_order=desc
```

```json
{"risks": [{"risk_id": "risk_51c0…", "rank": 1, "priority_rank": 3, "tier": "high",
            "money": {"kind": "estimate", "low": "2000.00", "high": "8000.00",
                      "currency": "EUR", "basis": "…"},
            "sort_note": null, "…": "…"}],
 "open_questions": [{"source": "discovery", "serves": ["…"], "reminder_ids": ["…"], "…": "…"}],
 "discovery": {"status": "completed", "discovery_run_id": "disc_3f9c2a71d0e84b55",
               "findings_total": 2, "merged": 0, "partly_read": 0, "…": "…"},
 "display": {"sort_by": "price_impact", "sort_order": "desc", "policy_version": "display-1",
             "…": "…"}}
```

#### Decisions on reminders without a finding

A reminder found by a text check of the risk report has no finding, so `POST
/issues/{issue_id}/review` cannot hold a decision on it. `PUT
/validation-runs/{run_id}/risk-reviews/{risk_id}` with `{"status": "open" | "in_review" |
"approved" | "rejected", "comment": ""}` records one as an audit event (`risk_reviewed`) on the
run's document; `open` takes it back. Reminder ids are stable across runs, so the decision carries
over to later runs of the same document, and `GET .../risk-reviews` returns the latest decision
per reminder. The id is checked for its form (`risk_` and 16 hexadecimal digits), not against the
report, which is computed on request. Reminders with findings are decided through their findings.

#### The bid risk report of a project

`GET /projects/{project_id}/risk-report?limit=20` is the report to print and hand over: the
positions of the project's bills that drive price and risk, read from the risk report of each
bill of the project's last validation (main list only, without the reminders reviewers rejected
through `risk-reviews`). It is computed on request; nothing is stored and no model is called.
It answers 409 before the project is validated and while it is being validated.

* `positions`: one row per position that a reminder names, at most `limit`, ranked by the
  position's size class first (its share of its bill's counted total: 1 % or more, 0.1 % to 1 %,
  below 0.1 %; positions without a line total last), so a large position comes before a small
  one whatever their tiers. Within a size class the sort keys of `grading.yaml` read for the
  position decide (the highest tier and state of its reminders, their largest weighted exposure,
  the highest challenge priority, the number of its reminders), then the larger line total and
  the bills' order (`order_basis` says so in words). The risk list of a run keeps its own
  order. Each row has its bill (`document_id`, `document_name`, `run_id`), the position
  (`label`, `short_text`, `quantity`, `unit`, `unit_price`), its `line_total` and
  `share_of_total` of its bill's counted total, and its `reminders`, each with its own `money`
  (exact, an estimate, or unknown with its basis). The weighted exposure only orders the rows
  and is not in the report.
* When fewer positions have reminders than `limit` and the bills are priced in one currency, the
  positions with the largest line totals fill the list with `kind` `largest` and no reminders;
  `largest_share` is the share of the counted total that the `limit` largest line totals make
  up. Amounts in different currencies are never compared.
* `other_reminders`: reminders no row holds, each listed once with its `reason`
  (`many_positions`: more than `combination.max_positions` of `grading.yaml`; `no_position`;
  `not_a_position`: a total or heading row). Their money is not spread over positions.
* `bills` (status, prices, counted total, reminders kept and `rejected`), `skipped` (files of the
  project with no part in the report, and why) and `notes`. `positions_with_reminders` counts
  the rows before the cut to `limit`.

`GET /projects/{project_id}/risk-report/pdf?limit=20` gives the same report as a PDF to hand
over (A4 landscape, English, the same `limit` and errors): the bills, the rows in the same order
with one table line per reminder (a position with several reminders keeps its rank on each), the
reminders about several positions and the notes. The same report gives the same bytes.

### Issues

`GET /validation-runs/{run_id}/issues` filters with repeatable parameters (OR within one
parameter, AND across parameters): `severity`, `evidence_class` (the effective class),
`review_status`, `detector_id`, `category`, `finding_category` (one of the six finding
categories, or `none` for the findings without one, see below), plus `table_id` and
`row_id`; `limit` ≤ 500 (default 100).

The order is fixed, so a run's pages and its exports never depend on random ids
(`ISSUE_ORDER` in `backend/app/repositories/querying.py`):

1. severity, critical first;
2. the source position of the first highlighted cell: sheet index, then row number, then column
   number. A finding located at a sheet but not at a row (a table-level finding) comes first in
   its sheet; findings without any location come after the located ones of the same severity;
3. then `detector_id`, `rule_id` and `fingerprint` (unique within a run, and the same in every
   run of the same data);
4. then the order in which the issues were stored, and the issue id as the last resort.

Text sorts by code point on every backend: SQLite and the in-memory store compare code points,
and PostgreSQL is told to (`COLLATE "C"`), whatever the database's collation, so `_` sorts after
`.` and `B` before `a` on every installation.

Every issue the API returns (in these pages, in `GET /issues/{issue_id}` and in the review
response) is the canonical issue plus **`allowed_review_actions`**: the sorted review statuses
that a review decision may set from its current `review_status`, empty when none. Offer exactly
these; the rules (`ALLOWED_REVIEW_TRANSITIONS` in `backend/app/models/issue.py`) stay on the
server.

`POST /issues/{issue_id}/review` takes `{"status": "confirmed_error", "comment": "optional",
"expected_version": 1}` and answers the updated issue with its audit history.
`expected_version` is the `version` the reviewer saw: when the issue changed in the meantime
(another tab, a double click) the answer is `409 conflict` and nothing is stored. A status
outside `allowed_review_actions` is `409 invalid_review_transition`; `corrected` is reserved for
the correction workflow and is `422 invalid_input`. Each decision increments `version` and
appends an audit event (`before`, `after`); the dataset is never modified.

`POST /issues/{issue_id}/corrections` applies one or more explicit value changes:

```json
{
  "cells": [{"table_id": "tbl_1", "row_id": "row_5", "column_id": "col_total", "value": "500.00"}],
  "comment": "optional",
  "expected_version": 1,
  "rerun_validation": true
}
```

The route validates optimistic concurrency (`expected_version`), creates dataset revision N+1 of
the same dataset id with the corrected raw values, sets the issue to `corrected`, records audit
events, and returns `IssueCorrectionResult`: the updated issue + history, the new dataset
summary, which cells changed, and (when `rerun_validation` is true) the new validation run
that runs every registered check.

The finding itself (see `ValidationIssue` in the OpenAPI document): `rule_id`, `fingerprint`,
`evidence_digest`, the highlighted `affected_cells` and the `input_cells` it was computed from,
typed `evidence` (for recomputations a `calculation` with operands, the exact and rounded
result, the reported value, the difference and the allowed difference),
`estimated_financial_impact` (only when calculable in an explicit currency),
`extraction_confidence` (OCR/PDF only), `anomaly_score` (never a probability unless
calibrated), `evidence_class` and `effective_evidence_class`, `finding_category`,
`review_status`, `reviewer_comment`, `reviewed_at`.

`finding_category` says what a finding means for the person checking the bill: `error`,
`omission`, `inconsistency`, `ambiguity`, `risk` or `change_order_opportunity`, or `null` for a
finding about reading the file (shown as "Reading the file"). A finding of a detector that
the category tables do not know has `null` too: one from a detector package added with
`TWB_DETECTOR_PACKAGES`, or a stored finding of a detector since renamed or removed (every
detector of the default packages has an entry; a test enforces it). It is computed from the
detector and the rule (the table is in `docs/architecture/data-model.md`); the value a stored
finding carries is never read back, and neither the evidence class nor a review decision
changes it. A finding on a PDF bill that the evidence policy downgraded to
`extraction_uncertainty` keeps its category: verify it in the source.
`suggested_action` is the finding's recommendation.

### Exports

`GET /datasets/{dataset_id}/export/xlsx` returns the extracted tables of the dataset's latest
revision as an Excel workbook, without a validation run (attachment
`<document-stem>-<dataset_id>-extracted.xlsx`): one sheet per table with the columns `Source`
(PDF page, file line, spreadsheet row or CSV record) and `Row kind`, then the table's columns
under their original headers (columns empty in every row are left out), and an `Extraction`
sheet with the document, format, extraction quality and warnings. Numbers are exact decimals
with the source's decimals; text cells are typed as text, so formula-like content is shown and
never evaluated.

Every run export names its validation run and dataset revision, and is an attachment named
`<document-stem> <run start>…`: the run's start in UTC to the minute (`2026-11-22 09-30`), so
two runs of a bill on one day get different names, then ` issues.xlsx`, ` issues.csv`,
` tables.zip`, `.json`, ` questions.md` or ` report.pdf`. Punctuation in the document name
becomes a space (`LV (Kopie).xlsx` gives `LV Kopie 2026-11-22 09-30 issues.xlsx`).

* `xlsx` (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`): the workbook
  above for the run's dataset revision, plus an `Issues` sheet (severity, finding category
  (empty for a finding about reading the file), evidence, review status, check, table, source
  row, cells, title, observed and expected value, financial impact, explanation, suggested
  action, reviewer comment, issue id). Byte-identical for the same run and time.

* `issues.csv` (`text/csv`): one row per finding with the run, dataset revision, issue,
  severity, finding category (`finding_category`, right after `severity`; empty for a finding
  about reading the file), evidence and review fields, the detector, the table, sheet, source
  row and A1 cells, title, observed and expected value, financial impact, explanation,
  suggested action (the recommendation) and reviewer comment, in the order of `ISSUE_COLUMNS`
  (`backend/app/exporters/csv_export.py`). UTF-8 with BOM, comma-separated, RFC 4180 quoting;
  text that a spreadsheet would read as a formula (starting with `=`, `+`, `-`, `@`, tab or
  carriage return, also after leading whitespace) is prefixed with `'`; plain decimal numbers
  are written as numbers.
* `tables.zip` (`application/zip`): `issues.csv`, one CSV per table (source row number, row
  kind, then each column with its original header; values as extracted, with the same
  protection) and `manifest.json` (run, dataset revision, document, profile, the files).
* `json` (`application/json`, schema `JsonExport`): `export` (format, format version, time,
  run, dataset revision, document, profile), the `dataset` revision with its rows, the
  `validation_run`, the `detectors` that ran and the `issues` (with their computed
  `effective_evidence_class` and `finding_category`).
* `questions.md` (`text/markdown`): a ready-to-send list of findings whose
  `review_status = needs_more_information`, with issue id, location, question text and context.
* `pdf` (`application/pdf`): a findings report: the file, the revision checked and when, the
  findings counted by severity and those still to review, then a table of the findings, most
  severe first (severity, review status, where, title and explanation, financial impact). A4
  landscape, Helvetica (Windows-1252 text), written by `backend/app/exporters/pdf_writer.py`
  without a PDF library; byte-identical for the same run and time.

## The web interface

When `frontend_dist_dir` (`TWB_FRONTEND_DIST_DIR`) names the output of `npm run build`, the
backend serves it at `/`: its files with their media types, and `index.html` for client-side
routes. It answers only requests that no API route matches and never paths under `/api`, in
any spelling (`//api/...` or `/x/%2e%2e/api/...` included), so an unknown API path is still a
JSON `404`. Files outside the build and hidden files and directories (a path segment that
starts with `.`, such as `.env` or `.git/`) get the JSON `404` too. The host and origin checks
apply to it as well, and its files are sent with `Content-Security-Policy: frame-ancestors
'none'` and `X-Frame-Options: DENY`, so no other site can show it in a frame (clickjacking).

## Logging

Each request leaves one access line (method, path without the query string, status, duration,
request id, and the error code of a rejected request). Uploads, review decisions, exports and
validation runs are logged with their ids. `logging.level` (`TWB_LOGGING__LEVEL`, default
`INFO`) and `logging.format` (`TWB_LOGGING__FORMAT`: `text`, or `json` for one object per line)
apply when the server starts.
