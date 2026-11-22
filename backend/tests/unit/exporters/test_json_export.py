"""JSON export: documented shape, exact decimals as strings, round trip, determinism."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.exporters.json_export import (
    JSON_FORMAT,
    JSON_FORMAT_VERSION,
    dump_json,
    export_json,
)
from app.models.dataset import Dataset
from app.models.issue import ValidationIssue
from app.models.profile import DomainProfile
from app.models.run import ValidationRun
from app.validation.contracts.detector import DetectorSpec
from tests.support.builders import DatasetBuilder, text_cell
from tests.unit.exporters.samples import GENERATED_AT, OTHER_SPEC, PROBE_SPEC, make_bundle


def load(data: bytes) -> dict:
    assert not data.startswith(b"\xef\xbb\xbf")
    return json.loads(data.decode("utf-8"))


def test_top_level_shape_and_header(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    payload = load(export_json(bundle))
    assert list(payload) == ["export", "dataset", "validation_run", "detectors", "issues"]
    assert payload["export"] == {
        "format": JSON_FORMAT,
        "format_version": JSON_FORMAT_VERSION,
        "generated_at": "2026-11-18T10:30:00Z",
        "validation_run_id": "run_000001",
        "dataset_id": "ds_000001",
        "dataset_revision": 1,
        "document": {
            "document_id": "doc_000001",
            "original_filename": "Angebot März 2026 €.xlsx",
            "format": "xlsx",
            "uploaded_at": "2026-03-01T09:00:00Z",
            "processing_status": "processed",
            "failure_reason": None,
            "profile_id": "boq",
            "model": None,
            "size_bytes": 48_211,
            "sha256": bundle.document.source_file.sha256,
            "dataset_id": "ds_000001",
            "table_count": 3,
            "row_count": 8,
        },
        "profile": {"profile_id": "boq", "version": boq_profile.version},
    }
    assert JSON_FORMAT == "tabular-integrity-workbench/json"
    assert JSON_FORMAT_VERSION == 1


def test_records_round_trip_through_the_models(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    payload = load(export_json(bundle))
    assert Dataset.model_validate(payload["dataset"]) == bundle.dataset
    assert ValidationRun.model_validate(payload["validation_run"]) == bundle.run
    assert [ValidationIssue.model_validate(i) for i in payload["issues"]] == list(bundle.issues)
    assert [DetectorSpec.model_validate(d) for d in payload["detectors"]] == [
        OTHER_SPEC,
        PROBE_SPEC,
    ]  # sorted by detector id


def test_decimals_are_exact_strings(boq_profile: DomainProfile) -> None:
    payload = load(export_json(make_bundle(boq_profile)))
    impact = payload["issues"][0]["estimated_financial_impact"]
    assert (impact["amount"], impact["reported"], impact["recomputed"]) == (
        "-12.50",
        "118.75",
        "131.25",
    )
    bill = payload["dataset"]["tables"][0]
    rate_column = bill["columns"][4]["column_id"]
    rate = bill["rows"][2]["cells"][rate_column]
    assert rate["raw_value"] == "-12.50"
    assert rate["normalized_value"] == {
        "kind": "number",
        "value": "-12.50",
        "currency": None,
        "is_percent": False,
    }
    report = payload["validation_run"]["detector_reports"][0]
    assert report["config"] == {"tolerance": "0.01"}


def test_computed_fields_and_review_state_are_included(boq_profile: DomainProfile) -> None:
    payload = load(export_json(make_bundle(boq_profile)))
    line_total, _, reviewed = payload["issues"]
    assert line_total["affected_cells"][0]["source"]["a1"] == "F3"
    assert reviewed["review_status"] == "confirmed_error"
    assert reviewed["effective_evidence_class"] == "human_confirmed_error"
    assert reviewed["reviewer_comment"] == "\r=x geprüft"  # JSON text is not neutralized
    assert reviewed["version"] == 2


def test_issues_carry_their_finding_category(boq_profile: DomainProfile) -> None:
    """``finding_category`` is a computed field: written as the model serializes it (null for
    a detector the category tables do not know, such as the test probes), ignored on parse."""
    bundle = make_bundle(boq_profile)
    line_total = bundle.issues[0].evolve(detector_id="deterministic.line_total")
    issues = [line_total, *bundle.issues[1:]]
    payload = load(export_json(make_bundle(boq_profile, dataset=bundle.dataset, issues=issues)))
    assert [issue["finding_category"] for issue in payload["issues"]] == ["error", None, None]
    assert [ValidationIssue.model_validate(issue) for issue in payload["issues"]] == issues


def test_issues_keep_the_given_order(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    reordered = make_bundle(boq_profile, dataset=bundle.dataset, issues=bundle.issues[::-1])
    ids = [issue["issue_id"] for issue in load(export_json(reordered))["issues"]]
    assert ids == ["iss_000003", "iss_000002", "iss_000001"]


def test_output_is_utf8_compact_with_a_final_newline(boq_profile: DomainProfile) -> None:
    data = export_json(make_bundle(boq_profile))
    assert data.endswith(b"}\n")
    assert data.count(b"\n") == 1  # line breaks inside text are escaped
    assert "März".encode() in data  # not \u-escaped
    assert b'{"export":{"format":"tabular-integrity-workbench/json",' in data


def test_nan_and_infinity_are_refused() -> None:
    with pytest.raises(ValueError, match="JSON compliant"):
        dump_json({"score": float("nan")})
    with pytest.raises(ValueError, match="JSON compliant"):
        dump_json([float("inf")])


def test_unpaired_surrogates_stay_exact_and_the_file_valid_utf8(
    boq_profile: DomainProfile,
) -> None:
    builder = DatasetBuilder(boq_profile)
    builder.table("T", [("Note", "description")]).row([text_cell("a\ud800b")])
    data = export_json(make_bundle(boq_profile, dataset=builder.build(), issues=[]))
    data.decode("utf-8")  # strict decoding succeeds
    table = json.loads(data)["dataset"]["tables"][0]
    cell = next(iter(table["rows"][0]["cells"].values()))
    assert cell["raw_value"] == "a\ud800b"


def test_same_bundle_gives_identical_bytes(boq_profile: DomainProfile) -> None:
    first = export_json(make_bundle(boq_profile))
    assert export_json(make_bundle(boq_profile)) == first  # rebuilt from scratch
    later = export_json(make_bundle(boq_profile, generated_at=GENERATED_AT + timedelta(1)))
    assert later != first
    assert later.replace(b"2026-11-19T10:30:00Z", b"2026-11-18T10:30:00Z") == first
