# 0008: Deferred to Phase 2

Status: accepted. These are deliberate omissions, not gaps found later.

Status note (2026-11-20): round 1 of the review (pull request #3) delivered two of the items
below in part. Optional sign-in: with access tokens configured, every API route except the
health check asks for one; there are still no accounts, owners or workspaces, and the audit
actor stays `local`. Background validation runs: `Prefer: respond-async` answers `202 Accepted`
and the client polls the run; a run without the header is still answered when it is done.
[ADR 0010](0010-boq-anomaly-detection.md) decides statistical, semantic and machine-learning
detectors for bills of quantities; the LLM planner stays deferred. Everything else below is
still deferred. The original decision follows unchanged.

* Per-row dataset storage with paged `DatasetRepository.rows()` (Phase 1 stores immutable
  snapshots with an LRU cache).
* Owner and workspace scoping; authentication. Phase 1 is a single local user (`actor = local`).
* Background validation jobs (`202 Accepted` plus polling). Phase 1 runs synchronously within
  the configured time limits.
* A `PlannerInput` model and the LLM planner itself (the baseline planner is the only planner).
* Immutable tuple containers in the canonical model. Interim: a test asserts that detectors do
  not mutate the dataset.
* Extraction in a subprocess with resource limits (Phase 1 relies on pre-parse checks and
  limits).
* Item blocks whose values sit on the last line of a multi-line item.
* Cross-checking summary pages (Zusammenstellung, collection) line by line against section
  subtotals; Phase 1 reconciles the total that closes a summary block.
* The correction workflow (ADR 0001) and the extraction-review screen that collects schema
  decisions (normalization already applies them).
* OCR of images other than scanned PDF pages, PDF review exports. (PDF bills and the XLSX
  export were added in [0011](0011-pdf-bills-and-excel-export.md), OCR of scanned PDF
  pages in [0012](0012-ocr-for-scanned-pdfs.md).)
* Statistical, semantic and machine-learning detectors.
