"""Canonical model invariants: exact decimals, immutability, round-trips, review workflow."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.a1 import a1_reference, column_letter
from app.core.errors import ReviewTransitionError
from app.models.dataset import Dataset, RowKind, Table
from app.models.finding_category import FindingCategory
from app.models.issue import (
    ALLOWED_REVIEW_TRANSITIONS,
    AnomalyScore,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    ReviewStatus,
    Severity,
    ValidationIssue,
    check_review_transition,
)
from app.models.source import SourceKind, SourceLocation
from app.models.values import NumberValue, TextValue, value_to_display
from tests.support.builders import DatasetBuilder

ISSUE_BASE = dict(
    issue_id="iss_1",
    fingerprint="abc",
    validation_run_id="run_1",
    document_id="doc_1",
    dataset_id="ds_1",
    dataset_revision=1,
    detector_id="deterministic.example",
    detector_version="1.0.0",
    issue_category="arithmetic",
    severity=Severity.HIGH,
    evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
    title="Line total mismatch",
    explanation="Quantity × unit price differs from the reported total.",
    created_at="2026-01-01T00:00:00Z",
)

# An issue as the code stored it before finding categories (2026-11-20): every field, and the
# computed effective_evidence_class, but no finding_category.
LEGACY_ISSUE_PAYLOAD = """{
  "issue_id": "iss_1", "fingerprint": "abc", "evidence_digest": null,
  "validation_run_id": "run_1", "document_id": "doc_1", "dataset_id": "ds_1",
  "dataset_revision": 1, "table_id": null, "row_id": null,
  "affected_cells": [], "input_cells": [],
  "detector_id": "deterministic.line_total", "detector_version": "1.0.0",
  "rule_id": "line_total_mismatch", "issue_category": "arithmetic", "severity": "high",
  "evidence_class": "confirmed_rule_violation", "title": "Line total mismatch",
  "explanation": "Quantity × unit price differs from the reported total.",
  "observed_value": "3725.00", "expected_value": "3752.00", "evidence": [],
  "suggested_action": "Correct the line total or the quantity.",
  "estimated_financial_impact": null, "extraction_confidence": null, "anomaly_score": null,
  "review_status": "pending_review", "reviewer_comment": null, "reviewed_at": null,
  "version": 1, "created_at": "2026-01-01T00:00:00Z",
  "effective_evidence_class": "confirmed_rule_violation"
}"""


class TestValues:
    def test_decimal_survives_json_round_trip_exactly(self) -> None:
        value = NumberValue(value=Decimal("1234.50"), currency="EUR")
        dumped = value.model_dump(mode="json")
        assert dumped["value"] == "1234.50"  # string, not float
        assert NumberValue.model_validate(dumped).value == Decimal("1234.50")

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_numbers_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            NumberValue(value=Decimal(bad))

    def test_currency_must_be_iso_code(self) -> None:
        with pytest.raises(ValidationError):
            NumberValue(value=Decimal(1), currency="€")

    def test_values_are_immutable(self) -> None:
        value = TextValue(value="x")
        with pytest.raises(ValidationError):
            value.value = "y"  # type: ignore[misc]

    def test_display_rendering(self) -> None:
        assert value_to_display(NumberValue(value=Decimal("1E+3"))) == "1000"
        assert value_to_display(NumberValue(value=Decimal("2.50"), currency="EUR")) == "2.50 EUR"
        assert value_to_display(None) is None


class TestSourceLocation:
    def test_a1_for_spreadsheet_cells(self) -> None:
        loc = SourceLocation(
            kind=SourceKind.SPREADSHEET, sheet_name="LV", row_number=12, column_number=28
        )
        assert loc.a1 == "AB12"
        assert "AB12" in loc.describe()

    def test_no_a1_for_csv(self) -> None:
        loc = SourceLocation(kind=SourceKind.DELIMITED_TEXT, row_number=3, column_number=2)
        assert loc.a1 is None
        assert loc.describe() == "CSV record 3, field 2"

    def test_round_trip_ignores_computed_field_but_rejects_unknown_keys(self) -> None:
        loc = SourceLocation(kind=SourceKind.SPREADSHEET, row_number=1, column_number=1)
        dumped = loc.model_dump(mode="json")
        assert dumped["a1"] == "A1"
        assert SourceLocation.model_validate(dumped) == loc
        with pytest.raises(ValidationError):
            SourceLocation.model_validate({**dumped, "unexpected": 1})

    @pytest.mark.parametrize(
        ("n", "letters"), [(1, "A"), (26, "Z"), (27, "AA"), (52, "AZ"), (703, "AAA")]
    )
    def test_column_letters(self, n: int, letters: str) -> None:
        assert column_letter(n) == letters

    def test_invalid_coordinates(self) -> None:
        with pytest.raises(ValueError, match="row_number"):
            a1_reference(0, 1)


class TestDataset:
    def test_dataset_round_trip_preserves_everything(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [("Qty", "quantity"), ("Unit", "unit"), ("Note", None)])
        table.row(["10.500", "m²", "first"])
        table.row([None, None, "Subtotal"], kind=RowKind.SUBTOTAL)
        dataset = builder.build()
        restored = Dataset.model_validate_json(dataset.model_dump_json())
        assert restored == dataset
        qty = restored.tables[0].rows[0].cells[restored.tables[0].columns[0].column_id]
        assert qty.normalized_value == NumberValue(value=Decimal("10.500"))

    def test_lookup_by_field_and_ids(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [("Qty", "quantity"), ("Rate", "unit_price")])
        table.row(["1", "2"])
        dataset = builder.build()
        tbl = dataset.tables[0]
        assert tbl.column_for_field("unit_price") is tbl.columns[1]
        assert tbl.column_for_field("line_total") is None
        assert tbl.row(tbl.rows[0].row_id) is tbl.rows[0]
        assert dataset.table(tbl.table_id) is tbl


class TestIssueModel:
    def test_detectors_cannot_claim_human_confirmation(self) -> None:
        with pytest.raises(ValidationError):
            ValidationIssue(**{**ISSUE_BASE, "evidence_class": EvidenceClass.HUMAN_CONFIRMED_ERROR})

    def test_effective_evidence_class_follows_review(self) -> None:
        issue = ValidationIssue(**ISSUE_BASE)
        assert issue.effective_evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
        confirmed = issue.evolve(review_status=ReviewStatus.CONFIRMED_ERROR)
        assert confirmed.effective_evidence_class is EvidenceClass.HUMAN_CONFIRMED_ERROR
        assert confirmed.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION  # history kept

    def test_issue_round_trip(self) -> None:
        issue = ValidationIssue(**ISSUE_BASE)
        assert ValidationIssue.model_validate(issue.model_dump(mode="json")) == issue

    def test_finding_category_is_computed_and_reviews_keep_it(self) -> None:
        line_total = {**ISSUE_BASE, "detector_id": "deterministic.line_total"}
        issue = ValidationIssue(**line_total)
        assert issue.finding_category is FindingCategory.ERROR
        assert issue.model_dump(mode="json")["finding_category"] == "error"
        confirmed = issue.evolve(review_status=ReviewStatus.CONFIRMED_ERROR)
        assert confirmed.finding_category is FindingCategory.ERROR
        dismissed = issue.evolve(review_status=ReviewStatus.FALSE_POSITIVE)
        assert dismissed.finding_category is FindingCategory.ERROR
        # Downgraded by the evidence policy (a value from a PDF's text layer): the evidence
        # class says to verify it in the source, and the category stays.
        downgraded = ValidationIssue(
            **{**line_total, "evidence_class": EvidenceClass.EXTRACTION_UNCERTAINTY}
        )
        assert downgraded.finding_category is FindingCategory.ERROR
        reading = ValidationIssue(
            **{
                **line_total,
                "detector_id": "deterministic.subtotal",
                "rule_id": "subtotal_display_rounding",
                "evidence_class": EvidenceClass.EXTRACTION_UNCERTAINTY,
            }
        )
        assert reading.finding_category is None  # about reading the file, by its rule
        assert reading.model_dump(mode="json")["finding_category"] is None
        unknown = ValidationIssue(**ISSUE_BASE)  # deterministic.example is not registered
        assert unknown.finding_category is None

    def test_an_issue_serialized_before_finding_categories_loads(self) -> None:
        """A payload stored before ``finding_category`` existed (no such key) loads unchanged
        and gets its category computed."""
        stored = json.loads(LEGACY_ISSUE_PAYLOAD)
        assert "finding_category" not in stored
        issue = ValidationIssue.model_validate(stored)
        assert issue.finding_category is FindingCategory.ERROR
        assert issue.model_dump(mode="json") == {**stored, "finding_category": "error"}

    def test_a_stored_category_is_never_read_back(self) -> None:
        """Computed values in a payload are dropped on load: the tables decide, so a stored
        payload follows a later change of the mapping."""
        stored = {**json.loads(LEGACY_ISSUE_PAYLOAD), "finding_category": "risk"}
        assert ValidationIssue.model_validate(stored).finding_category is FindingCategory.ERROR

    def test_category_must_be_snake_case(self) -> None:
        with pytest.raises(ValidationError):
            ValidationIssue(**{**ISSUE_BASE, "issue_category": "Bad Category"})


class TestReviewTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (ReviewStatus.PENDING_REVIEW, ReviewStatus.CONFIRMED_ERROR),
            (ReviewStatus.PENDING_REVIEW, ReviewStatus.FALSE_POSITIVE),
            (ReviewStatus.NEEDS_MORE_INFORMATION, ReviewStatus.DISMISSED),
            (ReviewStatus.CONFIRMED_ERROR, ReviewStatus.CORRECTED),
            (ReviewStatus.FALSE_POSITIVE, ReviewStatus.PENDING_REVIEW),
        ],
    )
    def test_allowed(self, current: ReviewStatus, target: ReviewStatus) -> None:
        check_review_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (ReviewStatus.PENDING_REVIEW, ReviewStatus.CORRECTED),  # needs the correction workflow
            (ReviewStatus.CORRECTED, ReviewStatus.PENDING_REVIEW),  # terminal
            (ReviewStatus.FALSE_POSITIVE, ReviewStatus.CONFIRMED_ERROR),  # reopen first
            (ReviewStatus.PENDING_REVIEW, ReviewStatus.PENDING_REVIEW),
        ],
    )
    def test_rejected(self, current: ReviewStatus, target: ReviewStatus) -> None:
        with pytest.raises(ReviewTransitionError):
            check_review_transition(current, target)

    def test_every_status_has_a_rule(self) -> None:
        assert set(ALLOWED_REVIEW_TRANSITIONS) == set(ReviewStatus)


class TestContractHardening:
    """Invariants added after the design review: no floats in exact values, validated changes,
    structural integrity of tables, honest scores."""

    def test_floats_are_rejected_for_exact_values(self) -> None:
        with pytest.raises(ValidationError):
            NumberValue(value=1.1 * 3)  # type: ignore[arg-type]
        assert NumberValue(value="3.3").value == Decimal("3.3")
        assert NumberValue(value=3).value == Decimal(3)

    @pytest.mark.parametrize("bad", ["1E+999999", "1E-50", "1" * 40])
    def test_document_numbers_are_bounded(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            NumberValue(value=Decimal(bad))

    def test_percent_values_display_as_percent(self) -> None:
        assert value_to_display(NumberValue(value=Decimal("0.19"), is_percent=True)) == "19 %"

    def test_evidence_data_keeps_decimals_exact(self) -> None:
        item = EvidenceItem(
            kind=EvidenceKind.CALCULATION,
            label="x",
            detail="x",
            data={"big": Decimal("12345678901234567890.12"), "ratio": 0.5},
        )
        assert item.data == {"big": "12345678901234567890.12", "ratio": 0.5}

    def test_calibrated_scores_need_a_reference(self) -> None:
        with pytest.raises(ValidationError):
            AnomalyScore(value=0.97, method="mad", interpretation="x", calibrated=True)

    def test_scores_cannot_back_confirmed_violations(self) -> None:
        score = AnomalyScore(value=4.2, method="mad", interpretation="robust z-score")
        with pytest.raises(ValidationError):
            ValidationIssue(**ISSUE_BASE, anomaly_score=score)

    def test_evolve_validates_where_model_copy_does_not(self) -> None:
        issue = ValidationIssue(**ISSUE_BASE)
        with pytest.raises(ValidationError):
            issue.evolve(evidence_class=EvidenceClass.HUMAN_CONFIRMED_ERROR)
        with pytest.raises(ValidationError):
            issue.evolve(reviewer_comment="x" * 5000)
        with pytest.raises(ValueError, match="Unknown field"):
            issue.evolve(not_a_field=1)

    def test_tables_enforce_one_column_per_field_and_complete_rows(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("LV", [("Kurztext", "description"), ("Qty", "quantity")]).row(["a", "1"])
        table = builder.build().tables[0]
        duplicate = table.columns[1].evolve(mapping=table.columns[0].mapping)
        with pytest.raises(ValidationError, match="same field"):
            table.evolve(columns=[table.columns[0], duplicate])
        sparse_row = table.rows[0].evolve(
            cells={table.columns[0].column_id: table.rows[0].cells[table.columns[0].column_id]}
        )
        with pytest.raises(ValidationError, match="exactly one cell per column"):
            Table.model_validate({**table.model_dump(), "rows": [sparse_row.model_dump()]})

    def test_section_hierarchy_is_recorded(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", [("OZ", "item_code"), ("Betrag", "line_total")])
        table.row(["01", None], kind=RowKind.SECTION, level=1)
        table.row(["01.01", None], kind=RowKind.SECTION, level=2)
        table.row(["01.01.0010", "100"])
        table.row([None, "100"], kind=RowKind.SUBTOTAL, closes_section=True)
        table.row([None, "100"], kind=RowKind.SUBTOTAL, closes_section=True)
        rows = builder.build().tables[0].rows
        title, sub, item, close_sub, close_title = rows
        assert sub.section_path == [title.row_id]
        assert item.section_path == [title.row_id, sub.row_id]
        assert item.section_row_id == sub.row_id
        assert close_sub.closes_section_id == sub.row_id
        assert close_title.closes_section_id == title.row_id
