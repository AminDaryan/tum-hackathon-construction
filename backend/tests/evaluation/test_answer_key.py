"""The answer-key scorer on a tiny made-up bill and key (no sample data)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.evaluation.__main__ import main
from app.evaluation.answer_key import LABEL, run_answer_key

pytestmark = pytest.mark.evaluation

# Item code, text, quantity, unit, unit price; rows 3 to 8 of the sheet (section in row 2).
ITEMS = [
    ("01.0010", "Boden ausheben", 100, "m3", 12.5),
    ("01.0020", "Boden abfahren", 80, "m3", 9.0),
    ("01.0030", "Rohr verlegen DN 100", 50, "m", 30.0),
    ("01.0040", "Schacht setzen", 4, "St", 800.0),
    ("01.0050", "Rohr verlegen DN 150", 40, "zz", 42.0),  # unknown unit in both files
    ("01.0060", "Oberboden andecken", 200, "qq", 3.5),  # unknown unit in both files
]
KEY = {
    "file": "faulty.xlsx",
    "planted": [
        # A wrong line total, only in the faulty file.
        {"error_id": "f-1", "finding_category": "error", "rows": [3]},
        # An unknown unit the clean original has as well: found, but not credited.
        {"error_id": "f-2", "finding_category": "error", "rows": [8]},
        # Nothing reports it; the most expensive line.
        {"error_id": "f-3", "finding_category": "risk", "rows": [6]},
    ],
    "not_planted": [{"id": "o-1", "rows": [4]}],
    "must_not_flag": [{"id": "ok-1", "rows": [7]}],
}


def _bill(path: Path, *, slip: bool) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["OZ", "Kurztext", "Menge", "Einheit", "EP", "GP"])
    sheet.append(["01", "Erdarbeiten", None, None, None, None])
    for code, text, quantity, unit, price in ITEMS:
        total = quantity * price + (90 if slip and code == "01.0010" else 0)
        sheet.append([code, text, quantity, unit, price, total])
    book.save(path)


def _files(root: Path) -> tuple[Path, Path]:
    _bill(root / "faulty.xlsx", slip=True)
    _bill(root / "clean.xlsx", slip=False)
    key = root / "key.json"
    key.write_text(json.dumps(KEY), encoding="utf-8")
    return key, root / "clean.xlsx"


def test_hits_the_clean_original_also_has_are_not_credited(tmp_path: Path) -> None:
    key, clean = _files(tmp_path)
    report = run_answer_key(key, clean_path=clean, bill_path=None, out_dir=tmp_path / "out", seed=1)
    before, after = report["before_discount"], report["after_discount"]
    assert report["planted"] == 3
    assert (before["found"], after["found"]) == (2, 1)
    assert (before["found_in_first_20"], after["found_in_first_20"]) == (2, 1)
    assert before["single_check_finds_by_check"] == {
        "deterministic.line_total": 1,
        "deterministic.unit_vocabulary": 1,
    }
    assert after["single_check_finds_by_check"] == {"deterministic.line_total": 1}
    assert after["found_by_category"] == {"error": 1, "risk": 0}
    assert report["must_not_flag_hits"] == 1
    assert report["must_not_flag_hits_also_on_clean_file"] == 1
    assert report["faulty_file_matches_key"] is None  # the key gives no checksum
    budget = report["review_budget"]
    # Three findings, so K = our findings is 3: the three most expensive lines hold f-3 only;
    # the first three lines top to bottom hold f-1 only.
    assert report["findings"] == 3
    assert budget["findings"]["findings"] == 2
    assert budget["most_expensive"]["findings"] == 1
    assert budget["top_to_bottom"]["findings"] == 1
    assert budget["findings_and_most_expensive"]["findings"] == 2
    assert budget["most_expensive"]["20"] == 3


def test_the_report_names_no_content_of_the_bill(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    key, clean = _files(tmp_path)
    out = tmp_path / "out"
    main(["--answer-key", str(key), "--clean", str(clean), "--out", str(out)])
    printed = capsys.readouterr().out
    written = (out / "answer-key-report.md").read_text(encoding="utf-8")
    assert LABEL in written
    for text in (printed, written, (out / "answer-key-report.json").read_text("utf-8")):
        for code, description, *_ in ITEMS:
            assert code not in text
            assert description not in text
        assert "zz" not in text
        assert "faulty.xlsx" not in text
        assert "f-1" not in text


def test_any_paths_and_a_key_without_file_or_not_planted(tmp_path: Path) -> None:
    _files(tmp_path)
    elsewhere = tmp_path / "held out" / "bills"
    elsewhere.mkdir(parents=True)
    bill = elsewhere / "some bill.xlsx"
    bill.write_bytes((tmp_path / "faulty.xlsx").read_bytes())
    key = tmp_path / "keys" / "blind.json"
    key.parent.mkdir()
    lean = {"planted": KEY["planted"], "must_not_flag": KEY["must_not_flag"]}
    key.write_text(json.dumps(lean), encoding="utf-8")
    out = tmp_path / "out"
    main(
        [
            "--answer-key",
            str(key),
            "--clean",
            str(tmp_path / "clean.xlsx"),
            "--bill",
            str(bill),
            "--out",
            str(out),
        ]
    )
    report = json.loads((out / "answer-key-report.json").read_text(encoding="utf-8"))
    assert (report["before_discount"]["found"], report["after_discount"]["found"]) == (2, 1)
    assert report["findings_on_original_oddities"] == 0
    with pytest.raises(SystemExit):  # neither the key nor --bill names the bill
        main(["--answer-key", str(key), "--clean", str(tmp_path / "clean.xlsx"), "--out", str(out)])


def test_answer_key_needs_the_clean_original(tmp_path: Path) -> None:
    key, _ = _files(tmp_path)
    with pytest.raises(SystemExit):
        main(["--answer-key", str(key), "--out", str(tmp_path / "out")])
