"""Download file names and archive entry names never carry paths, quotes or control text."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.exporters.filenames import (
    MAX_STEM_CHARS,
    MAX_TABLE_NAME_CHARS,
    document_stem,
    export_filename,
    project_export_filename,
    safe_table_name,
    table_entry_name,
)
from app.models.profile import DomainProfile
from tests.unit.exporters.samples import build_dataset, make_document, make_run

WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10))} | {
    f"LPT{n}" for n in range(1, 10)
}
HOSTILE_NAMES = (
    "../../etc/passwd",
    "..\\..\\Windows\\win.ini",
    "/absolute/path.xlsx",
    "C:\\temp\\x.xlsx",
    '"; filename=evil.html; a=".xlsx',
    "\u202egpj.exe.xlsx",  # right-to-left override
    "line\r\nbreak\x00.xlsx",
    "..",
    ".",
    "",
    "   ",
    "€€€.xlsx",
)


@pytest.mark.parametrize(
    ("filename", "stem"),
    [
        ("tender.xlsx", "tender"),
        ("Angebot März 2026 €.xlsx", "Angebot März 2026"),
        ("BoQ v1.2.xlsx", "BoQ v1.2"),
        ("archive.tar.gz", "archive.tar"),
        ("noext", "noext"),
        (".xlsx", "xlsx"),
        ("-rf.csv", "rf"),
        ("a..b.csv", "a.b"),
        ("Los  1\u00a0\t Nord.xlsx", "Los 1 Nord"),
        ("数量表.xlsx", "数量表"),
        ("....", "export"),
        ("€.xlsx", "export"),
    ],
)
def test_document_stem(filename: str, stem: str) -> None:
    assert document_stem(filename) == stem


def test_export_filename_is_stem_run_start_and_suffix(boq_profile: DomainProfile) -> None:
    run = make_run(build_dataset(boq_profile))
    document = make_document()
    assert export_filename(document, run, ".json") == "Angebot März 2026 2026-03-01 09-00.json"
    assert export_filename(document, run, " issues.csv") == (
        "Angebot März 2026 2026-03-01 09-00 issues.csv"
    )


def test_export_filename_turns_punctuation_into_spaces_and_omits_the_run_id(
    boq_profile: DomainProfile,
) -> None:
    run = make_run(build_dataset(boq_profile), run_id="run_385614ec8171488f918e2d637de4177e")
    document = make_document("Leistungsverzeichnis äöü (Kopie) (2).xlsx")
    assert export_filename(document, run, " issues.xlsx") == (
        "Leistungsverzeichnis äöü Kopie 2 2026-03-01 09-00 issues.xlsx"
    )


def test_two_runs_on_one_day_get_different_names(boq_profile: DomainProfile) -> None:
    morning = make_run(build_dataset(boq_profile))
    later = morning.model_copy(update={"started_at": morning.started_at + timedelta(hours=3)})
    names = {export_filename(make_document(), run, ".json") for run in (morning, later)}
    assert len(names) == 2


@pytest.mark.parametrize("filename", HOSTILE_NAMES)
def test_export_filename_never_carries_paths_or_header_syntax(
    boq_profile: DomainProfile, filename: str
) -> None:
    run = make_run(build_dataset(boq_profile))
    name = export_filename(make_document(filename), run, ".json")
    assert name.endswith(" 2026-03-01 09-00.json")
    assert not name.startswith(".")
    for forbidden in ("/", "\\", "..", '"', ";", ":", "\r", "\n", "\x00", "\u202e"):
        assert forbidden not in name
    assert len(name.removesuffix(" 2026-03-01 09-00.json")) <= MAX_STEM_CHARS


def test_long_stems_are_cut_and_never_end_in_punctuation(boq_profile: DomainProfile) -> None:
    run = make_run(build_dataset(boq_profile))
    name = export_filename(make_document("x" * 79 + " yyyyy.xlsx"), run, ".json")
    assert name == "x" * 79 + " 2026-03-01 09-00.json"


@pytest.mark.parametrize("suffix", ["/x.json", "..\\x", ".json\r\n", '".json'])
def test_unsafe_suffixes_are_refused(boq_profile: DomainProfile, suffix: str) -> None:
    run = make_run(build_dataset(boq_profile))
    with pytest.raises(ValueError, match="suffix"):
        export_filename(make_document(), run, suffix)


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("LV", "LV"),
        ("../../etc/passwd", "etc_passwd"),
        ("..\\..\\boot.ini", "boot_ini"),
        ("CON", "CON"),
        ("Übersicht März", "Übersicht März"),
        ("Los 1 / Titel 2", "Los 1 _ Titel 2"),
        ("Sheet.1", "Sheet_1"),
        ("\u202egpj.exe", "gpj_exe"),
        ("---", "table"),
        ("", "table"),
        ("..", "table"),
    ],
)
def test_safe_table_name(name: str, safe: str) -> None:
    assert safe_table_name(name) == safe


def test_table_names_are_cut_to_sixty_characters() -> None:
    assert safe_table_name("A" * 200) == "A" * MAX_TABLE_NAME_CHARS


def test_table_entry_names_are_numbered_and_safe() -> None:
    assert table_entry_name(1, "LV") == "01-LV.csv"
    assert table_entry_name(2, "../../etc/passwd") == "02-etc_passwd.csv"
    assert table_entry_name(3, "CON") == "03-CON.csv"
    assert table_entry_name(12, "") == "12-table.csv"
    assert table_entry_name(100, "x") == "100-x.csv"
    with pytest.raises(ValueError, match="1-based"):
        table_entry_name(0, "LV")


@pytest.mark.parametrize("name", [*HOSTILE_NAMES, *sorted(WINDOWS_DEVICE_NAMES)])
def test_table_entry_names_never_escape_or_hit_device_names(name: str) -> None:
    entry = table_entry_name(1, name)
    assert "/" not in entry
    assert "\\" not in entry
    assert ".." not in entry
    assert entry.count(".") == 1
    assert entry.endswith(".csv")
    assert entry.split(".")[0].upper() not in WINDOWS_DEVICE_NAMES


@pytest.mark.parametrize(
    ("name", "filename"),
    [
        ("Kalkufer 17, anchored excavation", "Kalkufer 17 anchored excavation report.pdf"),
        ("Brücke Nord / Los 2", "Brücke Nord Los 2 report.pdf"),
        ("Neubau_Halle-3", "Neubau_Halle-3 report.pdf"),
        ("../..", "project report.pdf"),
    ],
)
def test_project_export_filename_turns_punctuation_into_spaces(name: str, filename: str) -> None:
    assert project_export_filename(name, " report.pdf") == filename


@pytest.mark.parametrize("name", HOSTILE_NAMES)
def test_project_export_filename_never_carries_paths_or_header_syntax(name: str) -> None:
    filename = project_export_filename(name, " report.pdf")
    assert not any(char in filename for char in '/\\"\r\n\x00\u202e;')
    assert ".." not in filename and not filename.startswith(".")
