# Architecture decision records

Short records of decisions that shape the contracts. Each says what was decided, why, and what
follows from it. Superseded records stay in place with a note.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-corrections-create-revisions.md) | Reviewer corrections create dataset revision N+1; no overlay | accepted |
| [0002](0002-hidden-sheets.md) | Hidden sheets are extracted, skipped by normalization unless a reviewer includes them | accepted |
| [0003](0003-issue-identity.md) | Unique fingerprints per run, `subject` for findings that share a place | accepted |
| [0004](0004-financial-impact-currency.md) | A financial impact exists only in an explicit currency | accepted |
| [0005](0005-review-concurrency.md) | Review decisions are versioned; SQLite writers serialize with `BEGIN IMMEDIATE` | accepted |
| [0006](0006-run-status.md) | A stopped detector makes a run partial, not failed; background runs start `queued` | accepted |
| [0007](0007-condition-ownership.md) | Each cell condition has exactly one reporting detector | accepted |
| [0008](0008-deferred-to-phase-2.md) | Work deliberately deferred to Phase 2 | accepted; status note 2026-11-20: sign-in and background runs delivered in part |
| [0009](0009-gaeb-import.md) | GAEB DA XML 3.3 import: pinned schemas, a file-declared structure, STLB-Bau keys compared within the file | accepted, extended by [0010 (older formats)](0010-older-gaeb-formats.md) |
| [0010](0010-boq-anomaly-detection.md) | BoQ anomalies: rules confirm, comparisons only signal; NumPy only; a local model only explains | accepted |
| [0010](0010-older-gaeb-formats.md) | GAEB DA XML 3.1 and 3.2, phase X86, and GAEB 90 (.d81–.d86) read into the same model | accepted (numbered in parallel with the record above) |
| [0011](0011-pdf-bills-and-excel-export.md) | Printed bills read from a PDF's text layer by their column layout; Excel export of extracted tables and of runs | accepted, extended by 0012 |
| [0012](0012-ocr-for-scanned-pdfs.md) | Scanned PDF pages read by Tesseract OCR, straightened, with superscripts read again and no value guessed | accepted |
| [0013](0013-tender-review-checks.md) | The tender review: missing items, unclear descriptions, contradictions and typing slips as signals in the BoQ baseline | accepted |
| [0013](0013-risk-grading.md) | Risk grading: reminders computed on request from the bill text and stored findings; evidence and priority kept apart | proposed |
| [0014](0014-word-documents.md) | Word documents (.docx): each table read as a table with Word's rows and columns; a bill written as item paragraphs read into the shared bill model | accepted |
| [0015](0015-users-and-roles.md) | User accounts with three roles (viewer, reviewer, admin), signed in by personal access tokens; the audit trail names the user | accepted |

Two records carry the number 0010 because they were written in parallel on 2026-11-20:
[0010-boq-anomaly-detection](0010-boq-anomaly-detection.md) (Phase B: anomaly detection) and
[0010-older-gaeb-formats](0010-older-gaeb-formats.md) (older GAEB formats). In Phase B documents
and code, "ADR 0010" means the first. Two records also carry the number 0013:
[0013-tender-review-checks](0013-tender-review-checks.md) and
[0013-risk-grading](0013-risk-grading.md), written on different branches.
