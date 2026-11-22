# Master engineering brief: Tabular Integrity Workbench

Source: project owner's master brief (2026-11-17). Kept here verbatim in substance so every phase
and contributor works from the same requirements. Phases are delivered one at a time.

## Part A: Product objective

Build a web application that accepts structured and semi-structured documents, extracts tabular
information, validates the data using multiple methods, identifies suspicious cells, and presents
evidence to a human reviewer.

Supported input formats: Excel XLSX (XLS through an optional adapter), CSV, digital PDFs, scanned
PDFs and document images.

The application must eventually support: interactive spreadsheet-like viewing; cell-level anomaly
highlighting; deterministic validation; statistical anomaly detection; machine-learning-based
anomaly detection; semantic and contextual validation; LLM-driven validation planning and result
analysis; human review and correction; Excel, CSV, PDF and JSON exports.

The initial domain profile is construction Bills of Quantities (BoQs). Do not hardcode
construction terminology or assumptions throughout the application: implement a generic tabular
validation core and a replaceable domain-specific configuration layer.

## Part B: Non-negotiable engineering principles

### 1. Reliability

Never claim an LLM or anomaly model is 100% accurate. Explicit evidence categories:

- Confirmed rule violation: a deterministic rule has been violated using verified input data.
- Suspected anomaly: a statistical or ML detector identified an unusual observation.
- Semantic warning: a potential inconsistency identified through text or semantic analysis.
- Extraction uncertainty: the original document could not be reliably interpreted.
- Needs external context: cannot be resolved using the current document alone.
- Human-confirmed error: a reviewer explicitly confirmed the finding.

Never present an anomaly score as a probability of error unless calibrated and evaluated. Never
present an LLM conclusion as a confirmed error without supporting evidence. If input is
ambiguous, missing, corrupted or extracted with insufficient confidence, abstain rather than
inventing information.

### 2. Maintainability

Clean architecture and separation of concerns: single-responsibility modules, small testable
functions, dependency injection where appropriate, centralized configuration, typed API contracts
in the Python backend, JSDoc and PropTypes (or equivalent) in JavaScript, consistent naming,
centralized error handling, reusable UI components, separation of business logic and
presentation. Avoid giant components/services, duplicated validation logic, hidden dependencies,
unnecessary abstractions and premature microservices.

### 3. Adaptability to an undisclosed challenge

The final challenge may not be BoQ anomaly detection. Support generic tabular datasets,
configurable column mappings, configurable validation rules, replaceable anomaly detection
algorithms, domain profiles, optional external reference datasets and additional extraction
adapters. The BoQ profile is one configuration/module on top of the generic platform. A new
dataset or research algorithm must not require rewriting the application.

### 4. Free and locally runnable tools

Free, permissively licensed, self-hostable technologies. LLM integration behind a provider
abstraction; optional local Ollama; the application must work without an LLM. Check and document every dependency's actual license.
No paid/enterprise-only features of otherwise free libraries.

### 5. Security

Treat uploads and cell contents as untrusted. Never execute formulas, macros, shell commands or
code from documents. The LLM never executes code, SQL or OS commands; it may only request approved
validation tools through a restricted, schema-validated interface. Protect against malicious
uploads, oversized files, ZIP/XML parsing attacks, path traversal, CSV formula injection in
exports, prompt injection in documents, and cross-user access once authentication exists.
Preserve the original upload unchanged.

## Part C: Architecture

Modular monorepo. Frontend: React, Vite, JavaScript ES modules, Tailwind CSS, a reusable
grid abstraction (AG Grid Community or Glide Data Grid after checking the free feature set; no
Enterprise APIs), REST communication through centralized service modules. Backend: Python,
FastAPI, Pydantic, SQLite for the hackathon behind a repository abstraction that allows
PostgreSQL, local filesystem storage for uploads. Document processing, validation, AI
orchestration, persistence and export logic in separate modules.

## Part D: Canonical data model

Detectors never interpret raw Excel/PDF/OCR output. A normalized intermediate representation
preserves: original filename, original file, format, sheet/page/table location, original row and
column coordinates, original extracted text, parsed value, normalized value, data type, formula,
cached formula result, extraction confidence, user modifications. Multiple sheets/tables.
Conceptual entities: Document, Dataset (domain profile, schema, tables), Table (columns, rows),
Column (original header, normalized name, inferred type, mapped semantic field), Row (source row
index, cells), Cell (raw, parsed, normalized, formula, source reference, extraction confidence,
user edited). Stable identifiers: never identify a cell by its displayed row number. Map canonical
cells to spreadsheet coordinates or PDF page + bounding box; findings navigate to evidence.

## Part E: Validation engine

Independent of the LLM. Detector registry with a common interface. Each detector declares: id,
name, version, category, description, required input features, supported data types,
applicability conditions, configurable parameters, dependencies, output schema, limitations,
license, unit tests. Contract: `detector.validate(validation_context, configuration) ->
list[ValidationIssue]`. New detectors without modifying the core pipeline.

Deterministic detectors (first): missing required values; invalid data types; invalid numerical
values; quantity × unit price vs reported total; subtotal reconciliation; grand total
reconciliation; configurable rounding tolerance; currency consistency; exact duplicate rows;
invalid references; configurable unit normalization; basic unit compatibility rules;
configurable domain-specific constraints. Python Decimal for money; never floating point for
currency reconciliation. Do not assume every item has the same unit conventions; only apply
contextual unit rules when the category/specification is sufficiently established. Never silently
modify input values.

Statistical detectors (optional modules): modified z-score (MAD), IQR, Mahalanobis (only when
assumptions/covariance hold), Isolation Forest, LOF. Configurable parameters; group comparable
items; no multivariate methods on encoded identifiers; detect insufficient samples; handle skew,
constant columns, missing values, redundant features. Outputs are anomaly signals. Do not run
every algorithm automatically; the planner selects applicable methods.

Semantic detectors: exact and normalized description matching, TF-IDF baseline, optional local
embeddings, similarity-based duplicate candidates, description/unit compatibility warnings.
Similarity is evidence for comparison, not proof.

Domain-specific (BoQ profile): description/unit compatibility, repeated descriptions,
section/subsection consistency, conflicting specifications, inconsistent item codes,
duplicate-like items, missing references, configurable expected item relationships. Do not declare
missing work items without specifications, drawings or an established reference.

## Part F: LLM-driven validation planner

The LLM is an orchestrator and reasoning layer: inspect schema and profile, review data-quality
summaries, inspect the detector catalogue, choose applicable registered detectors, configure
allowed parameters, explain choices, interpret results, recommend checks, produce evidence-grounded
findings. Plans contain dataset_profile, selected_detectors, detector_configurations,
execution_order, applicability_rationale, skipped_checks, missing_information,
human_review_requirements; validated against strict Pydantic schemas (reject unknown detectors,
unsupported parameters, excessive execution). Up to four passes (profile/select, execute,
identify gaps, consolidate/report) with strict cycle limits. Fallback without LLM: deterministic
validation and eligible baseline detectors, explain that adaptive AI analysis was unavailable,
never block basic functionality. No documents to external providers without explicit approval.

## Part G: Algorithm research integration

Future research algorithms integrate only through the detector registry, as self-contained modules
with paper reference, description, input requirements, preprocessing, implementation,
hyperparameters, inference, output interpretation, computational requirements, assumptions,
limitations, reproducible tests and baseline comparison. No changes to UI, ingestion, canonical
model, review workflow, exports or database. Never pretend to implement a paper before one is
selected.

## Part H: Issue model

ValidationIssue: issue_id, document_id, dataset_id, table_id, row_id, affected_cell_references,
detector_id, detector_version, issue_category, severity, evidence_class, title, explanation,
observed_value, expected_value, evidence, suggested_action, estimated_financial_impact,
extraction_confidence, anomaly_score, review_status, reviewer_comment, timestamp,
validation_run_id. Review statuses: pending review, confirmed error, false positive, corrected,
needs more information, dismissed. Never change the source dataset automatically; corrections are
separate, user-authorized operations creating a new dataset revision. Audit history of original
values, proposed and applied corrections, user decisions, detector versions, validation runs.

## Part I: Document ingestion

Pluggable ingestion. XLSX via openpyxl: preserve sheet names, cell positions, raw values,
relevant formatting and formulas, source coordinates; never execute macros or formulas; keep
formulas and cached results separately and report when a formula cannot be evaluated. CSV:
delimiter, encoding and header detection, empty values, quoted fields, numeric and date parsing,
retain original values. Digital PDFs via pdfplumber (page numbers, coordinates). Scanned PDFs via
an OCR adapter (PaddleOCR first, optional Tesseract) with confidence and coordinates; request
human verification when a table cannot be reconstructed. Extraction review step: choose header
row, map columns, identify section hierarchy, correct extraction mistakes, confirm units, exclude
rows. Do not run anomaly detection on a badly parsed document without informing the user.

## Part J: Frontend and UX

Not a generic admin dashboard or AI SaaS template: a refined, desktop-first technical workbench
for forensic review of large datasets. Precise hierarchy, strong typography, sophisticated neutral
background, restrained accents, carefully designed spreadsheet surface, clear separation of data,
evidence and findings, subtle borders, minimal cards, no excessive gradients, no decorative
charts. Navigation: Workspace, Documents, Validation runs, Issue register, Exports, Settings.
Main workspace: left panel (documents, sheets/tables, categories, severity and review filters),
centre virtualized Excel-like grid (row/column headers, sheet tabs, resizing, sorting, filtering,
scrolling, selection, keyboard navigation, pinned columns, search, highlighting that distinguishes
confirmed violations from suspected anomalies without obscuring values), right issue inspector
(title, severity, evidence class, detector and version, cell reference, observed/expected values,
explanation, calculations, related rows, financial impact, recommended action, review status;
actions: confirm, false positive, request information, comment, apply correction with explicit
authorization). Accessible colour language (red confirmed, amber suspected, purple semantic, grey
extraction) never relying on colour alone; multiple issues per cell without contradictory
indicators; navigation to the right cell after sorting/filtering. Workspace summary: rows
processed, columns mapped, confirmed violations, suspected anomalies, extraction uncertainties,
pending reviews, run status. No invented accuracy or confidence numbers.

## Part K: Exports

Preserve the original. XLSX review workbook (highlights, styles, comments, original data, issue
register sheet, summary sheet, review statuses, detectors and evidence; preserve formatting where
supported, no promises about macros/charts/pivots). CSV per table plus a separate issue report,
ZIP for multiple sheets, formula-injection protection. PDF report (summary, issue register,
flagged rows, evidence and calculations, references, decisions). JSON (canonical dataset, issues,
detector info, review statuses, metadata). Modular export adapters. Every export identifies its
validation run and dataset revision.

## Part L: Testing and evaluation

pytest backend tests (parsing, canonical conversion, source mapping, every deterministic detector,
numerical edge cases, statistical applicability and small samples, semantic matching, LLM schema
validation, plugin registration, exports, review transitions, audit history). Vitest + React
Testing Library frontend tests. Playwright end-to-end workflow (upload, parse, schema review,
validate, open issue, navigate, confirm, correct, export, reopen and verify). Synthetic datasets
with controlled errors and fixed seeds; precision, recall, F1, precision@K, false positives per
1,000 rows, cell-localization accuracy, extraction accuracy, human-confirmed error rate,
processing time. Separate synthetic from real-world validated performance.

## Part M: Definition of done (every phase)

Working implementation, clean code, tests, error handling, documentation, no duplicated logic, no
hardcoded example findings presented as real, no fake progress indicators, no broken routes or
non-functional controls, no unsupported reliability claims. Maintain README, architecture and API
documentation, dependency/license inventory, detector catalogue, known limitations, setup and test
instructions. Always report what was implemented, files changed, tests executed and results, known
limitations and the recommended next phase. Never silently skip failed tests.
