"""Optimistic concurrency of issue updates and the lookup that carries review decisions into
later runs, on both adapters (ADR 0003, ADR 0005)."""

from __future__ import annotations

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.models.audit import EntityType
from app.models.issue import ReviewStatus, ValidationIssue
from app.repositories.base import UnitOfWorkFactory
from app.repositories.sql import issues as sql_issues
from tests.unit.repositories.samples import make_issue, make_run, minutes, review_event

ISSUE = "iss_000001"


def _store(factory: UnitOfWorkFactory, *issues: ValidationIssue) -> None:
    with factory() as uow:
        for run_id in dict.fromkeys(issue.validation_run_id for issue in issues):
            if uow.runs.get(run_id) is None:
                uow.runs.add(make_run(run_id))
        uow.issues.add_many(list(issues))


def _confirm(issue: ValidationIssue, minute: float = 1) -> ValidationIssue:
    return issue.with_review(ReviewStatus.CONFIRMED_ERROR, "Checked.", at=minutes(minute))


# ------------------------------------------------------------------- compare-and-set
def test_update_stores_the_next_version(uow_factory: UnitOfWorkFactory) -> None:
    original = make_issue(ISSUE)
    _store(uow_factory, original)
    with uow_factory() as uow:
        uow.issues.update(_confirm(original), expected_version=1)
    with uow_factory() as uow:
        assert uow.issues.get(ISSUE) == _confirm(original)


def test_a_stale_expected_version_is_a_conflict_and_changes_nothing(
    uow_factory: UnitOfWorkFactory,
) -> None:
    original = make_issue(ISSUE)
    _store(uow_factory, original)
    first = _confirm(original)
    with uow_factory() as uow:
        uow.issues.update(first, expected_version=1)
    # A second reviewer decided on the screen that still showed version 1.
    late = original.with_review(ReviewStatus.FALSE_POSITIVE, "Fine.", at=minutes(2))

    def review_late() -> None:
        with uow_factory() as uow:
            uow.audit.append(review_event("aud_late", original, late))  # rolled back
            uow.issues.update(late, expected_version=1)

    with pytest.raises(ConflictError) as conflict:
        review_late()
    assert type(conflict.value) is ConflictError  # not a review-transition error
    assert conflict.value.code == "conflict"
    assert conflict.value.details == {
        "issue_id": ISSUE,
        "expected_version": 1,
        "current_version": 2,
    }
    with uow_factory() as uow:
        assert uow.issues.get(ISSUE) == first
        assert uow.audit.list_for_entity(EntityType.ISSUE, ISSUE) == []


def test_an_expected_version_ahead_of_the_stored_one_is_a_conflict(
    uow_factory: UnitOfWorkFactory,
) -> None:
    original = make_issue(ISSUE)
    _store(uow_factory, original)
    ahead = _confirm(original).evolve(version=5)
    with pytest.raises(ConflictError) as conflict, uow_factory() as uow:
        uow.issues.update(ahead, expected_version=4)
    assert conflict.value.details["current_version"] == 1


@pytest.mark.parametrize(
    ("version", "expected_version"),
    [(1, 1), (3, 1), (2, 2), (1, 0), (2, True)],
    ids=["same-version", "skips-a-version", "goes-back", "expected-zero", "expected-bool"],
)
def test_an_update_that_is_not_the_next_version_is_refused_up_front(
    uow_factory: UnitOfWorkFactory, version: int, expected_version: int
) -> None:
    _store(uow_factory, make_issue(ISSUE))
    # Refused before storage is consulted: also for an issue that does not exist.
    for issue_id in (ISSUE, "iss_unknown"):
        candidate = make_issue(issue_id).evolve(version=version)
        with uow_factory() as uow, pytest.raises(ValueError, match="version"):
            uow.issues.update(candidate, expected_version=expected_version)
    with uow_factory() as uow:
        assert uow.issues.get(ISSUE) == make_issue(ISSUE)


def test_an_unknown_issue_is_not_found_rather_than_a_conflict(
    uow_factory: UnitOfWorkFactory,
) -> None:
    _store(uow_factory, make_issue(ISSUE))
    with pytest.raises(NotFoundError, match="iss_unknown"), uow_factory() as uow:
        uow.issues.update(_confirm(make_issue("iss_unknown")), expected_version=1)


def test_a_stale_update_naming_a_missing_run_is_still_a_conflict(
    uow_factory: UnitOfWorkFactory,
) -> None:
    # The version is compared before the run reference on both adapters.
    original = make_issue(ISSUE)
    _store(uow_factory, original)
    with uow_factory() as uow:
        uow.issues.update(_confirm(original), expected_version=1)
    moved = _confirm(original).evolve(validation_run_id="run_missing")
    with pytest.raises(ConflictError), uow_factory() as uow:
        uow.issues.update(moved, expected_version=1)


# ------------------------------------------------------------ reviewed_by_fingerprint
DOC, OTHER_DOC = "doc_000001", "doc_000002"


def _issue(
    issue_id: str,
    fingerprint: str,
    *,
    run_id: str = "run_1",
    document_id: str = DOC,
    status: ReviewStatus | None = ReviewStatus.CONFIRMED_ERROR,
    minute: float | None = 1,
) -> ValidationIssue:
    """An issue with ``fingerprint``; reviewed to ``status`` at ``minute`` (``status=None``:
    pending, never reviewed; ``minute=None``: reviewed but without a timestamp)."""
    issue = make_issue(issue_id, run_id=run_id, document_id=document_id, fingerprint=fingerprint)
    if status is None:
        return issue
    if minute is None:
        return issue.evolve(review_status=status)
    return issue.with_review(status, f"Decision on {issue_id}.", at=minutes(minute))


def _store_runs(factory: UnitOfWorkFactory, issues: list[ValidationIssue]) -> None:
    with factory() as uow:
        uow.runs.add(make_run("run_1", dataset_id="ds_a", started_at=minutes(0)))
        uow.runs.add(make_run("run_2", dataset_id="ds_b", started_at=minutes(50)))
        uow.runs.add(make_run("run_x", document_id=OTHER_DOC, dataset_id="ds_x"))
    for issue in issues:  # one unit of work each: storage order is the list order
        with factory() as uow:
            uow.issues.add_many([issue])


REVIEWED = [
    # fp_latest: the later decision wins, whichever run it belongs to.
    _issue("iss_a1", "fp_latest", run_id="run_1", minute=30),
    _issue("iss_a2", "fp_latest", run_id="run_2", status=ReviewStatus.FALSE_POSITIVE, minute=10),
    # fp_tie: the same instant; the issue stored last wins.
    _issue("iss_b1", "fp_tie", run_id="run_1", minute=5),
    _issue("iss_b2", "fp_tie", run_id="run_2", status=ReviewStatus.DISMISSED, minute=5),
    # fp_pending: pending issues are not decisions.
    _issue("iss_c1", "fp_pending", run_id="run_2", status=None),
    # fp_undated: a reviewed issue without reviewed_at ranks after dated ones ...
    _issue("iss_d1", "fp_undated", run_id="run_2", minute=None),
    _issue("iss_d2", "fp_undated", run_id="run_1", status=ReviewStatus.FALSE_POSITIVE, minute=2),
    # ... but is returned when it is the only decision.
    _issue("iss_e1", "fp_only_undated", minute=None, status=ReviewStatus.NEEDS_MORE_INFORMATION),
    # fp_latest in another document, reviewed even later: never used for DOC.
    _issue("iss_x1", "fp_latest", run_id="run_x", document_id=OTHER_DOC, minute=99),
    # fp_mixed: a newer pending issue does not hide an older decision.
    _issue("iss_f1", "fp_mixed", run_id="run_1", minute=3),
    _issue("iss_f2", "fp_mixed", run_id="run_2", status=None),
]
EXPECTED = {
    "fp_latest": "iss_a1",
    "fp_tie": "iss_b2",
    "fp_undated": "iss_d2",
    "fp_only_undated": "iss_e1",
    "fp_mixed": "iss_f1",
}


def _lookup(factory: UnitOfWorkFactory, fingerprints: list[str], document_id: str = DOC):
    with factory() as uow:
        return uow.issues.reviewed_by_fingerprint(document_id, fingerprints)


def test_the_most_recently_reviewed_issue_per_fingerprint(uow_factory: UnitOfWorkFactory) -> None:
    _store_runs(uow_factory, REVIEWED)
    asked = ["fp_unknown", "fp_pending", *EXPECTED, "fp_latest"]  # unknown, pending, a repeat
    found = _lookup(uow_factory, asked)
    assert {fp: issue.issue_id for fp, issue in found.items()} == EXPECTED
    assert list(found) == list(EXPECTED)  # the order the fingerprints were given, each once
    by_id = {issue.issue_id: issue for issue in REVIEWED}
    assert all(issue == by_id[issue.issue_id] for issue in found.values())
    assert {fp: i.issue_id for fp, i in _lookup(uow_factory, ["fp_latest"], OTHER_DOC).items()} == {
        "fp_latest": "iss_x1"
    }
    assert _lookup(uow_factory, []) == {}
    assert _lookup(uow_factory, list(EXPECTED), "doc_unknown") == {}


def test_a_later_decision_on_the_other_issue_takes_over(uow_factory: UnitOfWorkFactory) -> None:
    _store_runs(uow_factory, REVIEWED)
    reopened = REVIEWED[1].with_review(ReviewStatus.PENDING_REVIEW, None, at=minutes(40))
    dismissed = reopened.with_review(ReviewStatus.DISMISSED, "Duplicate.", at=minutes(41))
    with uow_factory() as uow:
        uow.issues.update(reopened, expected_version=2)
    # Resetting to pending is the latest decision: the older confirmation (iss_a1) must not be
    # carried forward again (a withdrawn decision is never resurrected).
    assert "fp_latest" not in _lookup(uow_factory, ["fp_latest"])
    with uow_factory() as uow:
        uow.issues.update(dismissed, expected_version=3)
    assert _lookup(uow_factory, ["fp_latest"])["fp_latest"] == dismissed


def test_large_fingerprint_sets_are_looked_up_in_batches(
    uow_factory: UnitOfWorkFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sql_issues, "ITER_BATCH_SIZE", 2)  # several SQL batches
    _store_runs(uow_factory, REVIEWED)
    asked = ["fp_unknown", "fp_pending", *EXPECTED]
    found = _lookup(uow_factory, asked)
    assert {fp: issue.issue_id for fp, issue in found.items()} == EXPECTED
