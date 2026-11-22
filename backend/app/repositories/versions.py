"""Optimistic concurrency for issue updates, shared by both adapters (ADR 0005).

``IssueRepository.update(issue, expected_version=n)`` stores ``issue`` only while the stored
issue still has version ``n`` (a compare-and-set); every review decision increments the
version (:meth:`app.models.issue.ValidationIssue.with_review`). Both adapters check the
arguments and report a stale version with the functions below, so they refuse the same calls
with the same errors.
"""

from __future__ import annotations

from app.core.errors import ConflictError
from app.models.issue import ValidationIssue


def check_successor_version(issue: ValidationIssue, expected_version: int) -> None:
    """Raise :class:`ValueError` unless ``issue`` is the version after ``expected_version``.

    This is a programming error of the caller (it holds an issue that cannot follow the
    version it names), so it is refused before anything is read or written.
    """
    if isinstance(expected_version, bool) or expected_version < 1:
        raise ValueError(f"expected_version must be an integer >= 1, got {expected_version!r}")
    if issue.version != expected_version + 1:
        raise ValueError(
            f"Issue {issue.issue_id!r} has version {issue.version}, so it cannot replace "
            f"version {expected_version} (it must be version {expected_version + 1})."
        )


def stale_version(issue_id: str, *, expected_version: int, current_version: int) -> ConflictError:
    """The error for an update whose ``expected_version`` is no longer the stored one."""
    return ConflictError(
        f"Issue {issue_id!r} is at version {current_version}, not {expected_version}: it was "
        "changed in the meantime. Reload it and decide again.",
        details={
            "issue_id": issue_id,
            "expected_version": expected_version,
            "current_version": current_version,
        },
    )
