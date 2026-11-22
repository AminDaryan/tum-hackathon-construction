"""tables.zip: entries, safe names, manifest and a byte-identical archive per bundle."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.exporters.csv_export import issues_csv, table_csv
from app.exporters.zip_export import (
    MANIFEST_ENTRY,
    ZIP_FORMAT,
    tables_zip,
    zip_timestamp,
)
from app.models.profile import DomainProfile
from tests.unit.exporters.samples import make_bundle

ENTRIES = ["01-LV.csv", "02-etc_passwd.csv", "03-CON.csv", "issues.csv", "manifest.json"]


def open_zip(data: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert archive.testzip() is None  # every CRC matches
    return archive


def test_entries_are_sorted_and_safely_named(boq_profile: DomainProfile) -> None:
    archive = open_zip(tables_zip(make_bundle(boq_profile)))
    assert archive.namelist() == ENTRIES
    for name in archive.namelist():
        assert "/" not in name
        assert "\\" not in name
        assert ".." not in name
        assert name.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL"}


def test_entries_hold_the_csv_exports(boq_profile: DomainProfile) -> None:
    bundle = make_bundle(boq_profile)
    archive = open_zip(tables_zip(bundle))
    assert archive.read("issues.csv") == issues_csv(bundle)
    for name, table in zip(ENTRIES[:3], bundle.dataset.tables, strict=True):
        assert archive.read(name) == table_csv(table)


def test_entry_metadata_is_fixed(boq_profile: DomainProfile) -> None:
    archive = open_zip(tables_zip(make_bundle(boq_profile)))
    for info in archive.infolist():
        assert info.compress_type == zipfile.ZIP_DEFLATED
        assert info.date_time == (2026, 11, 18, 10, 30, 0)
        assert info.create_system == 3
        assert info.external_attr == 0o100644 << 16
        assert info.comment == b""
        assert info.extra == b""
    assert archive.comment == b""


def test_manifest_names_run_revision_document_profile_and_files(
    boq_profile: DomainProfile,
) -> None:
    bundle = make_bundle(boq_profile)
    archive = open_zip(tables_zip(bundle))
    manifest = json.loads(archive.read(MANIFEST_ENTRY).decode("utf-8"))
    assert manifest["format"] == ZIP_FORMAT
    assert manifest["format_version"] == 1
    assert manifest["generated_at"] == "2026-11-18T10:30:00Z"
    assert manifest["validation_run_id"] == "run_000001"
    assert manifest["dataset_id"] == "ds_000001"
    assert manifest["dataset_revision"] == 1
    assert manifest["document"] == {
        "document_id": "doc_000001",
        "original_filename": "Angebot März 2026 €.xlsx",
    }
    assert manifest["profile"] == {"profile_id": "boq", "version": boq_profile.version}
    files = manifest["files"]
    assert [entry["name"] for entry in files] == ENTRIES[:-1]
    assert all(entry["description"] and "\n" not in entry["description"] for entry in files)
    tables = {entry["name"]: entry for entry in files if "table_id" in entry}
    assert tables["02-etc_passwd.csv"]["table_name"] == "../../etc/passwd"  # the real name
    assert tables["02-etc_passwd.csv"]["table_id"] == bundle.dataset.tables[1].table_id
    assert [entry["row_count"] for entry in tables.values()] == [5, 1, 2]
    assert "3 findings" in files[-1]["description"]
    assert any("apostrophe" in note for note in manifest["notes"])


def test_same_bundle_gives_identical_bytes(boq_profile: DomainProfile) -> None:
    first = tables_zip(make_bundle(boq_profile))
    assert tables_zip(make_bundle(boq_profile)) == first


def test_timestamps_come_from_generated_at_in_utc(boq_profile: DomainProfile) -> None:
    local = datetime(2026, 11, 18, 12, 30, 0, tzinfo=timezone(timedelta(hours=2)))
    data = tables_zip(make_bundle(boq_profile, generated_at=local))
    assert data == tables_zip(make_bundle(boq_profile))  # same instant, same archive
    later = tables_zip(make_bundle(boq_profile, generated_at=local + timedelta(days=1)))
    assert {info.date_time for info in open_zip(later).infolist()} == {(2026, 11, 19, 10, 30, 0)}


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 11, 18, 10, 30, 2, tzinfo=UTC), (2026, 11, 18, 10, 30, 2)),
        (datetime(1970, 1, 1, tzinfo=UTC), (1980, 1, 1, 0, 0, 0)),
        (datetime(2200, 6, 1, tzinfo=UTC), (2107, 12, 31, 23, 59, 58)),
    ],
)
def test_zip_timestamps_are_clamped_to_the_zip_range(
    moment: datetime, expected: tuple[int, ...]
) -> None:
    assert zip_timestamp(moment) == expected


def test_an_empty_run_still_has_issue_register_and_manifest(boq_profile: DomainProfile) -> None:
    archive = open_zip(tables_zip(make_bundle(boq_profile, issues=[])))
    assert archive.read("issues.csv").count(b"\r\n") == 1  # header only
    manifest = json.loads(archive.read(MANIFEST_ENTRY))
    assert "0 findings" in manifest["files"][-1]["description"]
