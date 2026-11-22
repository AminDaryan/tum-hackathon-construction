"""deterministic.grand_total: grand totals, tax lines (rate × net) and gross totals."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.errors import DetectorConfigError
from app.models.dataset import Dataset, RowKind
from app.models.finding_category import FindingCategory
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.models.source import SourceKind
from app.validation.contracts.detector import DetectorResult
from app.validation.deterministic.grand_total import GrandTotalConfig, GrandTotalDetector
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, ambiguous_cell, number_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    resolve,
    run,
)

DETECTOR = GrandTotalDetector
RowSpec = tuple[list[Any], dict[str, Any]]


def item(code: str, amount: Any) -> RowSpec:
    return [code, "Position", None, None, None, amount], {}


def line(kind: RowKind, text: str, amount: Any, quantity: Any = None) -> RowSpec:
    return [None, text, quantity, None, None, amount], {"kind": kind}


def net(amount: Any, text: str = "Summe netto") -> RowSpec:
    return line(RowKind.GRAND_TOTAL, text, amount)


def tax(amount: Any, text: str = "zzgl. 19 % MwSt.") -> RowSpec:
    return line(RowKind.TAX, text, amount)


def gross(amount: Any, text: str = "Gesamtsumme brutto") -> RowSpec:
    return line(RowKind.GROSS_TOTAL, text, amount)


def adjustment(amount: Any, text: str = "abzgl. 3 % Nachlass") -> RowSpec:
    return line(RowKind.ADJUSTMENT, text, amount)


def build(profile: DomainProfile, *rows: RowSpec) -> Dataset:
    builder = DatasetBuilder(profile)
    table = builder.table("LV", BOQ_COLUMNS)
    for values, options in rows:
        table.row(values, **options)
    return builder.build()


def check(profile: DomainProfile, *rows: RowSpec, overrides: Any = None) -> DetectorResult:
    return run(DETECTOR, build(profile, *rows), profile, overrides)


BILL = (item("01", "600.00"), item("02", "400.00"))


def test_a_consistent_bill_with_tax_and_gross(boq_profile: DomainProfile) -> None:
    result = check(boq_profile, *BILL, net("1000.00"), tax("190.00"), gross("1190.00"))
    assert result.issues == []
    assert result.coverage["totals_checked"] == 2 and result.coverage["totals_consistent"] == 2
    assert result.coverage["tax_rows_checked"] == 1 and result.coverage["tax_rows_consistent"] == 1


def test_a_grand_total_mismatch(boq_profile: DomainProfile) -> None:
    [issue] = check(boq_profile, *BILL, net("999.00")).issues
    assert issue.rule_id == "grand_total_mismatch"
    assert issue.issue_category is IssueCategory.GRAND_TOTAL
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.HIGH
    assert issue.title == "Grand total 999.00 does not match the sum of its items (1000.00)"
    assert_well_formed([issue])


def test_rows_not_counted_are_named_as_cells(boq_profile: DomainProfile) -> None:
    # The stated total includes the row that does not count: that row is evidence, as a cell.
    optional = (["03", "Position", None, None, None, "50.00"], {"in_totals": False})
    [issue] = check(boq_profile, *BILL, optional, net("1050.00")).issues
    summed, left_out = issue.evidence[1], issue.evidence[2]
    assert summed.label == "Rows summed" and len(summed.cells) == 2
    assert left_out.label == "Not counted" and left_out.data == {"rows": 1}
    assert len(left_out.cells) == 1
    assert left_out.cells[0].row_id not in {c.row_id for c in summed.cells}
    # Without such a row there is no "Not counted" item.
    [plain] = check(boq_profile, *BILL, net("999.00")).issues
    assert [e.label for e in plain.evidence] == ["Sum", "Rows summed"]


def test_totals_after_a_discount(boq_profile: DomainProfile) -> None:
    after_total = check(
        boq_profile,
        item("01", "1000.00"),
        net("1000.00"),
        adjustment("-30.00"),
        net("970.00", "Summe nach Nachlass"),
        tax("184.30"),
        gross("1154.30"),
    )
    assert after_total.issues == []
    assert after_total.coverage["totals_consistent"] == 3
    # The discount written as a positive deduction, with no total after it.
    written = check(
        boq_profile,
        item("01", "1000.00"),
        net("1000.00"),
        adjustment("30.00"),
        tax("184.30"),
        gross("1154.30"),
    )
    assert written.issues == []
    assert any("adjustments after it" in note for note in written.notes)


def test_a_gross_total_worded_as_a_grand_total(boq_profile: DomainProfile) -> None:
    rows = [*BILL, net("1000.00"), tax("190.00")]
    consistent = check(boq_profile, *rows, net("1190.00", "Gesamtsumme"))
    assert consistent.issues == [] and consistent.coverage["totals_consistent"] == 2
    [issue] = check(boq_profile, *rows, net("1200.00", "Gesamtsumme")).issues
    assert issue.rule_id == "grand_total_mismatch" and issue.expected_value == "1190.00"


def test_a_tax_mismatch_is_a_confirmed_violation(boq_profile: DomainProfile) -> None:
    result = check(boq_profile, *BILL, net("1000.00"), tax("180.00"))
    [issue] = result.issues
    assert issue.rule_id == "tax_mismatch"
    assert issue.issue_category is IssueCategory.GRAND_TOTAL
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.title == "Tax 180.00 does not match 19 % of the net total 1000.00 (190.00)"
    calculation = issue.evidence[0].calculation
    assert calculation is not None and calculation.operation == "percentage"
    assert calculation.exact_result == Decimal("190") and calculation.difference == Decimal("-10")
    assert issue.evidence[1].kind is EvidenceKind.REFERENCE
    assert issue.evidence[1].data["rate_percent"] == "19"
    assert len(issue.input_cells) == 1 and issue.estimated_financial_impact is None
    assert result.coverage["tax_rows_inconsistent"] == 1
    assert_well_formed([issue])


def test_tax_impact_with_an_explicit_currency(boq_profile: DomainProfile) -> None:
    eur = {"currency": "EUR"}
    rows = [item("01", number_cell("1000.00", **eur)), net(number_cell("1000.00", **eur))]
    [issue] = check(boq_profile, *rows, tax(number_cell("180.00", **eur))).issues
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.amount == Decimal("-10.00") and impact.currency == "EUR"


def test_tax_rates_in_other_cells_and_formats(boq_profile: DomainProfile) -> None:
    rate_cell = number_cell("0.19", raw="19 %", percent=True)
    in_quantity = line(RowKind.TAX, "Mehrwertsteuer", "190.00", quantity=rate_cell)
    result = check(boq_profile, *BILL, net("1000.00"), in_quantity)
    assert result.issues == [] and result.coverage["tax_rows_consistent"] == 1
    comma = check(boq_profile, *BILL, net("1000.00"), tax("75.00", "zzgl. 7,5 % USt"))
    assert comma.issues == [] and comma.coverage["tax_rows_consistent"] == 1


def test_tax_abstentions(boq_profile: DomainProfile) -> None:
    def coverage(*rows: RowSpec) -> dict[str, int]:
        result = check(boq_profile, *rows)
        assert result.issues == []
        return dict(result.coverage)

    assert (
        coverage(*BILL, net("1000.00"), tax("190.00", "Mehrwertsteuer"))["tax_rows_without_rate"]
        == 1
    )
    assert coverage(*BILL, tax("190.00"))["tax_rows_skipped_no_net"] == 1
    mixed = coverage(
        *BILL, net("1000.00"), tax("21.00", "7 % MwSt."), tax("133.00"), gross("1154.00")
    )
    assert mixed["tax_rows_skipped_mixed_rates"] == 2 and mixed["totals_consistent"] == 2
    assert coverage(*BILL, net("1000.00"), tax(None))["tax_rows_skipped_missing_amount"] == 1
    unreadable = coverage(*BILL, net(ambiguous_cell("1.000")), tax("190.00"))
    assert unreadable["tax_rows_skipped_incomplete"] == 1
    many = [adjustment(str(2**i), "Nachlass") for i in range(13)]
    assert coverage(*BILL, net("1000.00"), *many, tax("1.00"))["tax_rows_skipped_undecided"] == 1


def test_a_gross_total_mismatch(boq_profile: DomainProfile) -> None:
    [issue] = check(boq_profile, *BILL, net("1000.00"), tax("190.00"), gross("1200.00")).issues
    assert issue.rule_id == "gross_total_mismatch"
    assert issue.title == "Gross total 1200.00 does not match the sum of net and tax (1190.00)"
    assert len(issue.input_cells) == 2


def as_delimited_text(dataset: Dataset) -> Dataset:
    """The same bill read from a CSV file, whose amounts may be rounded for display."""
    table = dataset.tables[0]
    return dataset.evolve(
        tables=[table.evolve(source=table.source.evolve(kind=SourceKind.DELIMITED_TEXT))]
    )


def test_display_rounding_in_delimited_text(boq_profile: DomainProfile) -> None:
    printed = [item(f"{i:02d}", "16.67") for i in range(6)]
    dataset = build(boq_profile, *printed, net("100.00"))
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert issue.rule_id == "grand_total_mismatch"  # a spreadsheet: no drift allowance
    assert issue.finding_category is FindingCategory.ERROR
    [issue] = run(DETECTOR, as_delimited_text(dataset), boq_profile).issues
    assert issue.rule_id == "grand_total_display_rounding"
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert issue.finding_category is None  # about reading the file
    dataset = build(boq_profile, *BILL, net("1000.00"), tax("190.00"), gross("1190.02"))
    [issue] = run(DETECTOR, as_delimited_text(dataset), boq_profile).issues
    assert issue.rule_id == "gross_total_display_rounding"
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert issue.finding_category is None


def test_two_structural_readings_that_both_fail(boq_profile: DomainProfile) -> None:
    summary = line(RowKind.SUMMARY_LINE, "Titel 01", "30")
    [issue] = check(boq_profile, item("01", "100"), item("02", "50"), summary, net("999")).issues
    assert issue.rule_id == "grand_total_scope_ambiguous"
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert issue.finding_category is None  # about reading the file


def test_gross_totals_without_net_or_tax_are_not_checked(boq_profile: DomainProfile) -> None:
    no_net = check(boq_profile, *BILL, gross("1190.00"))
    assert no_net.issues == [] and no_net.coverage["totals_skipped_no_scope"] == 1
    assert any("no net total" in note for note in no_net.notes)
    no_tax = check(boq_profile, *BILL, net("1000.00"), gross("1190.00"))
    assert no_tax.issues == [] and no_tax.coverage["totals_skipped_no_scope"] == 1
    assert any("no tax line" in note for note in no_tax.notes)


def test_switches(boq_profile: DomainProfile) -> None:
    rows = [*BILL, net("1000.00"), tax("180.00"), gross("1200.00")]
    assert len(check(boq_profile, *rows).issues) == 2
    no_tax = check(boq_profile, *rows, overrides={"check_tax_lines": False})
    assert [i.rule_id for i in no_tax.issues] == ["gross_total_mismatch"]
    assert "tax_rows_checked" not in no_tax.coverage
    no_gross = check(boq_profile, *rows, overrides={"check_gross_totals": False})
    assert [i.rule_id for i in no_gross.issues] == ["tax_mismatch"]


def test_a_low_confidence_net_downgrades_the_tax_finding(boq_profile: DomainProfile) -> None:
    low = number_cell("1000.00", confidence=0.5)
    [issue] = check(boq_profile, *BILL, net(low), tax("180.00")).issues
    assert issue.rule_id == "tax_mismatch"
    assert issue.effective_evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY


def test_config_applicability_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)  # the boq.yaml defaults validate
    assert config.tolerance.absolute == Decimal("0.01") and config.check_tax_lines
    assert GrandTotalConfig.plannable_parameters() == {
        "total_field",
        "severity",
        "max_reference_cells",
    }
    bad_configs: list[dict[str, Any]] = [
        {"unknown": 1},
        {"tax_rate_pattern": "("},
        {"tax_rate_pattern": r"\d+ %"},
        {"tax_rate_pattern": r"(\d+)\s*(%)"},
    ]
    for bad in bad_configs:
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    assert not applicability(DETECTOR, build(boq_profile, *BILL), boq_profile).applicable
    only_tax = build(boq_profile, *BILL, tax("190.00"))
    assert applicability(DETECTOR, only_tax, boq_profile).applicable
    off = {"check_tax_lines": False}
    assert not applicability(DETECTOR, only_tax, boq_profile, off).applicable
    assert (
        "deterministic.grand_total"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [*BILL, net("999.00"), tax("180.00"), gross("1200.00")]
    first = check(boq_profile, *rows).issues
    second = check(boq_profile, *rows).issues
    assert sorted(i.rule_id for i in first) == [
        "grand_total_mismatch",
        "gross_total_mismatch",
        "tax_mismatch",
    ]
    assert_unique_fingerprints(first)
    assert [i.fingerprint for i in first] == [i.fingerprint for i in second]
