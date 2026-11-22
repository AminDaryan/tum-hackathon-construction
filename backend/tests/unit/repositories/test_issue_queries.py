"""IssueRepository on both adapters: storage, filters (OR within, AND across), counts, the
effective evidence class after a review decision and the computed finding category."""

from __future__ import annotations

import itertools

import pytest

from app.core.errors import NotFoundError
from app.models.finding_category import CATEGORY_BY_DETECTOR, CATEGORY_BY_RULE, FindingCategoryKey
from app.models.issue import EvidenceClass, ReviewStatus, Severity
from app.repositories.base import IssueCounts, IssueQuery, UnitOfWorkFactory
from app.repositories.errors import IntegrityViolationError
from app.repositories.querying import finding_category_key
from tests.unit.repositories.samples import make_issue, make_run, minutes

RUN_A, RUN_B = "run_a", "run_b"
CONFIRMED = EvidenceClass.CONFIRMED_RULE_VIOLATION
SUSPECTED = EvidenceClass.SUSPECTED_ANOMALY
SEMANTIC = EvidenceClass.SEMANTIC_WARNING
EXTRACTION = EvidenceClass.EXTRACTION_UNCERTAINTY
HUMAN = EvidenceClass.HUMAN_CONFIRMED_ERROR

ISSUES = [
    make_issue("iss_01", run_id=RUN_A, severity=Severity.HIGH, evidence_class=CONFIRMED,
               detector_id="test.alpha", category="arithmetic", table_id="tbl_1", row_id="row_1"),
    make_issue("iss_02", run_id=RUN_A, severity=Severity.MEDIUM, evidence_class=SUSPECTED,
               detector_id="test.beta", category="statistical_outlier", table_id="tbl_1",
               row_id="row_2"),
    make_issue("iss_03", run_id=RUN_A, severity=Severity.LOW, evidence_class=SEMANTIC,
               detector_id="test.alpha", category="semantic", table_id="tbl_2", row_id="row_3"),
    make_issue("iss_04", run_id=RUN_A, severity=Severity.CRITICAL, evidence_class=EXTRACTION,
               detector_id="test.gamma", category="extraction", table_id="tbl_2", row_id=None),
    make_issue("iss_05", run_id=RUN_A, severity=Severity.HIGH, evidence_class=CONFIRMED,
               review_status=ReviewStatus.FALSE_POSITIVE, detector_id="test.beta",
               category="arithmetic", table_id="tbl_1", row_id="row_1"),
    make_issue("iss_06", run_id=RUN_B, dataset_id="ds_other", severity=Severity.HIGH,
               evidence_class=CONFIRMED, detector_id="test.alpha", category="arithmetic",
               table_id="tbl_9", row_id="row_9"),
]  # fmt: skip
ALL = {issue.issue_id for issue in ISSUES}
IN_RUN_A = ALL - {"iss_06"}


def _store_issues(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.runs.add(make_run(RUN_A))
        uow.runs.add(make_run(RUN_B, dataset_id="ds_other", started_at=minutes(1)))
        uow.issues.add_many(ISSUES)


def _matches(factory: UnitOfWorkFactory, query: IssueQuery) -> set[str]:
    """Matching ids, after checking that query(), counts() and iter_all() agree."""
    with factory() as uow:
        page = uow.issues.query(query, limit=100)
        counts = uow.issues.counts(query)
        iterated = [issue.issue_id for issue in uow.issues.iter_all(query)]
    ids = [issue.issue_id for issue in page.items]
    assert page.total == len(ids) == counts.total == len(iterated)
    assert iterated == ids
    return set(ids)


def f(*values) -> frozenset:
    return frozenset(values)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param(IssueQuery(), ALL, id="no-filter"),
        pytest.param(IssueQuery(run_id=RUN_A), IN_RUN_A, id="run"),
        pytest.param(IssueQuery(dataset_id="ds_other"), {"iss_06"}, id="dataset"),
        pytest.param(IssueQuery(table_id="tbl_2"), {"iss_03", "iss_04"}, id="table"),
        pytest.param(IssueQuery(row_id="row_1"), {"iss_01", "iss_05"}, id="row"),
        pytest.param(
            IssueQuery(severities=f(Severity.HIGH)), {"iss_01", "iss_05", "iss_06"}, id="severity"
        ),
        pytest.param(IssueQuery(evidence_classes=f(SEMANTIC)), {"iss_03"}, id="evidence-class"),
        pytest.param(
            IssueQuery(review_statuses=f(ReviewStatus.FALSE_POSITIVE)), {"iss_05"}, id="review"
        ),
        pytest.param(IssueQuery(detector_ids=f("test.gamma")), {"iss_04"}, id="detector"),
        pytest.param(IssueQuery(categories=f("semantic")), {"iss_03"}, id="category"),
    ],
)
def test_each_filter_alone(uow_factory: UnitOfWorkFactory, query: IssueQuery, expected) -> None:
    _store_issues(uow_factory)
    assert _matches(uow_factory, query) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param(
            IssueQuery(severities=f(Severity.HIGH, Severity.LOW)),
            {"iss_01", "iss_03", "iss_05", "iss_06"},
            id="severity",
        ),
        pytest.param(
            IssueQuery(evidence_classes=f(SUSPECTED, EXTRACTION)), {"iss_02", "iss_04"}, id="class"
        ),
        pytest.param(
            IssueQuery(review_statuses=f(ReviewStatus.PENDING_REVIEW, ReviewStatus.FALSE_POSITIVE)),
            ALL,
            id="review",
        ),
        pytest.param(
            IssueQuery(detector_ids=f("test.beta", "test.gamma")),
            {"iss_02", "iss_04", "iss_05"},
            id="detector",
        ),
        pytest.param(
            IssueQuery(categories=f("arithmetic", "semantic")),
            {"iss_01", "iss_03", "iss_05", "iss_06"},
            id="category",
        ),
    ],
)
def test_values_within_one_filter_combine_with_or(
    uow_factory: UnitOfWorkFactory, query: IssueQuery, expected
) -> None:
    _store_issues(uow_factory)
    assert _matches(uow_factory, query) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        pytest.param(
            IssueQuery(run_id=RUN_A, severities=f(Severity.HIGH)), {"iss_01", "iss_05"}, id="2"
        ),
        pytest.param(
            IssueQuery(
                run_id=RUN_A,
                severities=f(Severity.HIGH, Severity.LOW),
                detector_ids=f("test.alpha"),
            ),
            {"iss_01", "iss_03"},
            id="3",
        ),
        pytest.param(
            IssueQuery(
                run_id=RUN_A,
                severities=f(Severity.HIGH),
                review_statuses=f(ReviewStatus.PENDING_REVIEW),
            ),
            {"iss_01"},
            id="review",
        ),
        pytest.param(
            IssueQuery(table_id="tbl_1", categories=f("arithmetic"), detector_ids=f("test.beta")),
            {"iss_05"},
            id="location",
        ),
        pytest.param(
            IssueQuery(run_id=RUN_A, table_id="tbl_2", evidence_classes=f(EXTRACTION)),
            {"iss_04"},
            id="class",
        ),
        pytest.param(IssueQuery(run_id=RUN_B, table_id="tbl_1"), set(), id="disjoint"),
        pytest.param(
            IssueQuery(run_id=RUN_A, severities=frozenset(), detector_ids=frozenset()),
            IN_RUN_A,
            id="empty-sets-are-no-filter",
        ),
    ],
)
def test_filters_combine_with_and(
    uow_factory: UnitOfWorkFactory, query: IssueQuery, expected
) -> None:
    _store_issues(uow_factory)
    assert _matches(uow_factory, query) == expected


def test_review_confirmation_makes_the_effective_class_human_confirmed(
    uow_factory: UnitOfWorkFactory,
) -> None:
    _store_issues(uow_factory)
    with uow_factory() as uow:
        suspected = uow.issues.get("iss_02")
        assert suspected is not None
        uow.issues.update(
            suspected.with_review(
                ReviewStatus.CONFIRMED_ERROR, "Rate is ten times the market price.", at=minutes(30)
            ),
            expected_version=1,
        )
    with uow_factory() as uow:
        stored = uow.issues.get("iss_02")
        assert stored is not None
        assert stored.evidence_class is SUSPECTED  # the detector's claim is kept
        assert stored.effective_evidence_class is HUMAN
        assert stored.version == 2
    assert _matches(uow_factory, IssueQuery(evidence_classes=f(HUMAN))) == {"iss_02"}
    assert _matches(uow_factory, IssueQuery(evidence_classes=f(SUSPECTED))) == set()
    assert _matches(uow_factory, IssueQuery(review_statuses=f(ReviewStatus.CONFIRMED_ERROR))) == {
        "iss_02"
    }
    with uow_factory() as uow:
        counts = uow.issues.counts(IssueQuery(run_id=RUN_A))
    assert counts.by_evidence_class == {
        "confirmed_rule_violation": 2,
        "extraction_uncertainty": 1,
        "human_confirmed_error": 1,
        "semantic_warning": 1,
    }
    assert counts.by_review_status == {
        "confirmed_error": 1,
        "false_positive": 1,
        "pending_review": 3,
    }

    with uow_factory() as uow:  # back to pending: the detector's class applies again
        uow.issues.update(
            stored.with_review(ReviewStatus.PENDING_REVIEW, None, at=minutes(31)),
            expected_version=2,
        )
    assert _matches(uow_factory, IssueQuery(evidence_classes=f(SUSPECTED))) == {"iss_02"}


def test_the_change_mark_moves_with_every_review(uow_factory: UnitOfWorkFactory) -> None:
    _store_issues(uow_factory)
    with uow_factory() as uow:
        before = uow.issues.change_mark(IssueQuery(run_id=RUN_A))
        assert uow.issues.change_mark(IssueQuery(run_id="run_unknown")) == (0, 0)
        issue = uow.issues.get("iss_02")
        assert issue is not None
        uow.issues.update(
            issue.with_review(ReviewStatus.FALSE_POSITIVE, None, at=minutes(30)),
            expected_version=1,
        )
    with uow_factory() as uow:
        after = uow.issues.change_mark(IssueQuery(run_id=RUN_A))
        other_run = uow.issues.change_mark(IssueQuery(run_id=RUN_B))
    assert before == (5, 5)
    assert after == (5, 6)
    assert other_run == (1, 1)


def test_counts_tally_every_dimension(uow_factory: UnitOfWorkFactory) -> None:
    _store_issues(uow_factory)
    with uow_factory() as uow:
        counts = uow.issues.counts(IssueQuery(run_id=RUN_A))
        high = uow.issues.counts(IssueQuery(run_id=RUN_A, severities=f(Severity.HIGH)))
        nothing = uow.issues.counts(IssueQuery(run_id="run_unknown"))
    assert counts == IssueCounts(
        total=5,
        by_evidence_class={
            "confirmed_rule_violation": 2,
            "extraction_uncertainty": 1,
            "semantic_warning": 1,
            "suspected_anomaly": 1,
        },
        by_severity={"critical": 1, "high": 2, "low": 1, "medium": 1},
        by_review_status={"false_positive": 1, "pending_review": 4},
        by_detector={"test.alpha": 2, "test.beta": 2, "test.gamma": 1},
        by_finding_category={"none": 5},  # test detectors have no category
    )
    assert list(counts.by_severity) == sorted(counts.by_severity)  # deterministic key order
    assert high == IssueCounts(
        total=2,
        by_evidence_class={"confirmed_rule_violation": 2},
        by_severity={"high": 2},
        by_review_status={"false_positive": 1, "pending_review": 1},
        by_detector={"test.alpha": 1, "test.beta": 1},
        by_finding_category={"none": 2},
    )
    assert nothing == IssueCounts()


# ------------------------------------------------------------------ finding categories
# Findings of real detectors: the finding category is computed from the detector and the rule
# (no column, never read back; the evidence class does not change it), and both adapters filter
# and count by it.
UNIT_RULES = "deterministic.unit_compatibility"
CATEGORY_ISSUES = [
    make_issue("cat_01", run_id=RUN_A, detector_id="deterministic.line_total",
               rule_id="line_total_mismatch"),  # error
    make_issue("cat_02", run_id=RUN_A, detector_id=UNIT_RULES,
               rule_id="same_description_dimension", evidence_class=SEMANTIC),  # by its rule
    make_issue("cat_03", run_id=RUN_A, detector_id=UNIT_RULES, rule_id="fractional_count",
               evidence_class=SEMANTIC, severity=Severity.HIGH),  # error, by its detector
    make_issue("cat_04", run_id=RUN_A, detector_id="deterministic.reference_integrity",
               rule_id="german_position_reference",
               evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT),  # ambiguity
    make_issue("cat_05", run_id=RUN_A, detector_id="deterministic.line_total",
               rule_id="line_total_mismatch",
               evidence_class=EXTRACTION),  # downgraded (a PDF value): still an error
    make_issue("cat_06", run_id=RUN_A, detector_id="deterministic.formula_errors",
               rule_id="formula_result_unavailable"),  # none by its rule, whatever the class
    make_issue("cat_07", run_id=RUN_A, detector_id="deterministic.exact_duplicates",
               rule_id="exact_duplicate",
               review_status=ReviewStatus.CONFIRMED_ERROR),  # a review keeps the category
    make_issue("cat_08", run_id=RUN_A, detector_id="test.alpha"),  # unknown detector: none
    make_issue("cat_09", run_id=RUN_B, dataset_id="ds_other",
               detector_id="deterministic.line_total", rule_id="line_total_mismatch"),
    make_issue("cat_10", run_id=RUN_A, detector_id="deterministic.subtotal",
               rule_id="subtotal_display_rounding",
               evidence_class=EXTRACTION),  # reading the file: none by its rule
]  # fmt: skip
NO_CATEGORY = FindingCategoryKey.NONE


def _store_category_issues(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        uow.runs.add(make_run(RUN_A))
        uow.runs.add(make_run(RUN_B, dataset_id="ds_other", started_at=minutes(1)))
        uow.issues.add_many(CATEGORY_ISSUES)


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        pytest.param(f(FindingCategoryKey.ERROR), {"cat_01", "cat_03", "cat_05"}, id="error"),
        pytest.param(f(FindingCategoryKey.INCONSISTENCY), {"cat_02", "cat_07"}, id="rule-entry"),
        pytest.param(f(FindingCategoryKey.AMBIGUITY), {"cat_04"}, id="ambiguity"),
        pytest.param(f(NO_CATEGORY), {"cat_06", "cat_08", "cat_10"}, id="none"),
        pytest.param(f(FindingCategoryKey.RISK), set(), id="absent"),
        pytest.param(
            f(FindingCategoryKey.ERROR, NO_CATEGORY),
            {"cat_01", "cat_03", "cat_05", "cat_06", "cat_08", "cat_10"},
            id="or-within",
        ),
    ],
)
def test_the_finding_category_filter(
    uow_factory: UnitOfWorkFactory, keys: frozenset[FindingCategoryKey], expected: set[str]
) -> None:
    _store_category_issues(uow_factory)
    query = IssueQuery(run_id=RUN_A, finding_categories=keys)
    assert _matches(uow_factory, query) == expected
    with uow_factory() as uow:
        page = uow.issues.query(query)
    for issue in page.items:
        assert finding_category_key(issue.finding_category) in keys


def test_the_finding_category_filter_combines_with_and(uow_factory: UnitOfWorkFactory) -> None:
    _store_category_issues(uow_factory)
    error = f(FindingCategoryKey.ERROR)
    assert _matches(uow_factory, IssueQuery(finding_categories=error)) == {
        "cat_01",
        "cat_03",
        "cat_05",
        "cat_09",
    }
    assert _matches(
        uow_factory, IssueQuery(run_id=RUN_A, finding_categories=error, severities=f(Severity.HIGH))
    ) == {"cat_03"}
    assert _matches(
        uow_factory, IssueQuery(finding_categories=error, detector_ids=f(UNIT_RULES))
    ) == {"cat_03"}
    assert _matches(uow_factory, IssueQuery(run_id=RUN_B, finding_categories=error)) == {"cat_09"}


def test_counts_tally_finding_categories(uow_factory: UnitOfWorkFactory) -> None:
    _store_category_issues(uow_factory)
    with uow_factory() as uow:
        counts = uow.issues.counts(IssueQuery(run_id=RUN_A))
        errors = uow.issues.counts(
            IssueQuery(run_id=RUN_A, finding_categories=f(FindingCategoryKey.ERROR))
        )
    assert counts.total == 9
    assert counts.by_finding_category == {
        "ambiguity": 1,
        "error": 3,
        "inconsistency": 2,
        "none": 3,
    }
    assert list(counts.by_finding_category) == sorted(counts.by_finding_category)
    assert errors.by_finding_category == {"error": 3}
    assert errors.by_detector == {"deterministic.line_total": 2, UNIT_RULES: 1}


def test_every_detector_rule_and_class_gets_the_same_category_on_every_adapter(
    uow_factory: UnitOfWorkFactory,
) -> None:
    """The SQL expression and the Python function agree for every entry of both tables, with
    each evidence class a detector can claim (none of them changes the category), and for a
    detector the tables do not know."""
    pairs = [(detector_id, "default") for detector_id in CATEGORY_BY_DETECTOR]
    pairs += [*CATEGORY_BY_RULE, ("test.unknown_probe", "default")]
    claimable = [c for c in EvidenceClass if c is not HUMAN]
    issues = [
        make_issue(
            f"iss_{number:03d}",
            run_id=RUN_A,
            detector_id=detector_id,
            rule_id=rule_id,
            evidence_class=evidence_class,
        )
        for number, ((detector_id, rule_id), evidence_class) in enumerate(
            itertools.product(pairs, claimable)
        )
    ]
    with uow_factory() as uow:
        uow.runs.add(make_run(RUN_A))
        uow.issues.add_many(issues)
    expected: dict[str, set[str]] = {key.value: set() for key in FindingCategoryKey}
    for issue in issues:
        expected[finding_category_key(issue.finding_category)].add(issue.issue_id)
    for key in FindingCategoryKey:
        assert _matches(uow_factory, IssueQuery(finding_categories=f(key))) == expected[key]
    with uow_factory() as uow:
        counts = uow.issues.counts(IssueQuery(run_id=RUN_A))
    assert counts.by_finding_category == {
        key: len(ids) for key, ids in sorted(expected.items()) if ids
    }
    assert sum(counts.by_finding_category.values()) == len(issues)


def test_add_many_then_get(uow_factory: UnitOfWorkFactory) -> None:
    _store_issues(uow_factory)
    with uow_factory() as uow:
        uow.issues.add_many([])  # a no-op, not an error
        assert [uow.issues.get(issue.issue_id) for issue in ISSUES] == ISSUES
        assert uow.issues.get("iss_unknown") is None


def test_duplicate_issue_ids_are_refused_and_nothing_is_stored(
    uow_factory: UnitOfWorkFactory,
) -> None:
    with uow_factory() as uow:
        uow.runs.add(make_run(RUN_A))
    batch = [make_issue("iss_x", run_id=RUN_A), make_issue("iss_x", run_id=RUN_A)]
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.issues.add_many(batch)
    with uow_factory() as uow:
        assert uow.issues.get("iss_x") is None
        uow.issues.add_many(batch[:1])
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.issues.add_many(batch[1:])


def test_an_issue_requires_its_validation_run(uow_factory: UnitOfWorkFactory) -> None:
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.issues.add_many([make_issue("iss_orphan", run_id="run_missing")])


def test_update_checks_existence_and_the_run_reference(uow_factory: UnitOfWorkFactory) -> None:
    _store_issues(uow_factory)
    with pytest.raises(NotFoundError, match="iss_unknown"), uow_factory() as uow:
        uow.issues.update(
            make_issue("iss_unknown", run_id=RUN_A).evolve(version=2), expected_version=1
        )
    moved = ISSUES[0].evolve(validation_run_id="run_missing", version=2)
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.issues.update(moved, expected_version=1)
    with uow_factory() as uow:
        assert uow.issues.get(ISSUES[0].issue_id) == ISSUES[0]
