"""The synthetic benchmark: reproducible corpus, honest scoring, every error kind found."""

from __future__ import annotations

import dataclasses
import io
import json
import random
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from app.evaluation.__main__ import main
from app.evaluation.runner import (
    DISCLAIMER,
    BenchmarkConfig,
    benchmark_workbench,
    evaluate,
    run_benchmark,
    signal_checks,
)
from app.evaluation.scoring import (
    RISK_NOTES_LINE,
    Finding,
    Tally,
    is_correct_risk_note,
    risk_notes_text,
    score_document,
)
from app.evaluation.synthetic import (
    EXPECTED_RULES,
    STANDARD_KINDS,
    STYLES,
    WORKBOOK_TIMESTAMP,
    CorpusConfig,
    ErrorKind,
    GroundTruth,
    corrupt,
    document,
    generate_bill,
    generate_corpus,
    inject,
)

pytestmark = pytest.mark.evaluation
SMALL = CorpusConfig(documents_per_variant=2, sections=(1, 3), items_per_section=(3, 8))
VARIANTS = [(language, file_format) for language in STYLES for file_format in ("xlsx", "csv")]
# domain.boq_position_types lists the contingency positions of a German bill ("..., Bedarfsposition
# ohne GB"): one finding on such a bill, by design, which finds no error. The scoring checks it
# against the generator's own item types: a correct note, not a false positive.
POSITION_TYPES = "domain.boq_position_types"
LIST_RULE = "contingency_and_hourly"


def _single(language: str, file_format: str, kinds: list[ErrorKind], seed: int = 7):
    """A small bill (few terms per total, so CSV display-rounding allowances stay below the
    smallest injected slip) with the given errors."""
    rng = random.Random(seed)
    bill = generate_bill(rng, STYLES[language], sections=(1, 2), items=(3, 5))
    inject(rng, bill, kinds, prefix="t")
    return document(bill, name=f"{language}-{'-'.join(kinds) or 'clean'}", file_format=file_format)


def _xlsx_values(content: bytes) -> list[tuple[object, ...]]:
    return list(load_workbook(io.BytesIO(content)).active.iter_rows(values_only=True))


def test_the_corpus_is_reproducible() -> None:
    first, second = generate_corpus(SMALL), generate_corpus(SMALL)
    assert [d.name for d in first] == [d.name for d in second]
    for a, b in zip(first, second, strict=True):
        assert (a.truths, a.row_kinds) == (b.truths, b.row_kinds)
        if a.format == "csv":
            assert a.content == b.content
        else:
            assert _xlsx_values(a.content) == _xlsx_values(b.content)
    other = generate_corpus(CorpusConfig(seed=1, documents_per_variant=2))
    assert [d.row_kinds for d in other] != [d.row_kinds for d in first]
    assert {d.format for d in first} == {"xlsx", "csv"} and {d.language for d in first} == {
        "en",
        "de",
    }


def test_xlsx_files_carry_fixed_timestamps_not_the_time_of_the_run() -> None:
    """Document properties and ZIP member times are fixed, so the bytes depend on the seed only
    (a comparison of two quick runs alone could pass within the same second)."""
    content = _single("de", "xlsx", [ErrorKind.LINE_TOTAL]).content
    with ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        assert "docProps/core.xml" in archive.namelist()
    assert members and {member.date_time for member in members} == {
        WORKBOOK_TIMESTAMP.timetuple()[:6]
    }
    properties = load_workbook(io.BytesIO(content)).properties
    assert properties.created == properties.modified == WORKBOOK_TIMESTAMP


def test_two_runs_with_the_same_seed_write_identical_files_and_hashes(tmp_path: Path) -> None:
    corpus = CorpusConfig(documents_per_variant=1, sections=(1, 2), items_per_section=(3, 5))
    first, second = tmp_path / "first", tmp_path / "second"
    for out in (first, second):
        run_benchmark(BenchmarkConfig(corpus=corpus), out)
    manifest = (first / "manifest.json").read_bytes()
    assert manifest == (second / "manifest.json").read_bytes()
    names = sorted(path.name for path in (first / "documents").iterdir())
    assert names == sorted(path.name for path in (second / "documents").iterdir())
    assert {name.rsplit(".", 1)[1] for name in names} == {"xlsx", "csv"}
    for name in names:
        assert (first / "documents" / name).read_bytes() == (
            second / "documents" / name
        ).read_bytes()


def test_corruption_is_a_digit_swap() -> None:
    rng = random.Random(3)
    for value in (Decimal("1250.40"), Decimal("7.05"), Decimal("1000.00")):
        wrong = corrupt(rng, value)
        assert abs(wrong - value) >= Decimal("0.09")  # always beyond the 0.01 tolerance
        written = f"{value:.2f}"
        assert sorted(f"{wrong:.2f}".rjust(len(written), "0")) == sorted(written)  # same digits
    assert corrupt(rng, Decimal("11.11")) == Decimal("111.11")  # no two digits differ


def test_ground_truth_points_at_the_injected_cells() -> None:
    doc = _single("de", "csv", [ErrorKind.DUPLICATE_ROW, ErrorKind.NET_TOTAL])
    rows = doc.content.decode("utf-8").splitlines()
    by_kind = {truth.kind: truth for truth in doc.truths}
    duplicate = by_kind[ErrorKind.DUPLICATE_ROW]
    assert rows[duplicate.row - 1] == rows[duplicate.row - 2]  # the copy follows its original
    assert duplicate.rows == (duplicate.row - 1, duplicate.row) and duplicate.field is None
    net = by_kind[ErrorKind.NET_TOTAL]
    assert rows[net.row - 1].startswith(";Gesamtsumme netto;")
    assert net.rows == (net.row, net.row + 1, net.row + 2)  # tax and gross follow
    assert doc.row_kinds[net.row] == "grand_total"


@pytest.mark.parametrize(("language", "file_format"), VARIANTS)
def test_clean_bills_have_no_rule_findings(tmp_path: Path, language: str, file_format: str) -> None:
    # Every check runs; the signal checks may flag a clean bill (counted in the BoQ report as
    # signals on unplanted rows), the rule checks may not.
    wb = benchmark_workbench(tmp_path)
    signals = signal_checks(wb)
    for seed in range(4):
        result = evaluate(wb, _single(language, file_format, [], seed), k=5, profile_id="boq")
        rules = [f for f in result.score.false_positives if f.detector_id not in signals]
        assert rules == [], rules
        notes = result.score.correct_notes
        assert len(notes) <= (1 if language == "de" else 0), notes
        assert {(f.detector_id, f.rule_id) for f in notes} <= {(POSITION_TYPES, LIST_RULE)}
        doc = _single(language, file_format, [], seed)
        assert all(f.rows <= doc.contingency_and_hourly_rows for f in notes)
        assert result.misclassified == ()


@pytest.mark.parametrize(("language", "file_format"), VARIANTS)
def test_every_error_kind_is_found_and_localized(
    tmp_path: Path, language: str, file_format: str
) -> None:
    wb = benchmark_workbench(tmp_path)
    for kind in STANDARD_KINDS:
        doc = _single(language, file_format, [kind])
        result = evaluate(wb, doc, k=5, profile_id="boq")
        [outcome] = result.score.outcomes
        assert outcome.detected and outcome.localized, (kind, outcome)
        assert set(outcome.rules) & set(EXPECTED_RULES[kind]), (kind, outcome.rules)
        assert result.score.false_positives == (), kind


def _truth(row: int, field: str | None = "line_total", rows: tuple[int, ...] = ()) -> GroundTruth:
    return GroundTruth(
        error_id=f"e{row}",
        kind=ErrorKind.LINE_TOTAL,
        row=row,
        field=field,
        rows=rows or (row,),
        expected_rules=("line_total_mismatch",),
        change="",
    )


def _finding(rows: set[int], cells: set[tuple[int, str | None]] = frozenset(), rule="x"):
    return Finding("i", "d", rule, "high", "t", frozenset(rows), frozenset(cells))


def test_budget_recall_counts_errors_not_duplicate_alerts_at_both_boundaries() -> None:
    truths = [_truth(row) for row in (1, 20, 21, 50, 51, 99)]
    findings = [_finding({row}) for row in range(1, 52)]
    # Replace a false alarm with a second alert for error 1: recall must not count it twice.
    findings[1] = _finding({1})
    tally = Tally()
    tally.add(score_document(findings, truths, k=20), rows=100, classified=(0, 0), seconds=0)
    metrics = tally.metrics()
    assert metrics["recall_at_20"] == pytest.approx(2 / 6)
    assert metrics["recall_at_50"] == pytest.approx(4 / 6)
    assert metrics["recall"] == pytest.approx(5 / 6)


def test_scoring_arithmetic() -> None:
    truths = [_truth(5), _truth(9, rows=(9, 20)), _truth(30)]
    findings = [
        _finding({20}),  # the total thrown off by error 9: a true positive
        _finding({5}, {(5, "line_total")}, rule="line_total_mismatch"),  # exact cell
        _finding({7}),  # nothing was injected in row 7: a false positive
    ]
    score = score_document(findings, truths, k=2)
    assert score.true_positives == 2 and [f.rows for f in score.false_positives] == [{7}]
    assert [(o.detected, o.localized, o.expected_rule) for o in score.outcomes] == [
        (True, True, True),
        (True, False, False),
        (False, False, False),
    ]
    assert score.precision_at_k == 1.0  # the first two findings are both true positives
    tally = Tally()
    tally.add(score, rows=500, classified=(499, 500), seconds=0.5)
    tally.add(score_document([], [], k=2), rows=500, classified=(500, 500), seconds=0.5)
    metrics = tally.metrics()
    assert metrics["precision"] == pytest.approx(2 / 3)
    assert metrics["recall"] == pytest.approx(2 / 3)
    assert metrics["f1"] == pytest.approx(2 / 3)
    assert metrics["precision_at_k"] == 1.0  # documents without findings are not averaged
    assert metrics["false_positives_per_1000_rows"] == 1.0
    assert metrics["cell_localization"] == 0.5
    assert metrics["row_classification_accuracy"] == pytest.approx(999 / 1000)


def _note(rows: set[int]) -> Finding:
    """A list of contingency positions naming ``rows``."""
    return Finding("n", POSITION_TYPES, LIST_RULE, "low", "list", frozenset(rows), frozenset())


def test_a_correct_risk_note_is_not_a_false_positive() -> None:
    """A list of contingency positions every row of which is one in the generated bill claims no
    error: counted on its own, outside precision and false positives (decision of 2026-11-21,
    for the owner to confirm)."""
    contingency = frozenset({12, 14})
    findings = [_note({12, 14}), _finding({5}, {(5, "line_total")}), _finding({7})]
    score = score_document(findings, [_truth(5)], k=5, noted_rows=contingency)
    assert [f.rows for f in score.correct_notes] == [{12, 14}]
    assert [f.rows for f in score.false_positives] == [{7}]
    assert score.true_positives == 1 and score.findings == 3
    assert score.precision_at_k == 0.5  # the note is left out of the findings shown
    tally = Tally()
    tally.add(score, rows=1000, classified=(0, 0), seconds=0.0)
    metrics = tally.metrics()
    assert metrics["correct_risk_notes"] == 1 and metrics["false_positive_findings"] == 1
    assert metrics["precision"] == 0.5  # one true and one false positive
    assert metrics["false_positives_per_1000_rows"] == 1.0
    # A note alone leaves nothing to rank.
    assert score_document([_note({12})], [], k=5, noted_rows=contingency).precision_at_k is None


def test_a_risk_note_naming_another_row_is_a_false_positive() -> None:
    contingency = frozenset({12, 14})
    wrong = _note({12, 13})  # row 13 is no contingency position of the bill
    score = score_document([wrong], [], k=5, noted_rows=contingency)
    assert score.correct_notes == () and score.false_positives == (wrong,)
    assert not is_correct_risk_note(_note(set()), contingency)  # a note must name rows
    # Only the list rule is a risk note: another finding on a contingency row stays false.
    other = _finding({12})
    assert score_document([other], [], k=5, noted_rows=contingency).false_positives == (other,)
    # Without the generator's truth (a real file), every list is a false positive.
    assert score_document([_note({12})], [], k=5).false_positives != ()


def test_a_risk_note_is_scored_by_every_row_it_names() -> None:
    """The highlighted cells of a long list stop at a cap; the rows of its evidence count too,
    so a wrong position after the cap still makes the list a false positive."""
    contingency = frozenset({12, 14, 16})
    long = Finding(
        "n", POSITION_TYPES, LIST_RULE, "low", "list", frozenset({12}), frozenset(),
        evidence_rows=frozenset({12, 14, 99}),
    )  # fmt: skip
    score = score_document([long], [], k=5, noted_rows=contingency)
    assert score.false_positives == (long,) and score.correct_notes == ()
    right = dataclasses.replace(long, evidence_rows=frozenset({12, 14, 16}))
    assert score_document([right], [], k=5, noted_rows=contingency).correct_notes == (right,)
    # Evidence rows are read only for a risk note: another finding is located as before.
    other = dataclasses.replace(_finding({5}), evidence_rows=frozenset({7}))
    assert score_document([other], [_truth(5)], k=5).true_positives == 1


def test_a_wrong_risk_note_on_a_planted_row_is_still_a_false_positive() -> None:
    """Decision 3: a list naming one non-contingency row is a false positive, even when it also
    names a row with an injected error; a correct list there is a true positive."""
    contingency = frozenset({12, 14})
    wrong = _note({12, 13})
    score = score_document([wrong], [_truth(12)], k=5, noted_rows=contingency)
    assert score.true_positives == 0 and score.false_positives == (wrong,)
    assert score.correct_notes == () and not score.outcomes[0].detected
    right = _note({12, 14})
    score = score_document([right], [_truth(12)], k=5, noted_rows=contingency)
    assert score.true_positives == 1 and score.outcomes[0].detected
    assert score.false_positives == () and score.correct_notes == ()


def test_budget_recall_reads_the_list_precision_at_k_reads() -> None:
    """Recall at 20/50 counts the findings that precision at K counts: a correct risk note takes
    no place in the first 20, a wrong one takes its place and matches nothing."""
    contingency = frozenset({500})
    truths = [_truth(20), _truth(21)]
    findings = [_note({500}), *(_finding({row}) for row in range(2, 22))]
    score = score_document(findings, truths, k=20, noted_rows=contingency)
    assert score.correct_notes == (findings[0],)
    assert score.detected_at_20 == 2  # rows 20 and 21 are the 19th and 20th finding after it
    # A wrong note that names row 21 does not find its error, and pushes row 21 to place 21.
    wrong = _note({21, 600})
    findings = [wrong, *(_finding({row}) for row in range(2, 21)), _finding({21})]
    score = score_document(findings, [_truth(21)], k=20, noted_rows=contingency)
    assert score.false_positives[0] is wrong
    assert (score.detected_at_20, score.detected_at_50) == (0, 1)


def test_the_risk_notes_line() -> None:
    assert RISK_NOTES_LINE == "Risk notes on unplanted rows, checked against the generated bill"
    assert risk_notes_text(47, 0) == "47, all correct"
    assert risk_notes_text(3, 1) == "4, 3 correct (1 counted as false positives)"


def test_the_generator_records_its_contingency_positions() -> None:
    """German bills mark contingency positions "Bedarfsposition mit/ohne GB"; the document
    records their rows. English bills type no contingency position."""
    seen = 0
    for seed in range(12):
        for language in ("de", "en"):
            rng = random.Random(seed)
            bill = generate_bill(rng, STYLES[language], sections=(2, 4), items=(5, 10))
            doc = document(bill, name="b", file_format="csv")
            marked = {
                bill.row_of(line)
                for line in bill.lines
                if line.kind == "item" and "Bedarfsposition" in line.text
            }
            assert doc.contingency_and_hourly_rows == marked
            seen += len(marked)
            if language == "en":
                assert marked == set()
    assert seen > 0


def test_a_row_level_error_is_localized_by_its_row() -> None:
    truth = _truth(12, field=None, rows=(11, 12))
    [outcome] = score_document([_finding({11, 12})], [truth], k=5).outcomes
    assert outcome.localized


def test_benchmark_run_writes_report_and_manifest(tmp_path: Path) -> None:
    corpus = CorpusConfig(documents_per_variant=1, sections=(1, 2), items_per_section=(3, 6))
    report = run_benchmark(BenchmarkConfig(corpus=corpus), tmp_path)
    assert report["disclaimer"] == DISCLAIMER and report["real_world"] is None
    synthetic = report["synthetic"]
    assert synthetic["documents"] == 4
    for name in ("precision", "recall", "row_classification_accuracy"):
        assert synthetic[name] is None or 0 <= synthetic[name] <= 1
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["documents"]) == 4
    for entry in manifest["documents"]:
        assert (tmp_path / "documents" / entry["name"]).is_file()
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Synthetic documents only" in markdown and "## Real-world documents" in markdown
    notes = report["risk_notes"]
    assert notes["correct"] == synthetic["correct_risk_notes"] and notes["false"] == 0
    assert f"| {RISK_NOTES_LINE} | {notes['correct']}, all correct |" in markdown
    # Recall in the first 20/50 skips the correct risk notes, as its label says.
    for budget in (20, 50):
        label = (
            f"Recall in first {budget} findings (register order, correct risk notes on "
            "unplanted rows take no place)"
        )
        assert f"| {label} | " in markdown
    assert "Like precision at K, it passes over correct risk notes on unplanted rows" in markdown
    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert written == json.loads(json.dumps(report))


def test_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--documents", "1", "--max-errors", "1", "--out", str(tmp_path / "out")])
    assert "# Synthetic benchmark report" in capsys.readouterr().out
    assert (tmp_path / "out" / "report.json").is_file()
