# 0003: Issue identity: unique fingerprints and subjects

Status: accepted.

## Context

Review decisions are carried into later runs by `(fingerprint, evidence_digest)`. The
fingerprint covered detector, category, rule, table, row and the highlighted cells. Findings
without highlighted cells (table-level findings such as "required column not mapped") and
several findings of one rule at the same place collided, and the pipeline merged them as
"duplicates": marking one false positive would have suppressed the others in the next run.

## Decision

* `IssueFactory.create(..., subject=...)` (formerly `fingerprint_key`): `subject` names what a
  finding is about when the place does not (a field id, a constraint, a group key). It is part
  of the fingerprint and of the evidence digest.
* `subject` is required for findings with neither highlighted cells nor a row.
* Fingerprints are unique within a run: a second finding with the same fingerprint raises
  `IssuePolicyError`, a detector defect that fails its unit tests. The pipeline no longer merges
  findings.
* The fingerprint covers: detector id, category, rule id, table (sheet index and name), row
  (source row number), highlighted cells (source kind, sheet index, page, row, column), subject.
  The evidence digest covers: observed value, expected value, subject, and for every highlighted
  and input cell its source coordinate, raw text and normalized value.

## Consequences

Detectors pass a subject for table-level and grouped findings (`docs/architecture/validation-engine.md`).
