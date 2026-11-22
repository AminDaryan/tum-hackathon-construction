"""``--inject-into``: planting into the canonical datasets of a folder of bills, in memory."""

from __future__ import annotations

import hashlib
import random
import tempfile
from pathlib import Path

import pytest

from app.core.ids import IdPrefix
from app.evaluation.__main__ import main
from app.evaluation.boq import Features, document, generate_bill, render_csv, render_xlsx
from app.evaluation.boq_report import LABEL
from app.evaluation.inject import (
    NEEDS,
    InjectConfig,
    _near_duplicate_position,
    plant_table,
    planted_dataset,
    render,
    run_injection,
    sheet_for,
    summary,
    truths,
)
from app.evaluation.inject import (
    _priced as _items,
)
from app.evaluation.runner import benchmark_workbench
from app.evaluation.synthetic import ErrorKind
from app.models.cell_rules import text_cell
from app.models.dataset import Dataset
from app.services import documents
from app.services.workbench import Workbench

pytestmark = pytest.mark.evaluation

FEATURES = [
    Features(language="de", buildings=True, type_column=True),
    Features(language="de", buildings=True, keys=True),
    Features(language="en", buildings=True),
    Features(language="de", buildings=False, components=3),
]


def _folder(root: Path) -> Path:
    folder = root / "bills"
    folder.mkdir()
    for index, features in enumerate(FEATURES):
        bill = generate_bill(random.Random(40 + index), features, 160)
        (folder / f"bill-{index}.xlsx").write_bytes(render_xlsx(bill))
    bill = generate_bill(random.Random(50), Features(language="de", buildings=True), 120)
    (folder / "bill-csv.csv").write_bytes(render_csv(bill))
    (folder / "broken.xlsx").write_bytes(b"not a workbook")
    (folder / "notes.txt").write_text("not a bill", encoding="utf-8")
    return folder


def _state(folder: Path) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()}


def test_planting_happens_in_memory_and_leaves_the_folder_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _folder(tmp_path)
    before = _state(folder)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    report = run_injection(folder, InjectConfig(), tmp_path / "out")
    assert _state(folder) == before  # no file changed, none added
    assert list(scratch.iterdir()) == []  # the temporary workbench is gone
    assert (tmp_path / "out" / "inject-report.md").is_file()
    assert (tmp_path / "out" / "inject-report.json").is_file()
    files = {entry["file"]: entry for entry in report["files"]}
    assert set(files) == {
        "bill-0.xlsx",
        "bill-1.xlsx",
        "bill-2.xlsx",
        "bill-3.xlsx",
        "bill-csv.csv",
        "broken.xlsx",
    }
    assert files["broken.xlsx"]["status"] == "not read"
    assert all(files[name]["status"] == "planted" for name in files if name != "broken.xlsx")
    boq = report["boq"]
    assert boq["planted_errors"] >= 30
    planted = {kind for kind, entry in boq["by_kind"].items() if entry["planted"]}
    assert len(planted) >= 20
    for kind, entry in boq["by_kind"].items():
        rule_kind = all(check["step"] == "available" for check in entry["expected_checks"])
        if entry["status"] == "measured" and entry["planted"] and rule_kind:
            # The rule checks find every error planted for them, in its cell (the signal
            # checks of B3 are measured too, without that promise).
            assert entry["recall"] == 1.0 and entry["cell_localization"] == 1.0, kind
    # Planting carried every changed amount into its totals: no rule check reports anything
    # the bill did not already hold.
    added = [
        o for o in report["other_findings"] if o["check"] == "rule" and not o["in_file_as_read"]
    ]
    assert added == []
    assert report["label"] == LABEL
    printed = summary(report)
    assert LABEL in printed and "bill-0" not in printed  # counts only, no names or rows


def test_the_same_seed_plants_the_same_errors(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    first = run_injection(folder, InjectConfig(seed=3, max_errors=4), tmp_path / "a")
    again = run_injection(folder, InjectConfig(seed=3, max_errors=4), tmp_path / "b")
    assert first["boq"] == again["boq"] and first["files"] == again["files"]


def test_the_report_never_goes_into_the_folder(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        run_injection(folder, InjectConfig(), folder / "out")
    with pytest.raises(SystemExit):
        main(["--inject-into", str(folder), "--out", str(folder)])
    with pytest.raises(ValueError, match="does not exist"):
        run_injection(tmp_path / "missing", InjectConfig(), tmp_path / "out")


def test_command_line_prints_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _folder(tmp_path)
    main(["--inject-into", str(folder), "--max-errors", "3", "--out", str(tmp_path / "out")])
    output = capsys.readouterr().out
    assert "# Planted errors in your bills" in output and "bill-1" not in output
    assert "inject-report.md" in output


def _datasets(tmp_path: Path) -> tuple[Workbench, list[Dataset]]:
    wb = benchmark_workbench(tmp_path)
    result = []
    for seed in range(6):
        features = Features(language="de", buildings=True, components=3 if seed == 0 else 0)
        bill = generate_bill(random.Random(seed), features, 160)
        doc = document(bill, name=f"b{seed}", file_format="xlsx")
        # The first bill's EP-Anteil columns are mapped as a reviewer would map them.
        _, dataset = documents.upload(
            wb,
            filename=doc.name,
            chunks=[doc.content],
            profile_id="boq",
            decisions=doc.decisions(),
        )
        assert dataset is not None
        result.append(dataset)
    return wb, result


@pytest.fixture(scope="module")
def uploaded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Workbench, list[Dataset]]:
    return _datasets(tmp_path_factory.mktemp("inject"))


@pytest.mark.parametrize(
    "kind", [k for k in ErrorKind if k is not ErrorKind.COMPONENT_SUM_ERROR], ids=lambda k: k.value
)
def test_each_kind_changes_the_cell_its_ground_truth_names(
    uploaded: tuple[Workbench, list[Dataset]], kind: ErrorKind
) -> None:
    wb, datasets = uploaded
    for dataset in datasets:
        sheet = sheet_for(dataset, random.Random(1), lambda: wb.ids.new(IdPrefix.ROW), "t")
        assert sheet is not None
        if plant_table(sheet, [kind]) == []:
            break
    else:
        raise AssertionError(f"no bill took {kind}")
    [truth] = truths(sheet)
    planted = planted_dataset(dataset, sheet)
    assert (planted.revision, planted.parent_revision) == (dataset.revision + 1, dataset.revision)
    [old_table] = dataset.tables
    [table] = planted.tables
    old_rows = {row.row_id: row for row in old_table.rows}
    target = sheet.planted[0].target
    row = next(r for r in table.rows if r.row_id == target)
    assert row.source_row_number == truth.row
    assert [r.position for r in table.rows] == list(range(len(table.rows)))
    if kind in (
        ErrorKind.DUPLICATE_ROW,
        ErrorKind.DUPLICATE_POSITION,
        ErrorKind.NEAR_DUPLICATE_POSITION,
    ):
        assert target not in old_rows and len(table.rows) == len(old_table.rows) + 1
        assert truth.row > max(r.source_row_number for r in old_table.rows)
        return
    assert len(table.rows) == len(old_table.rows)
    if kind is ErrorKind.MISPLACED_POSITION:
        assert row.section_path != old_rows[target].section_path
        return
    column = next(
        c.column_id for c in table.columns if c.mapping and c.mapping.field_id == truth.field
    )
    assert row.cells[column] != old_rows[target].cells[column]


def test_a_kind_no_row_fits_is_reported_with_its_need(
    uploaded: tuple[Workbench, list[Dataset]],
) -> None:
    wb, datasets = uploaded
    sheet = sheet_for(datasets[1], random.Random(1), lambda: wb.ids.new(IdPrefix.ROW), "t")
    assert sheet is not None
    assert plant_table(sheet, [ErrorKind.COMPONENT_SUM_ERROR]) == [ErrorKind.COMPONENT_SUM_ERROR]
    assert NEEDS[ErrorKind.COMPONENT_SUM_ERROR]


def test_a_component_error_goes_into_the_component_columns_a_reviewer_mapped(
    uploaded: tuple[Workbench, list[Dataset]],
) -> None:
    wb, datasets = uploaded
    dataset = datasets[0]  # the bill with three EP-Anteil columns, mapped by "a reviewer"
    sheet = sheet_for(dataset, random.Random(2), lambda: wb.ids.new(IdPrefix.ROW), "t")
    assert sheet is not None
    components = [
        c.column_id
        for c in sheet.table.columns
        if (c.original_header or "").startswith("EP-Anteil")
    ]
    assert len(components) == 3
    for k, column in enumerate(components, start=1):
        assert sheet.columns[f"unit_price_component_{k}"] == column
    assert plant_table(sheet, [ErrorKind.COMPONENT_SUM_ERROR]) == []
    [truth] = truths(sheet)
    assert truth.field is not None and truth.field.startswith("unit_price_component_")
    row = sheet.rows[sheet.index(sheet.planted[0].target)]
    values = [sheet.number(row, f"unit_price_component_{k}") for k in (1, 2, 3)]
    assert sum(v for v in values if v is not None) != sheet.number(row, "unit_price")


def test_component_errors_need_component_columns_a_reviewer_maps(tmp_path: Path) -> None:
    # No header maps the unit price components, and nothing reviews a folder's bills, so their
    # EP-Anteil columns stay unmapped and the kind is reported as not planted, with its need.
    folder = tmp_path / "bills"
    folder.mkdir()
    bill = generate_bill(random.Random(7), Features(language="de", components=3), 120)
    (folder / "components.xlsx").write_bytes(render_xlsx(bill))
    config = InjectConfig(kinds=(ErrorKind.COMPONENT_SUM_ERROR,), max_errors=1)
    report = run_injection(folder, config, tmp_path / "out")
    assert [(f["file"], f["planted"]) for f in report["files"]] == [("components.xlsx", 0)]
    assert report["not_planted"] == {
        ErrorKind.COMPONENT_SUM_ERROR.value: NEEDS[ErrorKind.COMPONENT_SUM_ERROR]
    }
    entry = report["boq"]["by_kind"][ErrorKind.COMPONENT_SUM_ERROR.value]
    # Its check exists (deterministic.unit_price_components), but nothing was planted to measure.
    assert entry["planted"] == 0 and entry["status"] == "measured" and entry["recall"] is None
    # With nothing planted, the run adds no rule finding of its own.
    added = [
        o for o in report["other_findings"] if o["check"] == "rule" and not o["in_file_as_read"]
    ]
    assert added == []


def test_the_markdown_report_lists_every_unmatched_finding() -> None:
    report = {
        "label": LABEL,
        "planting": "in memory.",
        "seed": 1,
        "max_errors": 2,
        "profile_id": "boq",
        "files": [
            {"file": "a.xlsx", "status": "planted", "rows": 9, "item_rows": 7, "planted": 1,
             "first_inserted_row": 12},
            {"file": "b.csv", "status": "not read", "rows": 0, "planted": 0, "reason": "x"},
        ],
        "not_planted": {"tax_mismatch": NEEDS[ErrorKind.TAX]},
        "boq": {
            "by_kind": {},
            "missed": [{"document": "a.xlsx", "error_id": "b1-e1", "kind": "line_total_slip",
                        "row": 4, "change": "line total ×10", "rules_found": []}],
        },
        "other_findings": [
            {"file": "a.xlsx", "rows": [5], "detector_id": "d", "rule_id": "r", "severity": "low",
             "check": "rule", "in_file_as_read": True, "title": "t"},
            {"file": "a.xlsx", "rows": [], "detector_id": "s", "rule_id": "q", "severity": "info",
             "check": "signal", "in_file_as_read": False, "title": "u"},
        ],
        "timing": {"total_seconds": 1.25},
    }  # fmt: skip
    markdown = render(report)
    assert "| a.xlsx | planted | 9 | 7 | 1 | 12 |" in markdown
    assert "| b.csv | not read (x) | 0 |  | 0 |  |" in markdown
    assert f"- `tax_mismatch`: {NEEDS[ErrorKind.TAX]}" in markdown
    assert "| a.xlsx | b1-e1 | `line_total_slip` | 4 | line total ×10 | none |" in markdown
    assert "| a.xlsx | 5 | `d` | `r` | low | rule | yes | t |" in markdown
    assert "| a.xlsx | table | `s` | `q` | info | signal | no | u |" in markdown
    assert "The run took 1.2 s." in markdown or "The run took 1.3 s." in markdown
    assert summary({**report, "boq": {**report["boq"], "planted_errors": 1}}).count("a.xlsx") == 0


def test_a_text_without_a_small_change_gets_no_near_duplicate(
    uploaded: tuple[Workbench, list[Dataset]],
) -> None:
    wb, datasets = uploaded
    sheet = sheet_for(datasets[1], random.Random(1), lambda: wb.ids.new(IdPrefix.ROW), "t")
    assert sheet is not None
    index = next(
        i for i, row in enumerate(sheet.rows) if row.row_id in {r.row_id for r in _items(sheet)}
    )
    source = sheet.cell(sheet.rows[index], "description").source
    sheet.with_cell(index, "description", text_cell("X 1", source))
    assert _near_duplicate_position(sheet, sheet.rows[index]) is None
    assert sheet.planted == []
