"""Export bundles always describe one consistent run; the registry maps format ids."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

import app.exporters.bundle as bundle_module
from app.core.errors import NotFoundError
from app.exporters import EXPORTERS, ExportBundle, export_filename, get_exporter
from app.exporters.bundle import register_exporter, utc_timestamp
from app.exporters.csv_export import IssuesCsvExporter, issues_csv
from app.exporters.json_export import JsonExporter, export_json
from app.exporters.xlsx_export import XLSX_MEDIA_TYPE, XlsxExporter
from app.exporters.zip_export import TablesZipExporter, tables_zip
from app.models.profile import DomainProfile
from tests.unit.exporters.samples import (
    GENERATED_AT,
    build_dataset,
    build_issues,
    make_bundle,
    make_document,
    make_run,
)


def _bundle_kwargs(profile: DomainProfile) -> dict:
    dataset = build_dataset(profile)
    return {
        "document": make_document(),
        "dataset": dataset,
        "run": make_run(dataset),
        "issues": build_issues(dataset, profile),
        "detectors": [],
        "generated_at": GENERATED_AT,
    }


def test_bundle_stores_sequences_as_tuples_and_time_in_utc(boq_profile: DomainProfile) -> None:
    kwargs = _bundle_kwargs(boq_profile)
    kwargs["generated_at"] = datetime(2026, 11, 18, 11, 30, tzinfo=timezone(timedelta(hours=1)))
    bundle = ExportBundle(**kwargs)
    assert isinstance(bundle.issues, tuple)
    assert isinstance(bundle.detectors, tuple)
    assert bundle.generated_at == GENERATED_AT
    assert bundle.generated_at.tzinfo is UTC
    assert bundle.generated_at_text == "2026-11-18T10:30:00Z"
    kwargs["issues"].clear()  # the caller's list cannot change the bundle
    assert len(bundle.issues) == 3


def test_naive_generated_at_is_refused(boq_profile: DomainProfile) -> None:
    kwargs = _bundle_kwargs(boq_profile)
    kwargs["generated_at"] = datetime(2026, 11, 18, 10, 30)
    with pytest.raises(ValueError, match="timezone-aware"):
        ExportBundle(**kwargs)
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_timestamp(datetime(2026, 1, 1))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda kw: kw.update(run=kw["run"].evolve(dataset_revision=2)), "dataset revision"),
        (lambda kw: kw.update(run=kw["run"].evolve(dataset_id="ds_other")), "dataset revision"),
        (lambda kw: kw.update(run=kw["run"].evolve(document_id="doc_other")), "document"),
        (
            lambda kw: kw.update(document=kw["document"].evolve(document_id="doc_other")),
            "document",
        ),
        (
            lambda kw: kw.update(issues=[kw["issues"][0].evolve(validation_run_id="run_x")]),
            "does not belong",
        ),
        (
            lambda kw: kw.update(issues=[kw["issues"][0].evolve(dataset_revision=2)]),
            "another dataset revision",
        ),
        (
            lambda kw: kw.update(issues=[kw["issues"][0].evolve(table_id="tbl_missing")]),
            "outside the dataset",
        ),
        (
            lambda kw: kw.update(issues=[kw["issues"][0].evolve(row_id="row_missing")]),
            "outside the dataset",
        ),
    ],
)
def test_inconsistent_bundles_are_refused(boq_profile: DomainProfile, change, message) -> None:
    kwargs = _bundle_kwargs(boq_profile)
    change(kwargs)
    with pytest.raises(ValueError, match=message):
        ExportBundle(**kwargs)


def test_registry_holds_the_phase_one_formats() -> None:
    # questions.md (main, e665b74): the question list for findings that need more information.
    # pdf: the findings report (app/exporters/pdf_report.py).
    assert sorted(EXPORTERS) == ["issues.csv", "json", "pdf", "questions.md", "tables.zip", "xlsx"]
    assert isinstance(get_exporter("json"), JsonExporter)
    assert isinstance(get_exporter("issues.csv"), IssuesCsvExporter)
    assert isinstance(get_exporter("tables.zip"), TablesZipExporter)
    assert isinstance(get_exporter("xlsx"), XlsxExporter)
    assert get_exporter("json") is bundle_module.get_exporter("json")


@pytest.mark.parametrize(
    ("format_id", "media_type", "filename"),
    [
        ("json", "application/json", "Angebot März 2026 2026-03-01 09-00.json"),
        ("issues.csv", "text/csv; charset=utf-8", "Angebot März 2026 2026-03-01 09-00 issues.csv"),
        ("tables.zip", "application/zip", "Angebot März 2026 2026-03-01 09-00 tables.zip"),
        ("xlsx", XLSX_MEDIA_TYPE, "Angebot März 2026 2026-03-01 09-00 issues.xlsx"),
        ("pdf", "application/pdf", "Angebot März 2026 2026-03-01 09-00 report.pdf"),
    ],
)
def test_exporters_declare_media_type_and_filename(
    boq_profile: DomainProfile, format_id: str, media_type: str, filename: str
) -> None:
    bundle = make_bundle(boq_profile)
    exporter = get_exporter(format_id)
    assert exporter.format_id == format_id
    assert exporter.media_type == media_type
    assert export_filename(bundle.document, bundle.run, exporter.filename_suffix) == filename


def test_exporters_delegate_to_the_format_functions(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    assert get_exporter("json").export(bundle) == export_json(bundle)
    assert get_exporter("issues.csv").export(bundle) == issues_csv(bundle)
    assert get_exporter("tables.zip").export(bundle) == tables_zip(bundle)


@pytest.mark.parametrize("format_id", ["html", "docx", "../json", "JSON", ""])
def test_unknown_formats_are_not_found(format_id: str) -> None:
    with pytest.raises(NotFoundError) as caught:
        get_exporter(format_id)
    assert caught.value.code == "not_found"
    assert caught.value.details["available"] == [
        "issues.csv",
        "json",
        "pdf",
        "questions.md",
        "tables.zip",
        "xlsx",
    ]


class _FakeExporter:
    def __init__(self, format_id: str) -> None:
        self.format_id = format_id
        self.media_type = "application/octet-stream"
        self.filename_suffix = ".bin"

    def export(self, bundle: ExportBundle) -> bytes:
        return bundle.run.run_id.encode()


def test_new_formats_are_added_by_registration(
    monkeypatch: pytest.MonkeyPatch, boq_profile: DomainProfile
) -> None:
    monkeypatch.setattr(bundle_module, "EXPORTERS", dict(EXPORTERS))
    fake = register_exporter(_FakeExporter("html"))
    assert get_exporter("html") is fake
    assert get_exporter("html").export(make_bundle(boq_profile)) == b"run_000001"
    assert "html" not in EXPORTERS  # the real registry is untouched


@pytest.mark.parametrize("format_id", ["json", "../x", "", "UPPER", "a" * 40])
def test_duplicate_and_malformed_format_ids_are_refused(
    monkeypatch: pytest.MonkeyPatch, format_id: str
) -> None:
    monkeypatch.setattr(bundle_module, "EXPORTERS", dict(EXPORTERS))
    with pytest.raises(ValueError, match="format"):
        register_exporter(_FakeExporter(format_id))
