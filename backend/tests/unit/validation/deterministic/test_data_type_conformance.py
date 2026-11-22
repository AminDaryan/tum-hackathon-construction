"""deterministic.data_type_conformance: failed, ambiguous and wrongly typed values."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import DetectorConfigError
from app.models import cell_rules
from app.models.dataset import RowKind
from app.models.finding_category import FindingCategory
from app.models.issue import EvidenceClass, Severity
from app.models.profile import DomainProfile
from app.models.source import SourceKind, SourceLocation
from app.models.values import DataType, DateValue
from app.validation.deterministic.data_type_conformance import (
    RULE_AMBIGUOUS,
    RULE_INVALID,
    RULE_MINORITY,
    RULE_WRONG_TYPE,
    DataTypeConformanceDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import DatasetBuilder, ambiguous_cell, failed_number_cell, unit_cell
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    by_rule,
    resolve,
    run,
)

DETECTOR = DataTypeConformanceDetector
_SOURCE = SourceLocation(kind=SourceKind.SPREADSHEET, sheet_index=0, row_number=1, column_number=3)


def _item(quantity: object) -> list[object]:
    return ["01", "Aushub", quantity, unit_cell("m3", "m3"), "40.00", "480.00"]


def test_clean_data_has_no_findings(boq_profile: DomainProfile) -> None:
    assert run(DETECTOR, boq_dataset(boq_profile, [_item("12")]), boq_profile).issues == []


def test_failed_number_is_a_confirmed_violation(boq_profile: DomainProfile) -> None:
    dataset = boq_dataset(
        boq_profile, [_item(failed_number_cell("ca. 5", "Not a number: 'ca. 5'."))]
    )
    result = run(DETECTOR, dataset, boq_profile)
    [issue] = by_rule(result.issues, RULE_INVALID)
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.finding_category is FindingCategory.ERROR
    assert issue.severity is Severity.MEDIUM
    assert "ca. 5" in issue.title and "Quantity" in issue.title
    assert_well_formed(result.issues)


def test_ambiguous_value_is_extraction_uncertainty(boq_profile: DomainProfile) -> None:
    result = run(DETECTOR, boq_dataset(boq_profile, [_item(ambiguous_cell("1.234"))]), boq_profile)
    [issue] = by_rule(result.issues, RULE_AMBIGUOUS)
    assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert issue.finding_category is None  # about reading the file
    assert "1.234" in issue.title


def test_wrong_type_in_a_number_field(boq_profile: DomainProfile) -> None:
    dated = cell_rules.typed_cell(
        DateValue(value=date(2026, 3, 4)), DataType.DATE, _SOURCE, raw="2026-03-04"
    )
    result = run(DETECTOR, boq_dataset(boq_profile, [_item(dated)]), boq_profile)
    [issue] = by_rule(result.issues, RULE_WRONG_TYPE)
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert "date" in issue.title


def test_text_rows_are_not_checked_but_totals_are(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(
        [None, "Hinweis", failed_number_cell("siehe Plan"), None, None, None], kind=RowKind.TEXT
    )
    table.row([None, "Summe", None, None, None, ambiguous_cell("1.234")], kind=RowKind.SUBTOTAL)
    result = run(DETECTOR, builder.build(), boq_profile)
    assert [i.rule_id for i in result.issues] == [RULE_AMBIGUOUS]


def test_many_cells_are_grouped(boq_profile: DomainProfile) -> None:
    rows = [_item(failed_number_cell(f"x{i}")) for i in range(60)]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    [group] = result.issues
    assert group.title.startswith("60 values in Quantity")
    assert len(group.affected_cells) == 50


def test_minority_types_in_unmapped_columns(boq_profile: DomainProfile) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", [*BOQ_COLUMNS, ("Zusatz", None)])
    for i in range(20):
        table.row([f"{i:02d}", "Pos", "1", unit_cell("m", "m"), "1", "1", str(i)])
    table.row(["99", "Pos", "1", unit_cell("m", "m"), "1", "1", "abc"])
    result = run(DETECTOR, builder.build(), boq_profile)
    [issue] = by_rule(result.issues, RULE_MINORITY)
    assert issue.evidence_class is EvidenceClass.SUSPECTED_ANOMALY
    assert issue.severity is Severity.LOW
    assert issue.anomaly_score is None
    off = run(DETECTOR, builder.build(), boq_profile, {"check_unmapped_columns": False})
    assert by_rule(off.issues, RULE_MINORITY) == []


def test_config_and_registry(boq_profile: DomainProfile) -> None:
    assert resolve(DETECTOR, boq_profile).max_cells_per_issue == 50
    with pytest.raises(DetectorConfigError):
        resolve(DETECTOR, boq_profile, {"dominance_threshold": 0.2})
    with pytest.raises(DetectorConfigError):
        resolve(DETECTOR, boq_profile, {"unknown": True})
    assert (
        "deterministic.data_type_conformance"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [_item(failed_number_cell("a")), _item(ambiguous_cell("2.500"))]
    first = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    second = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert_unique_fingerprints(first.issues)
    assert [i.fingerprint for i in first.issues] == [i.fingerprint for i in second.issues]
