"""Synthetic evidence, no project documents."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from app.models.dataset import Dataset
from app.models.issue import EvidenceItem, EvidenceKind, ValidationIssue
from app.models.profile import DomainProfile
from app.models.run import ValidationRun
from app.risk.bill import read_bill
from app.risk.findings import from_findings
from app.risk.grading import grade
from app.risk.tables import RiskTables
from app.validation.deterministic.line_total import LineTotalDetector
from tests.support.builders import make_context, unit_cell
from tests.unit.risk.test_risk_checks import TABLES, _bill, _issue, _p
from tests.unit.validation.deterministic.references_fixtures import boq_dataset, run_pipeline
from tests.unit.validation.deterministic.test_line_total import _bid, _bid_warning, _eur, _item


def _tables(pricing: bool) -> RiskTables:
    # Test a nonpricing mapping only; the real R076 stays a pricing risk.
    if pricing:
        return TABLES
    types = [
        risk.model_copy(update={"category": "other"}) if risk.id == "R076" else risk
        for risk in TABLES.catalogue.risk_types
    ]
    return dataclasses.replace(
        TABLES, catalogue=TABLES.catalogue.model_copy(update={"risk_types": types})
    )


def _evidence(**changes: Any) -> EvidenceItem:
    data = {"prevails": "unit_price", "corrected_line_total": "315.00"}
    data.update(changes)
    return EvidenceItem(
        kind=EvidenceKind.RULE, label="Stored rule", detail="Rule used in this check.", data=data
    )


def _finding(evidence: list[EvidenceItem], **changes: Any) -> ValidationIssue:
    return _issue(
        1,
        detector_id="deterministic.line_total",
        rule_id="line_total_mismatch",
        issue_category="arithmetic",
        observed_value="65.00",
        expected_value="315.00",
        evidence=evidence,
        **changes,
    )


def _risk(issue: ValidationIssue, pricing: bool = False) -> Any:
    tables = _tables(pricing)
    bill = _bill(_p("1", "Synthetic panel"))
    candidates = from_findings(
        ValidationRun.model_construct(detector_reports=[]),
        [issue],
        Dataset.model_construct(tables=[]),
        bill,
        tables,
    ).candidates
    return grade(candidates, bill, tables)[0]


@pytest.mark.parametrize("pricing", [True, False])
def test_stored_unit_price_rule_requests_confirmation_without_deciding_a_typo(
    pricing: bool,
) -> None:
    question = _risk(_finding([_evidence()]), pricing).question
    assert question is not None
    assert "unit price" in question.lower() and "confirm" in question.lower()
    assert "rule" in question.lower() and "check" in question.lower()
    assert "Which value applies?" not in question
    assert "VOB" not in question and "§" not in question
    assert "typo" not in question and "confirmed" not in question.lower()
    if pricing:
        assert "315" not in question and "65" not in question
    else:
        assert "315.00" in question and "65.00" not in question


@pytest.mark.parametrize(
    "evidence",
    [
        [],
        [_evidence(prevails="none")],
        [_evidence(prevails=None)],
        [_evidence(corrected_line_total=None)],
        [_evidence(corrected_line_total="not a number")],
        [_evidence(corrected_line_total="NaN")],
        [_evidence(corrected_line_total="Infinity")],
        [_evidence(corrected_line_total=True)],
        [_evidence().model_copy(update={"kind": EvidenceKind.NOTE})],
        [_evidence(), _evidence(prevails="stated_amount", corrected_line_total="65.00")],
    ],
)
@pytest.mark.parametrize("pricing", [True, False])
def test_missing_or_invalid_rules_keep_the_existing_neutral_question(
    evidence: list[EvidenceItem],
    pricing: bool,
) -> None:
    question = _risk(_finding(evidence), pricing).question
    if pricing:
        assert question is None
    else:
        assert question == "1: the bill shows 65.00, the check expects 315.00. Which value applies?"


@pytest.mark.parametrize(
    ("prevails", "corrected", "required"),
    [
        ("stated_amount", "65.00", "lump sum"),
        ("unit_price_unless_lump_sum", "315.00", "unless"),
    ],
)
@pytest.mark.parametrize("pricing", [True, False])
def test_lump_sum_exception_and_uncertainty_are_preserved(
    prevails: str,
    corrected: str,
    required: str,
    pricing: bool,
) -> None:
    question = _risk(
        _finding([_evidence(prevails=prevails, corrected_line_total=corrected)]), pricing
    ).question
    assert question is not None and required in question.lower()
    assert "confirm" in question.lower() and "lump sum" in question.lower()
    if pricing:
        assert "315" not in question and "65" not in question
    else:
        assert corrected in question
    if prevails == "stated_amount":
        assert "315.00" not in question


def test_other_checks_do_not_reuse_a_line_total_rule() -> None:
    issue = _finding([_evidence()]).model_copy(
        update={"detector_id": "deterministic.exact_duplicates"}
    )
    question = _risk(issue).question
    assert question == "1: the bill shows 65.00, the check expects 315.00. Which value applies?"


def test_only_the_question_changes_risk_identity_amount_grading_and_review_matching() -> None:
    issue = _finding([_evidence()])
    before = _risk(issue.model_copy(update={"evidence": []}))
    after = _risk(issue)
    assert before.question != after.question
    assert before.model_dump(exclude={"question"}) == after.model_dump(exclude={"question"})
    assert before.risk_id == after.risk_id and before.source_issue_ids == after.source_issue_ids


@pytest.mark.parametrize(
    ("quantity", "price", "total", "expected", "bid"),
    [
        ("5", "63.00", "65.00", "315.00", False),
        ("3", "19.75", "60.00", "59.25", False),
        ("4", "-7.50", "-29.00", "-30.00", True),
    ],
)
def test_real_detector_evidence_reaches_the_graded_risk_without_recalculation(
    boq_profile: DomainProfile,
    quantity: str,
    price: str,
    total: str,
    expected: str,
    bid: bool,
) -> None:
    rows = [_item(quantity, _eur(price), _eur(total))]
    dataset = _bid(boq_profile, rows, _bid_warning()) if bid else boq_dataset(boq_profile, rows)
    result = run_pipeline(LineTotalDetector, dataset, boq_profile)
    [issue] = result.issues
    [evidence] = [e for e in issue.evidence if "prevails" in e.data]
    assert evidence.data["corrected_line_total"] == expected
    bill = read_bill(make_context(dataset, boq_profile), TABLES.components)
    for pricing in (False, True):
        tables = _tables(pricing)
        candidates = from_findings(
            ValidationRun.model_construct(detector_reports=result.reports),
            [issue],
            dataset,
            bill,
            tables,
        ).candidates
        [risk] = grade(candidates, bill, tables)
        assert risk.question and "confirm" in risk.question.lower()
        if pricing:
            assert expected not in risk.question and total not in risk.question
        else:
            assert expected in risk.question
        if bid:
            assert "unless" in risk.question.lower() and "lump sum" in risk.question.lower()


@pytest.mark.parametrize("pricing", [False, True])
def test_free_text_cannot_supply_or_override_the_saved_rule(pricing: bool) -> None:
    # Prose and language cannot supply a rule.
    prose = "The unit price prevails under VOB/A; internal offer 54321.99 EUR. {positions}"
    without_rule = _finding([], explanation=prose)
    baseline = _risk(without_rule, pricing).question
    assert baseline is None if pricing else "Which value applies?" in baseline
    saved_rule = _evidence().model_copy(update={"detail": prose, "label": "Regel dieser Prüfung"})
    question = _risk(_finding([saved_rule]), pricing).question
    assert question and "confirm" in question.lower()
    assert all(text not in question for text in ("54321.99", "VOB/A", "{positions}", "Regel"))


@pytest.mark.parametrize("wrong", ["tax_mismatch", "unit_factor_unknown"])
def test_another_rule_of_the_same_detector_stays_neutral(wrong: str) -> None:
    issue = _finding([_evidence()]).model_copy(update={"rule_id": wrong})
    assert "Which value applies?" in _risk(issue).question


@pytest.mark.parametrize("amount", ["", "-Infinity", "sNaN", "1e999999", "0.000" + "1" * 121])
def test_additional_unusable_amount_spellings_do_not_break_report_generation(amount: str) -> None:
    question = _risk(_finding([_evidence(corrected_line_total=amount)])).question
    assert question and question.endswith("Which value applies?")


@pytest.mark.parametrize(
    ("quantity", "price", "total", "unit", "expected", "prevails"),
    [
        ("0", "99.99", "10.01", "m3", "0.00", "unit_price"),
        ("3", "100.00", "250.00", "ls", "250.00", "stated_amount"),
    ],
)
def test_zero_and_explicit_lump_sum_use_the_stored_total_on_another_position(
    boq_profile: DomainProfile,
    quantity: str,
    price: str,
    total: str,
    unit: str,
    expected: str,
    prevails: str,
) -> None:
    # Vary boundaries, position and table name.
    dataset = boq_dataset(
        boq_profile,
        [_item(quantity, _eur(price), _eur(total), unit_cell(unit, unit), code="09.700")],
        name="Synthetic revised schedule",
    )
    result = run_pipeline(LineTotalDetector, dataset, boq_profile)
    [issue] = result.issues
    [stored] = [e for e in issue.evidence if "prevails" in e.data]
    assert stored.data["prevails"] == prevails
    assert stored.data["corrected_line_total"] == expected
    bill = read_bill(make_context(dataset, boq_profile), TABLES.components)
    tables = _tables(False)
    found = from_findings(
        ValidationRun.model_construct(detector_reports=result.reports),
        [issue],
        dataset,
        bill,
        tables,
    )
    [risk] = grade(found.candidates, bill, tables)
    assert risk.question and "09.700" in risk.question and expected in risk.question
    assert "confirm" in risk.question.lower()
    if prevails == "stated_amount":
        assert "lump sum" in risk.question.lower() and "300.00" not in risk.question
