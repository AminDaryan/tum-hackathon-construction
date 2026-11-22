"""``allowed_review_actions`` (contract K1): exactly the decisions a review may make now; and
the ranking of a project's findings still to review."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.errors import ReviewTransitionError
from app.models.issue import REVIEW_DECISION_TARGETS, FinancialImpact, ReviewStatus, Severity
from app.models.project import Project, ProjectFile, ProjectValidation
from app.services.issues import allowed_review_actions, top_for_project, view
from tests.unit.api.conftest import make_workbench
from tests.unit.repositories.samples import make_issue, make_run

S = ReviewStatus
EXPECTED = {
    S.PENDING_REVIEW: [S.CONFIRMED_ERROR, S.DISMISSED, S.FALSE_POSITIVE, S.NEEDS_MORE_INFORMATION],
    S.NEEDS_MORE_INFORMATION: [S.CONFIRMED_ERROR, S.DISMISSED, S.FALSE_POSITIVE, S.PENDING_REVIEW],
    S.CONFIRMED_ERROR: [S.PENDING_REVIEW],  # `corrected` only through the correction workflow
    S.FALSE_POSITIVE: [S.PENDING_REVIEW],
    S.DISMISSED: [S.PENDING_REVIEW],
    S.CORRECTED: [],
}
AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_every_review_status_is_covered() -> None:
    assert set(EXPECTED) == set(ReviewStatus)


@pytest.mark.parametrize("status", list(ReviewStatus))
def test_allowed_actions_per_status(status: ReviewStatus) -> None:
    actions = allowed_review_actions(status)
    assert actions == EXPECTED[status]
    assert actions == sorted(actions, key=str)  # sorted by value


@pytest.mark.parametrize("status", list(ReviewStatus))
def test_an_action_is_allowed_exactly_when_the_decision_is_accepted(status: ReviewStatus) -> None:
    issue = make_issue("iss_000001", review_status=status)
    for target in ReviewStatus:
        try:
            accepted = target in REVIEW_DECISION_TARGETS
            if accepted:
                issue.with_review(target, None, at=AT)
        except ReviewTransitionError:
            accepted = False
        assert (target in allowed_review_actions(status)) is accepted, target


def test_the_view_is_the_issue_plus_its_actions() -> None:
    issue = make_issue("iss_000001", review_status=ReviewStatus.DISMISSED)
    shown = view(issue)
    assert shown.allowed_review_actions == [ReviewStatus.PENDING_REVIEW]
    dumped = shown.model_dump(mode="json")
    assert dumped.pop("allowed_review_actions") == ["pending_review"]
    assert dumped == issue.model_dump(mode="json")


def test_a_comparison_with_reference_prices_does_not_rank_as_money_lost(tmp_path: Path) -> None:
    def impact(amount: str, kind: str) -> FinancialImpact:
        return FinancialImpact.model_validate(
            {"amount": amount, "currency": "EUR", "basis": "Synthetic.", "kind": kind}
        )

    wb = make_workbench(tmp_path)
    comparison = make_issue("iss_000001", fingerprint="0" * 32, severity=Severity.HIGH).evolve(
        estimated_financial_impact=impact("-228600.00", "reference_deviation")
    )
    discrepancy = make_issue("iss_000002", fingerprint="2" * 32, severity=Severity.HIGH).evolve(
        estimated_financial_impact=impact("-20.00", "discrepancy")
    )
    without = make_issue("iss_000003", fingerprint="1" * 32, severity=Severity.HIGH)
    with wb.uow() as uow:
        uow.runs.add(make_run())
        uow.issues.add_many([comparison, without, discrepancy])
        uow.projects.add(
            Project(
                project_id="prj_1",
                name="Tender",
                created_at=AT,
                files=[ProjectFile(document_id="doc_000001")],
                validation=ProjectValidation(
                    status="completed", started_at=AT, runs={"doc_000001": "run_000001"}
                ),
            )
        )
    ranked, total = top_for_project(wb, "prj_1")
    # In the run (by fingerprint) the comparison comes first; it ranks with the findings without
    # money, in the run's order, after the discrepancy.
    assert [issue.issue_id for issue in ranked] == ["iss_000002", "iss_000001", "iss_000003"]
    assert total == 3
