# 0001: Corrections create dataset revision N+1

Status: accepted (Phase 1 records the decision). Manual cell corrections are implemented since
21 Nov 2026: `POST /datasets/{dataset_id}/corrections` (`app/normalization/revise.py`), used by
the workspace's editable sheet. The stale-parent check is done in the service inside one
transaction instead of a new repository method. Linking a correction to the issue that
motivated it, and moving that issue to `corrected`, are still open.

## Context

The brief (Part H) says the source dataset is never changed automatically and that corrections
are separate, user-authorized operations creating a new dataset revision. Earlier docstrings
also described corrections as an "overlay" on cells. An overlay would have to be applied by every
context accessor, the issue factory's evidence digest and every exporter, and two descriptions
of one mechanism invite two implementations.

## Decision

* A correction is materialized as **revision N+1 of the same dataset**: same `dataset_id`, same
  table, column and row ids, `parent_revision = N`, the corrected cells replaced, and an audit
  event per change (original value, new value, the issue that motivated it, who authorized it).
  The issue that motivated a correction moves to `corrected`.
* **Re-normalization** (for example after a reviewer changed the header row or the column
  mapping) creates a **new dataset** (new `dataset_id`, revision 1). Reviewer schema decisions
  and issue fingerprints are keyed by source coordinates, so decisions and review history carry
  over.
* Validation runs and issues always name the exact `(dataset_id, revision)` they examined.
* There is no overlay: detectors read the revision they are given.

## Consequences

* `Cell` and `ValidationContext` docstrings no longer mention an overlay.
* Phase 2 adds `DatasetRepository.add_revision(dataset, expected_parent_revision)` (rejecting a
  stale parent), a `revise(dataset, corrections)` function next to `build_dataset`, and the
  correction endpoints.
