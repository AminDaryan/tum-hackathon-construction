"""Mapping of the tender detectors, their coverage, and the merging of one cause found twice."""

from decimal import Decimal

from app.models.dataset import Dataset
from app.models.issue import ValidationIssue
from app.models.run import DetectorExecutionStatus, DetectorRunReport, ValidationRun
from app.risk.findings import from_findings
from app.risk.grading import grade
from app.risk.models import Certainty, Method, Money, MoneyKind, State
from app.risk.triage import triage
from tests.unit.risk.test_risk_units import TABLES, _bill, _candidate, _position


def _issue(detector_id: str, rule_id: str, observed: str) -> ValidationIssue:
    return ValidationIssue.model_construct(
        detector_id=detector_id,
        rule_id=rule_id,
        observed_value=observed,
        affected_cells=[],
        issue_category="contradiction",
    )


def test_one_cause_found_twice_counts_its_money_once_and_raises_no_certainty() -> None:
    p = _position("01.0010", "PE-Rohr DN 150", "PE-Rohr DN 300", total="1000.00")

    def found(rule: str, certainty: Certainty, amount: int) -> object:
        return _candidate(
            p,
            rule_id=rule,
            risk_type="R049",
            method=Method.ATTRIBUTE_CONSISTENCY,
            certainty=certainty,
            keywords_only=False,
            evidence_keys=frozenset({f"{rule}@{p.key}"}),
            money=Money(kind=MoneyKind.EXACT, amount=Decimal(amount), currency="EUR", basis="b"),
        )

    first = found("C01", Certainty.SUSPECTED, 100)
    second = found("domain.boq_contradictions:spec_conflict", Certainty.SEMANTIC, 80)
    [alone] = grade([first], _bill(p, total="10000.00"), TABLES)
    [merged] = grade([first, second], _bill(p, total="10000.00"), TABLES)
    assert merged.rules == ["C01", "domain.boq_contradictions:spec_conflict"]
    assert merged.money.amount == Decimal(100)  # the larger amount, never 180
    assert merged.factors.independent_signals == 1
    assert (merged.evidence_class, merged.tier, merged.state) == (
        alone.evidence_class,
        alone.tier,
        alone.state,
    )


def test_other_findings_of_different_rules_on_one_position_stay_apart() -> None:
    p = _position("01.0010", "Rohr seperat nach Bedarf")
    typo = _candidate(
        p,
        rule_id="domain.boq_typos:known_misspelling",
        risk_type="other",
        evidence_keys=frozenset({"cell:t1/r01.0010/c2#typo"}),
    )
    blank = _candidate(
        p,
        rule_id="domain.boq_description_clarity:placeholder_text",
        risk_type="other",
        evidence_keys=frozenset({"cell:t1/r01.0010/c2#blank"}),
    )
    assert len(grade([typo, blank], _bill(p), TABLES)) == 2


def test_one_cause_on_two_positions_is_not_merged() -> None:
    a, b = _position("01.0010", "Rohr DN 150"), _position("01.0020", "Rohr DN 150")
    found = [
        _candidate(
            p,
            risk_type="R049",
            evidence_keys=frozenset({f"C01@{p.key}"}),
            stable_key=f"C01|{p.key}",
        )
        for p in (a, b)
    ]
    assert len(grade(found, _bill(a, b), TABLES)) == 2


def _coverage(report: DetectorRunReport | None) -> dict[str, tuple[State, str]]:
    run = ValidationRun.model_construct(detector_reports=[report] if report else [])
    result = from_findings(run, [], Dataset.model_construct(tables=[]), _bill(), TABLES)
    return {
        o.risk_type: (o.state, o.reason)
        for o in result.outcomes
        if o.rule_id == "domain.boq_companion_work"
    }


def _report(status: DetectorExecutionStatus, **kw: object) -> DetectorRunReport:
    return DetectorRunReport.model_construct(
        detector_id="domain.boq_companion_work",
        detector_version="1",
        status=status,
        coverage=kw.pop("coverage", {}),
        skipped_reasons=kw.pop("skipped_reasons", []),
        error=kw.pop("error", None),
    )


def test_coverage_tells_not_run_skipped_failed_nothing_to_check_and_nothing_found_apart() -> None:
    done = DetectorExecutionStatus.COMPLETED
    cases = {
        "not in the plan": (None, "detector not in this run's plan"),
        "skipped": (
            _report(DetectorExecutionStatus.SKIPPED, skipped_reasons=["no long text"]),
            "detector skipped: no long text",
        ),
        "failed": (_report(DetectorExecutionStatus.FAILED, error="boom"), "detector failed: boom"),
        "nothing to check": (
            _report(done, coverage={"rows_skipped_missing_inputs": 3}),
            "the detector ran but had nothing to check",
        ),
        "stopped": (
            _report(DetectorExecutionStatus.STOPPED, coverage={"items_read": 4}),
            "the detector stopped at its time limit",
        ),
    }
    for name, (report, reason) in cases.items():
        rows = _coverage(report)
        assert set(rows) == {"R005", "R010", "other"}
        assert all(state is State.NOT_CHECKABLE for state, _ in rows.values()), name
        assert all(text.startswith(reason) for _, text in rows.values()), (name, rows)
    clean = _coverage(_report(done, coverage={"items_read": 12}))
    assert all(state is State.COVERED for state, _ in clean.values())
    assert all("items_read 12" in text for _, text in clean.values())


def test_a_typo_or_catch_all_wording_alone_stays_in_the_check_record() -> None:
    # Grading 0.6 (owner's request): neither takes a main-list place, even on a structural
    # position; with a rule of the risk checks on the same reminder the usual tier applies.
    p = _position("02.0010", "Stahlbeton Fundament komplett herstellen", "Bewehrung seperat")

    def found(rule: str, risk_type: str) -> object:
        return _candidate(
            p,
            rule_id=rule,
            risk_type=risk_type,
            evidence_keys=frozenset({f"{rule}@{p.key}"}),
            stable_key=f"{rule}|{p.key}",
        )

    typo = found("domain.boq_typos:known_misspelling", "other")
    catch_all = found("domain.boq_description_clarity:catch_all_wording", "R037")
    risks = grade([typo, catch_all], _bill(p), TABLES)
    assert sorted((r.tier_rule, r.tier.value) for r in risks) == [("T07c", "low"), ("T07d", "low")]
    main, record, _ = triage(risks, TABLES)
    assert main == [] and len(record) == 2
    [both] = grade([catch_all, found("V02", "R037")], _bill(p), TABLES)
    assert both.tier_rule == "T08"
    assert [r.risk_id for r in triage([both], TABLES)[0]] == [both.risk_id]
