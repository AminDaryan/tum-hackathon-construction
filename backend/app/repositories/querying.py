"""Query semantics shared by both adapters: orderings, issue filters, counts and paging, and
the selection rules of ``reviewed_by_fingerprint``, ``latest_for_document`` and audit lookups.

The orderings and filters are declared here as data. :mod:`app.repositories.memory` evaluates
them in Python and :mod:`app.repositories.sql` renders them as SQL, so both adapters order,
filter, page and count identically by construction; the parametrized repository tests check it.
Column names refer to the projections in :mod:`app.repositories.records` plus ``seq``, the
monotonically increasing insertion sequence that breaks timestamp ties deterministically.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal, TypeVar

from app.core.errors import InvalidInputError
from app.models.audit import EntityType
from app.models.finding_category import FindingCategory, FindingCategoryKey, finding_category_of
from app.models.issue import ReviewStatus, ValidationIssue
from app.repositories.base import IssueCounts, IssueQuery
from app.repositories.errors import PersistenceError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SortTerm:
    """One ORDER BY term. ``nulls`` places NULLs explicitly (SQLite and PostgreSQL disagree by
    default); it is ``None`` for columns that are never NULL."""

    column: str
    descending: bool = False
    nulls: Literal["first", "last"] | None = None


# Newest first; documents uploaded at the same instant: most recently stored first.
DOCUMENT_ORDER: tuple[SortTerm, ...] = (
    SortTerm("uploaded_at", descending=True),
    SortTerm("seq", descending=True),
)
# Revision history of a document: oldest first, in the order the revisions were stored.
DATASET_ORDER: tuple[SortTerm, ...] = (SortTerm("created_at"), SortTerm("seq"))
# Newest started run first; runs started at the same instant: most recently stored first.
RUN_ORDER: tuple[SortTerm, ...] = (
    SortTerm("started_at", descending=True),
    SortTerm("seq", descending=True),
)
# Audit trail: oldest first; events at the same instant in the order they were appended.
AUDIT_ORDER: tuple[SortTerm, ...] = (SortTerm("occurred_at"), SortTerm("seq"))
# Explanations: newest created first; created at the same instant: most recently stored first.
EXPLANATION_ORDER: tuple[SortTerm, ...] = (
    SortTerm("created_at", descending=True),
    SortTerm("seq", descending=True),
)
# Spelling and text-style findings: every typing-slip finding (a rare spelling variant, a
# repeated word, a known misspelling) and an item with only a short text. They fire about as
# often on the clean originals of the practice bills as on their faulty copies
# (docs/evaluation/boq-practice-p1-tuning.md), so the register shows them after every other
# finding, whatever their severity (issue #85). Derived from the stored detector and rule like
# the finding category, so it needs no column and applies to stored runs too.
STYLE_FINDING = "style_finding"
STYLE_DETECTORS: frozenset[str] = frozenset({"domain.boq_typos"})
STYLE_RULES: frozenset[tuple[str, str]] = frozenset(
    {("domain.boq_description_clarity", "short_text_only")}
)


def is_style_finding(*, detector_id: str, rule_id: str) -> bool:
    """Whether a finding of this check and rule is a spelling or text-style finding."""
    return detector_id in STYLE_DETECTORS or (detector_id, rule_id) in STYLE_RULES


# Issue register: spelling and text-style findings last, then most severe first, then by the
# first affected cell's source position. Rows
# without a row number lead their sheet (table-level findings); issues without any location
# come after the located ones of the same severity. Findings at the same place follow their
# detector and rule, then their fingerprint (unique within a run, and the same in every run of
# the same data), so a run's list and its exports never depend on random ids. Copies of one
# finding from several runs (dataset-wide queries) follow their insertion order; the issue id
# is only the last resort that keeps the order total.
ISSUE_ORDER: tuple[SortTerm, ...] = (
    SortTerm(STYLE_FINDING),
    SortTerm("severity_rank", descending=True),
    SortTerm("sort_sheet", nulls="last"),
    SortTerm("sort_row", nulls="first"),
    SortTerm("sort_column", nulls="first"),
    SortTerm("detector_id"),
    SortTerm("rule_id"),
    SortTerm("fingerprint"),
    SortTerm("seq"),
    SortTerm("issue_id"),
)

# Carrying review decisions forward: the most recently reviewed issue first (a reviewed issue
# without ``reviewed_at`` last); reviews at the same instant: the issue stored last first.
REVIEWED_ORDER: tuple[SortTerm, ...] = (
    SortTerm("reviewed_at", descending=True, nulls="last"),
    SortTerm("seq", descending=True),
)
# Every review status except pending_review: what "reviewed" means for carrying decisions.
REVIEWED_STATUSES: frozenset[str] = frozenset(
    status.value for status in ReviewStatus if status is not ReviewStatus.PENDING_REVIEW
)

# The finding category has no column: ValidationIssue.finding_category derives it from the
# detector and the rule (app.models.finding_category).
# Filters and counts name it like a column. issue_column_value derives it from these stored
# columns (for the in-memory adapter and the shared count aggregation); the SQL adapter
# renders the same tables as an expression (app.repositories.sql.statements.issue_column).
FINDING_CATEGORY = "finding_category"
FINDING_CATEGORY_SOURCES: tuple[str, ...] = ("detector_id", "rule_id")

# IssueQuery attribute -> issue column it filters on. ``evidence_classes`` deliberately
# matches the *effective* class, so a reviewer-confirmed finding is a human_confirmed_error.
ISSUE_FILTER_COLUMNS: Mapping[str, str] = MappingProxyType(
    {
        "run_id": "validation_run_id",
        "dataset_id": "dataset_id",
        "table_id": "table_id",
        "row_id": "row_id",
        "severities": "severity",
        "evidence_classes": "effective_evidence_class",
        "review_statuses": "review_status",
        "detector_ids": "detector_id",
        "categories": "issue_category",
        "finding_categories": FINDING_CATEGORY,
    }
)

# IssueCounts field -> issue column it tallies.
COUNT_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("by_evidence_class", "effective_evidence_class"),
    ("by_severity", "severity"),
    ("by_review_status", "review_status"),
    ("by_detector", "detector_id"),
    ("by_finding_category", FINDING_CATEGORY),
)
# The stored columns that counts group by: the column of each dimension, the derived finding
# category replaced by the columns it is computed from.
COUNT_COLUMNS: tuple[str, ...] = tuple(
    dict.fromkeys(
        source
        for _, column in COUNT_DIMENSIONS
        for source in (FINDING_CATEGORY_SOURCES if column == FINDING_CATEGORY else (column,))
    )
)

IssueCondition = tuple[str, frozenset[str]]


def issue_conditions(query: IssueQuery) -> list[IssueCondition]:
    """The active filters of ``query`` as ``(column, accepted values)`` pairs.

    Conditions combine with AND; a row passes one condition when its column holds any of the
    accepted values (OR within a filter). ``None`` and empty sets mean "no filter". A query
    attribute without a column mapping raises instead of being silently ignored.
    """
    conditions: list[IssueCondition] = []
    for attribute in fields(query):
        accepted = _accepted_values(getattr(query, attribute.name))
        if not accepted:
            continue
        column = ISSUE_FILTER_COLUMNS.get(attribute.name)
        if column is None:
            raise PersistenceError(
                f"IssueQuery.{attribute.name} has no column mapping, so the repositories "
                "cannot apply it; add it to ISSUE_FILTER_COLUMNS."
            )
        conditions.append((column, accepted))
    return conditions


def finding_category_key(category: FindingCategory | None) -> str:
    """How filters and counts name ``category``: its value, or ``none`` without one."""
    return FindingCategoryKey.NONE.value if category is None else category.value


def issue_column_value(columns: Mapping[str, Any], column: str) -> Any:
    """The value of ``column`` for an issue with these stored ``columns``: the stored value, or
    for :data:`FINDING_CATEGORY` the category key and for :data:`STYLE_FINDING` 1 or 0, both
    derived from its source columns."""
    if column == STYLE_FINDING:
        return int(is_style_finding(detector_id=columns["detector_id"], rule_id=columns["rule_id"]))
    if column != FINDING_CATEGORY:
        return columns[column]
    return finding_category_key(
        finding_category_of(detector_id=columns["detector_id"], rule_id=columns["rule_id"])
    )


def reviewed_conditions(document_id: str, fingerprints: Collection[str]) -> list[IssueCondition]:
    """Conditions selecting every issue of a document that has one of ``fingerprints``
    (evaluated like :func:`issue_conditions`). All review statuses are candidates: the latest
    *decision* wins even when it reset a finding to pending, so a withdrawn decision is never
    resurrected from an older run; :func:`carried_decisions` then drops pending winners."""
    return [
        ("document_id", frozenset({document_id})),
        ("fingerprint", frozenset(fingerprints)),
    ]


def carried_decisions(winners: Mapping[str, ValidationIssue]) -> dict[str, ValidationIssue]:
    """The winners whose latest decision is a review status other than pending."""
    return {
        fingerprint: issue
        for fingerprint, issue in winners.items()
        if issue.review_status.value in REVIEWED_STATUSES
    }


def latest_reviews(
    fingerprints: Collection[str], candidates: Iterable[tuple[str, T]]
) -> dict[str, T]:
    """For each of ``fingerprints`` (in their given order, each once) the first of its
    ``(fingerprint, item)`` candidates; fingerprints without a candidate are left out.

    The candidates must come in :data:`REVIEWED_ORDER`; they may be the concatenation of
    several such sequences as long as each covers its own fingerprints (batched queries).
    """
    first: dict[str, T] = {}
    for fingerprint, item in candidates:
        first.setdefault(fingerprint, item)
    return {fp: first[fp] for fp in dict.fromkeys(fingerprints) if fp in first}


def latest_dataset_key(keys: Iterable[tuple[str, int]]) -> tuple[str, int] | None:
    """``(dataset_id, revision)`` of the latest dataset by creation, at its highest revision.

    ``keys`` are the ``(dataset_id, revision)`` pairs of one document's stored revisions in
    :data:`DATASET_ORDER` (oldest first). A dataset counts as created where its first pair
    appears; ``None`` when ``keys`` is empty.
    """
    created: dict[str, int] = {}  # dataset id -> position of its first stored revision
    highest: dict[str, int] = {}
    for position, (dataset_id, revision) in enumerate(keys):
        created.setdefault(dataset_id, position)
        highest[dataset_id] = max(revision, highest.get(dataset_id, revision))
    if not created:
        return None
    latest = max(created, key=created.__getitem__)
    return latest, highest[latest]


def entity_type_value(entity_type: EntityType | str) -> str:
    """The stored form of an audit entity type; anything that is not an :class:`EntityType`
    (or its value) raises :class:`InvalidInputError` instead of matching nothing."""
    try:
        return EntityType(entity_type).value
    except ValueError:
        raise InvalidInputError(
            f"Unknown audit entity type {entity_type!r}.",
            details={
                "entity_type": str(entity_type),
                "allowed": sorted(member.value for member in EntityType),
            },
        ) from None


def _accepted_values(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str | Enum):
        return frozenset({_as_text(value)})
    if isinstance(value, Iterable):
        return frozenset(_as_text(item) for item in value)
    return frozenset({_as_text(value)})


def _as_text(value: object) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)


def build_issue_counts(groups: Iterable[tuple[Sequence[str], int]]) -> IssueCounts:
    """Fold ``(values per COUNT_COLUMNS, count)`` groups into :class:`IssueCounts`.

    Each mapping holds only the values that occur, with keys in sorted order.
    """
    tallies: dict[str, Counter[str]] = {name: Counter() for name, _ in COUNT_DIMENSIONS}
    total = 0
    for values, count in groups:
        total += count
        columns = dict(zip(COUNT_COLUMNS, values, strict=True))
        for name, column in COUNT_DIMENSIONS:
            tallies[name][issue_column_value(columns, column)] += count
    return IssueCounts(
        total=total,
        by_evidence_class=_sorted_dict(tallies["by_evidence_class"]),
        by_severity=_sorted_dict(tallies["by_severity"]),
        by_review_status=_sorted_dict(tallies["by_review_status"]),
        by_detector=_sorted_dict(tallies["by_detector"]),
        by_finding_category=_sorted_dict(tallies["by_finding_category"]),
    )


def _sorted_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def check_paging(offset: int, limit: int) -> None:
    """Reject negative paging values. Both adapters check, because SQLite would otherwise
    treat a negative LIMIT as "no limit" while PostgreSQL rejects it."""
    if offset < 0:
        raise InvalidInputError(f"offset must be >= 0, got {offset}", details={"offset": offset})
    if limit < 0:
        raise InvalidInputError(f"limit must be >= 0, got {limit}", details={"limit": limit})
