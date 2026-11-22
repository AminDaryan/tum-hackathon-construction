"""deterministic.unit_price_components: the components of a unit price add up to it."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.clock import FixedClock
from app.core.config import IngestionLimits
from app.core.errors import DetectorConfigError
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.adapter import Gaeb90Adapter, GaebAdapter
from app.models.dataset import Dataset, ExtractionWarning
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.models.values import ValueMarker
from app.normalization.builder import build_dataset
from app.validation.deterministic.unit_price_components import (
    RULE_COMPONENT_SUM,
    UnitPriceComponentsConfig,
    UnitPriceComponentsDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import (
    DatasetBuilder,
    ambiguous_cell,
    marker_cell,
    number_cell,
    unit_cell,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    resolve,
    run,
)

DETECTOR = UnitPriceComponentsDetector
COLUMNS = [
    *BOQ_COLUMNS,
    ("Lohn", "unit_price_component_1"),
    ("Stoffe", "unit_price_component_2"),
    ("Geräte", "unit_price_component_3"),
]
GAEB_FIXTURES = Path(__file__).parents[3] / "fixtures" / "gaeb"
GAEB_RULE = "Die Summe der Einheitspreisanteile einer Position muss den Einheitspreis ergeben."


def _item(price: Any, *components: Any, code: str = "01") -> list[Any]:
    parts = [*components, *([None] * (3 - len(components)))]
    return [code, "Mauerwerk", "10", unit_cell("m2", "m2"), price, None, *parts]


def _run(profile: DomainProfile, rows: list[list[Any]], overrides: Any = None) -> Any:
    return run(DETECTOR, boq_dataset(profile, rows, columns=COLUMNS), profile, overrides)


def test_components_that_add_up(boq_profile: DomainProfile) -> None:
    rows = [
        _item("9.77", "5.00", "4.77", code="01"),
        _item("40.00", "22.10", "12.40", "5.50", code="02"),
        _item("12.5", "12.5", code="03"),  # one component is the whole price
        _item("8.00", "8.00", "0", code="04"),  # a zero share
    ]
    result = _run(boq_profile, rows)
    assert result.issues == []
    assert result.coverage["rows_checked"] == 4 and result.coverage["rows_consistent"] == 4


def test_a_difference_is_a_confirmed_violation(boq_profile: DomainProfile) -> None:
    eur = {"currency": "EUR"}
    row = _item(number_cell("9.77", **eur), number_cell("5.00", **eur), "4.80")
    result = _run(boq_profile, [row])
    [issue] = result.issues
    assert result.coverage["rows_inconsistent"] == 1
    assert issue.rule_id == RULE_COMPONENT_SUM
    assert issue.issue_category is IssueCategory.ARITHMETIC
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.MEDIUM
    assert issue.title == "Components of the Unit price add up to 9.80, not 9.77"
    assert (issue.observed_value, issue.expected_value) == ("9.80", "9.77")
    assert issue.explanation.startswith(
        "'LV' row 2: Unit price component 1 5.00 + Unit price component 2 4.80 = 9.80, but the "
        "Unit price is 9.77 (difference -0.03)."
    )
    assert "The bill's total does not change" in issue.explanation
    # The unit price and both components are highlighted (the planted cell can be either).
    assert len(issue.affected_cells) == 3 and issue.input_cells == []
    assert issue.estimated_financial_impact is None  # the unit price is what the bid offers
    [calculation_item, rule] = issue.evidence
    calculation = calculation_item.calculation
    assert calculation_item.kind is EvidenceKind.CALCULATION and calculation is not None
    assert calculation.operation == "sum" and calculation.terms == 2
    assert [o.value for o in calculation.operands] == [Decimal("5.00"), Decimal("4.80")]
    assert calculation.exact_result == Decimal("9.80") and calculation.reported == Decimal("9.77")
    assert calculation.difference == Decimal("-0.03")
    assert calculation.allowed_difference == 0
    assert rule.kind is EvidenceKind.RULE and GAEB_RULE in rule.detail
    assert "4.6.5" in rule.detail
    assert issue.suggested_action == (
        "Make the components add up to the Unit price 9.77, the price the bid offers. If the "
        "Unit price itself is wrong, correct it together with its components."
    )
    assert_well_formed([issue])


def test_the_sum_is_rounded_to_the_unit_price_places(boq_profile: DomainProfile) -> None:
    assert _run(boq_profile, [_item("3.33", "1.111", "2.222")]).issues == []  # 3.333 -> 3.33
    [issue] = _run(boq_profile, [_item("3.34", "1.345", "2.000")]).issues  # 3.345 -> 3.35
    assert issue.observed_value == "3.35"
    assert "= 3.345 → 3.35 (2 decimal places, half up)" in issue.explanation
    calculation = issue.evidence[0].calculation
    assert calculation is not None and calculation.rounded_result == Decimal("3.35")
    half_even = {"rounding_mode": "half_even"}
    assert _run(boq_profile, [_item("3.34", "1.345", "2.000")], half_even).issues == []


def test_the_places_come_from_the_column(boq_profile: DomainProfile) -> None:
    # A spreadsheet reads 40.00 back as 40; the column's other prices show two places, so a
    # sum of 39.90 does not round to 40.
    rows = [_item("40", "20.40", "19.50", code="01"), _item("9.77", "9.77", code="02")]
    [issue] = _run(boq_profile, rows).issues
    assert (issue.observed_value, issue.expected_value) == ("39.90", "40")
    # The number format says so too, also when no price shows its places.
    formatted = number_cell("40", number_format="#,##0.00 [$€-407]")
    [alone] = _run(boq_profile, [_item(formatted, "20.40", "19.50")]).issues
    assert alone.observed_value == "39.90"
    # Without either, the price's own places apply: 39.90 rounds to 40, as written.
    assert _run(boq_profile, [_item("40", "20.40", "19.50")]).issues == []
    general = number_cell("40", number_format="General")
    assert _run(boq_profile, [_item(general, "20.40", "19.50")]).issues == []
    # A price written with more places than a rounding takes is compared at ten places.
    long = "1.123456789012"
    [capped] = _run(boq_profile, [_item(long, "1.1234567890", "0.0000000001")]).issues
    assert capped.observed_value == "1.1234567891"


def test_abstentions(boq_profile: DomainProfile) -> None:
    rows = [
        _item("9.77", code="01"),  # no components: the normal case
        _item("9.77", marker_cell("entfällt", ValueMarker.NOT_APPLICABLE), "4.77", code="02"),
        _item("9.77", ambiguous_cell("5,000"), "4.77", code="03"),
        _item("9.77", number_cell("0.5", percent=True), "4.77", code="04"),  # a share in %
        _item(None, "5.00", "4.77", code="05"),
        _item(marker_cell("inkl.", ValueMarker.INCLUDED_ELSEWHERE), "5.00", "4.77", code="06"),
        _item(number_cell("9.77", currency="EUR"), number_cell("5.00", currency="USD"), code="07"),
    ]
    result = _run(boq_profile, rows)
    assert result.issues == []
    assert result.coverage["rows_without_components"] == 1
    assert result.coverage["rows_skipped_marker"] == 2
    assert result.coverage["rows_skipped_unusable_inputs"] == 2
    assert result.coverage["rows_skipped_missing_inputs"] == 1
    assert result.coverage["rows_skipped_currency_conflict"] == 1
    assert "rows_checked" not in result.coverage


def test_low_confidence_inputs_downgrade_the_finding(boq_profile: DomainProfile) -> None:
    [issue] = _run(boq_profile, [_item("9.77", number_cell("5.00", confidence=0.5), "4.80")]).issues
    assert issue.effective_evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [_item("9.77", "5.00", "4.80", code="01"), _item("12.00", "6.00", "6.10", code="02")]
    first = _run(boq_profile, rows).issues
    second = _run(boq_profile, rows).issues
    assert len(first) == 2
    assert_unique_fingerprints(first)
    assert [i.fingerprint for i in first] == [i.fingerprint for i in second]


def _gaeb_like(profile: DomainProfile, message: str, table_id: str | None = None) -> Dataset:
    """A priced table without component columns, under an import warning like the GAEB one."""
    warning = ExtractionWarning(
        code="gaeb_elements_not_shown", message=message, table_id=table_id, needs_review=False
    )
    builder = DatasetBuilder(profile, warnings=[warning])
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(["01.0010", "Mauerwerk", "10", unit_cell("m2", "m2"), "9.77", "97.70"])
    return builder.build()


def test_components_the_import_did_not_read_are_named(boq_profile: DomainProfile) -> None:
    listed = "GAEB elements kept in the file but not shown in the table: AddText (3), UPComp1 (4)"
    dataset = _gaeb_like(boq_profile, f"{listed}, UPComp2 (4).")
    assert applicability(DETECTOR, dataset, boq_profile).applicable
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage == {"tables_skipped_components_not_imported": 1}
    assert result.notes == [
        "Table 'LV': the file has unit price components (UPComp1 (4), UPComp2 (4)) that the "
        "import does not read yet, so they were not checked against the unit prices."
    ]
    # Other elements, another table's warning, or no profile setting: nothing to say.
    for other in (
        _gaeb_like(boq_profile, f"{listed.split(', UPComp1')[0]}."),
        _gaeb_like(boq_profile, f"{listed}.", table_id="tbl_999999"),
        _gaeb_like(boq_profile, "GAEB elements kept in the file but not shown: XUPComp1 (2)."),
    ):
        assert not applicability(DETECTOR, other, boq_profile).applicable
    unset = {"not_imported_warning": None}
    assert not applicability(DETECTOR, dataset, boq_profile, unset).applicable


def test_a_gaeb_file_with_components_says_they_were_not_checked(
    boq_profile: DomainProfile, tmp_path: Path
) -> None:
    x84 = (GAEB_FIXTURES / "small.x84").read_text(encoding="utf-8")
    components = "<UP>9.77</UP><UPComp1>5.00</UPComp1><UPComp2>4.77</UPComp2>"
    changed = x84.replace("<UP>9.77</UP>", components)
    assert changed != x84
    path = tmp_path / "bid.x84"
    path.write_text(changed, encoding="utf-8")
    raw = GaebAdapter("84").extract(path, IngestionLimits())
    dataset = build_dataset(
        raw, profile=boq_profile, document_id="doc", ids=SequentialIdFactory(), clock=FixedClock()
    )
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["tables_skipped_components_not_imported"] == 1
    [note] = result.notes
    assert "the file has unit price components (UPComp1 (1), UPComp2 (1))" in note


def test_a_gaeb_90_file_with_components_says_they_were_not_checked(
    boq_profile: DomainProfile, tmp_path: Path
) -> None:
    # GAEB 90 keeps the components in record 30 (Einheitspreisanteile), which the import counts
    # under its own label; this guards that the profile still names that label.
    lines = (GAEB_FIXTURES / "small.d86").read_bytes().decode("cp850").split("\r\n")
    at = next(i for i, line in enumerate(lines) if line.startswith("230101  10"))
    assert lines[at][12:22] == "0000004250"  # the unit price 42.50 of 01.01.10
    record = ("30" + " " * 10 + "0000003000" + "0000001250").ljust(72) + lines[at][72:]
    path = tmp_path / "bid.d86"
    path.write_bytes("\r\n".join([*lines[: at + 1], record, *lines[at + 1 :]]).encode("cp850"))
    raw = Gaeb90Adapter("86").extract(path, IngestionLimits())
    dataset = build_dataset(
        raw, profile=boq_profile, document_id="doc", ids=SequentialIdFactory(), clock=FixedClock()
    )
    verdict = applicability(DETECTOR, dataset, boq_profile)
    assert verdict.applicable, verdict.reasons
    result = run(DETECTOR, dataset, boq_profile)
    assert result.issues == []
    assert result.coverage["tables_skipped_components_not_imported"] == 1
    [note] = result.notes
    assert "unit price components (Satzart 30 (Einheitspreisanteile) (1))" in note


def test_config_applicability_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)  # the boq.yaml defaults validate
    assert config.not_imported_warning == "gaeb_elements_not_shown"
    assert config.not_imported_elements == [
        *(f"UPComp{k}" for k in range(1, 7)),
        "Satzart 30 (Einheitspreisanteile)",
    ]
    assert config.component_fields == [f"unit_price_component_{k}" for k in range(1, 7)]
    assert UnitPriceComponentsConfig.plannable_parameters() == {
        "price_field",
        "component_fields",
        "severity",
    }
    for bad in (
        {"unknown": 1},
        {"component_fields": []},
        {"component_fields": [f"unit_price_component_{k}" for k in range(1, 8)]},
        {"component_fields": ["Unit price"]},
        {"rounding_mode": "ceiling"},
    ):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    plain = boq_dataset(boq_profile, [_item("9.77")[:6]])  # no component columns
    verdict = applicability(DETECTOR, plain, boq_profile)
    assert not verdict.applicable and "a reviewer maps the components" in verdict.reasons[0]
    assert applicability(
        DETECTOR, boq_dataset(boq_profile, [], columns=COLUMNS), boq_profile
    ).applicable
    assert (
        "deterministic.unit_price_components"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )
