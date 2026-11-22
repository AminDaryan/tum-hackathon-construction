"""llm.bill_review: the stored claims of a Claude review, listed as suspicions (no model is
called)."""

from __future__ import annotations

from dataclasses import replace

from app.agents.bill_review import position_digest, read_bill
from app.models.bill_review import BillReview, BillReviewClaim
from app.models.dataset import Dataset, RowKind
from app.models.issue import EvidenceClass
from app.validation.semantic.bill_review import BillReviewDetector
from tests.support.builders import DatasetBuilder, make_context
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    run,
)


def _bill(profile) -> Dataset:
    builder = DatasetBuilder(profile)
    table = builder.table("LV", BOQ_COLUMNS)
    table.row(["01", "Erdarbeiten", None, None, None, None], kind=RowKind.SECTION, code="01")
    table.row(["01.0010", "Baugrube ausheben", "380", "m3", "18.50", "7030.00"])
    table.row(["01.0020", "Verfüllen mit Kies", "120", "m3", "32.00", "3840.00"])
    return builder.build()


def _claim(dataset: Dataset, oz: str, issue_type: str | None, **values: object) -> BillReviewClaim:
    position = next(p for p in read_bill(dataset, "").positions if p.oz == oz)
    fields: dict[str, object] = {
        "focus": "numbers",
        "issue_name": "Unusually high unit price" if issue_type else None,
        "certainty": "high",
        "quote": "32.00",
        "grounded": True,
        "why": "Gravel fill at 32.00 per m3.",
    }
    fields.update(values)
    return BillReviewClaim(
        table_id=position.table_id,
        row_id=position.row_id,
        oz=oz,
        position_digest=position_digest(position),
        issue_type=issue_type,
        **fields,  # type: ignore[arg-type]
    )


def _context(dataset: Dataset, profile, claims: list[BillReviewClaim]):
    review = BillReview(
        dataset_id=dataset.dataset_id,
        dataset_revision=dataset.revision,
        model="claude-haiku-5-5",
        prompt_version="sandwich-5",
        status="completed",
        detail="3 of 3 passes answered on 2 positions.",
        positions=2,
        claims=claims,
    )
    return replace(make_context(dataset, profile), bill_review=review)


def test_a_claim_two_passes_make_is_listed_once(boq_profile) -> None:
    dataset = _bill(boq_profile)
    twice = [
        _claim(dataset, "01.0020", "081"),
        _claim(dataset, "01.0020", "081", focus="basis", why="Above the other fill."),
    ]
    found = run(
        BillReviewDetector, dataset, boq_profile, context=_context(dataset, boq_profile, twice)
    )
    [issue] = found.issues
    assert issue.rule_id == "r081"
    assert issue.evidence_class == EvidenceClass.SEMANTIC_WARNING
    assert found.coverage == {"positions_checked": 2, "claims_repeated": 1}


def test_a_claim_outside_the_catalogue_points_at_the_description(boq_profile) -> None:
    dataset = _bill(boq_profile)
    claim = _claim(dataset, "01.0010", None, quote="ohne Bodenklasse", grounded=False)
    found = run(
        BillReviewDetector, dataset, boq_profile, context=_context(dataset, boq_profile, [claim])
    )
    [issue] = found.issues
    assert issue.rule_id == "other"
    assert issue.title == "Suspected by Claude: an issue outside the catalogue"
    assert (
        issue.affected_cells[0].column_id
        == dataset.tables[0].column_for_field("description").column_id
    )
    assert issue.evidence[0].label.startswith("Quoted by the model (not found")


def test_without_a_stored_review_the_check_is_skipped(boq_profile) -> None:
    result = applicability(BillReviewDetector, _bill(boq_profile), boq_profile)
    assert not result.applicable
    assert result.reasons == ("No Claude review was started for this bill.",)
