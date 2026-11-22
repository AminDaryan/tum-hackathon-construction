"""The boq corpus variant: generation, planting, ground truth, and what today's checks find."""

from __future__ import annotations

import copy
import json
import random
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.boq import (
    COUNTED,
    WITH_TOTAL,
    WITHOUT_TOTAL,
    BoqBill,
    BoqLine,
    Features,
    document,
    eligible,
    features_of,
    generate_bill,
    near_text,
    plant,
    recompute_totals,
    render_csv,
    truths,
)
from app.evaluation.prices import Language
from app.evaluation.runner import (
    BenchmarkConfig,
    benchmark_workbench,
    evaluate,
    run_benchmark,
    signal_checks,
)
from app.evaluation.synthetic import (
    EXPECTED_RULES,
    STANDARD_KINDS,
    BoqSettings,
    CorpusConfig,
    ErrorKind,
    generate_corpus,
)
from app.repositories.base import IssueQuery
from app.services import documents, runs
from app.services.workbench import Workbench
from app.validation.domain.boq import position_types
from app.validation.support.items import item_frame
from tests.support.builders import make_context

pytestmark = pytest.mark.evaluation

# domain.boq_position_types lists the contingency positions of a German bill (B2 brief D): one
# finding on every such bill, clean or not, by design. It finds no error: the scoring checks it
# against the generator's item types and counts it as a correct risk note, so the checks below
# expect exactly that note and no false positive.
POSITION_TYPES = "domain.boq_position_types"


def _lists_contingency(bill: BoqBill) -> bool:
    """Whether domain.boq_position_types lists contingency positions of ``bill``: German bills
    mark them in words or item type codes it reads; English bills say "not included in the
    total", which it does not read."""
    contingency = (WITH_TOTAL, WITHOUT_TOTAL)
    return bill.style.language == "de" and any(
        line.item_type in contingency for line in bill.items()
    )


def _listings(bill: BoqBill) -> list[str]:
    """The detectors of the findings a clean ``bill`` gets."""
    return [POSITION_TYPES] if _lists_contingency(bill) else []


CENT = Decimal("0.01")
KEY_CHECK = "domain.standard_text_keys"
TOTAL_KINDS = ("subtotal", "grand_total", "tax", "gross_total")
INSERTED = (
    ErrorKind.DUPLICATE_ROW,
    ErrorKind.DUPLICATE_POSITION,
    ErrorKind.NEAR_DUPLICATE_POSITION,
)
PRICE = {"unit_price", "total"}
QUANTITY = {"quantity", "total"}
CHANGED: dict[ErrorKind, set[str]] = {
    ErrorKind.LINE_TOTAL: {"total"},
    ErrorKind.LINE_TOTAL_SLIP: {"total"},
    ErrorKind.UNKNOWN_UNIT: {"unit"},
    ErrorKind.WRONG_UNIT: {"unit"},
    ErrorKind.MISSING_PRICE: {"unit_price"},
    ErrorKind.INVALID_QUANTITY: {"quantity"},
    ErrorKind.CODE_OUTSIDE_SECTION: {"code"},
    ErrorKind.PRICE_DECIMAL_SLIP: PRICE,
    ErrorKind.PRICE_DIGIT_SWAP: PRICE,
    ErrorKind.INCONSISTENT_RATE: PRICE,
    ErrorKind.WRONG_RATE_COPIED: PRICE,
    ErrorKind.PLACEHOLDER_PRICE: PRICE,
    ErrorKind.HIGH_CONTINGENCY_PRICE: PRICE,
    ErrorKind.PRICE_PER_WRONG_UNIT: PRICE,
    ErrorKind.QUANTITY_DECIMAL_SLIP: QUANTITY,
    ErrorKind.QUANTITY_UNIT_SLIP: QUANTITY,
}


def _cells(line: BoqLine) -> dict[str, object]:
    return {
        "code": line.code,
        "text": line.text,
        "quantity": line.quantity,
        "unit": (line.unit, line.unit_text),
        "unit_price": line.unit_price,
        "total": line.total,
        **{f"unit_price_component_{i}": c for i, c in enumerate(line.components, start=1)},
    }


def _planted(
    kind: ErrorKind, language: Language = "de", *, keys: bool = False
) -> tuple[BoqBill, BoqBill]:
    """A clean bill and the same bill with one error of ``kind``."""
    features = Features(
        language=language,
        buildings=True,
        keys=keys,
        components=3 if kind is ErrorKind.COMPONENT_SUM_ERROR else 0,
    )
    for seed in range(60):
        clean = generate_bill(random.Random(seed), features, 120)
        bill = copy.deepcopy(clean)
        if eligible(bill, kind):
            plant(random.Random(seed), bill, [kind], "t")
            if bill.planted:
                return clean, bill
    raise AssertionError(f"no bill took {kind}")


def _consistent_totals(bill: BoqBill) -> None:
    summed = copy.deepcopy(bill)
    recompute_totals(summed)
    for line, again in zip(bill.lines, summed.lines, strict=True):
        assert line.total == again.total, (line.kind, line.text)


@pytest.mark.parametrize("kind", list(ErrorKind), ids=lambda kind: kind.value)
def test_each_kind_changes_only_what_its_ground_truth_names(kind: ErrorKind) -> None:
    clean, bill = _planted(kind)
    [truth] = truths(bill)
    target = bill.planted[0].target
    assert truth.kind is kind and truth.expected_rules == EXPECTED_RULES[kind]
    assert truth.row == bill.row_of(target) and truth.row in truth.rows
    related = {bill.row_of(line) for line in bill.planted[0].related}
    assert set(truth.rows) == {truth.row, *related}
    if kind in INSERTED:
        assert len(bill.lines) == len(clean.lines) + 1
        assert all(line is not target for line in clean.lines)
        [original] = [line for line in bill.planted[0].related if line.text == target.text] or [
            bill.planted[0].related[0]
        ]
        assert (target.unit, target.unit_price) == (original.unit, original.unit_price)
        if kind is ErrorKind.DUPLICATE_ROW:
            assert _cells(target) == _cells(original)
        else:
            assert target.code != original.code and target.section == original.section
        if kind is ErrorKind.NEAR_DUPLICATE_POSITION:
            assert target.text != original.text
        _consistent_totals(bill)
        return
    assert len(bill.lines) == len(clean.lines)
    if kind is ErrorKind.MISPLACED_POSITION:
        [before] = [
            line
            for line in clean.lines
            if _cells(line) == {**_cells(target), "code": line.code}
            and line.section != target.section
        ]
        assert target.code is not None and target.section is not None
        assert target.code.startswith(target.section)
        _consistent_totals(bill)
        return
    index = bill.lines.index(target)
    before = clean.lines[index]
    if kind in (ErrorKind.SUBTOTAL, ErrorKind.NET_TOTAL, ErrorKind.TAX):
        changed_rows = [
            bill.row_of(line)
            for line, old in zip(bill.lines, clean.lines, strict=True)
            if _cells(line) != _cells(old)
        ]
        gross = [bill.row_of(line) for line in bill.lines if line.kind == "gross_total"]
        assert set(changed_rows) == ({truth.row, *gross} if kind is ErrorKind.TAX else {truth.row})
        return
    changed = {name for name, value in _cells(target).items() if _cells(before)[name] != value}
    expected = {truth.field} if kind is ErrorKind.COMPONENT_SUM_ERROR else CHANGED[kind]
    assert changed == expected, kind
    for line, old in zip(bill.lines, clean.lines, strict=True):
        if line is not target and line.kind not in TOTAL_KINDS:
            assert _cells(line) == _cells(old)
    _consistent_totals(bill)


def test_a_clean_bill_adds_up() -> None:
    bill = generate_bill(random.Random(2), Features(language="de", buildings=True), 200)
    assert 140 <= len(bill.items()) <= 260  # about 200: Titel sizes vary by up to 30 %
    for line in bill.items():
        assert isinstance(line.quantity, Decimal) and line.unit_price is not None
        expected = (line.quantity * line.unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
        assert line.total == expected
    net = sum(line.total or 0 for line in bill.items() if line.item_type in COUNTED)
    [grand] = [line for line in bill.lines if line.kind == "grand_total"]
    [tax] = [line for line in bill.lines if line.kind == "tax"]
    [gross] = [line for line in bill.lines if line.kind == "gross_total"]
    assert grand.total == net
    assert tax.total == (net * bill.style.tax_rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    assert gross.total == net + tax.total
    _consistent_totals(bill)


def test_the_same_work_has_the_same_unit_price_in_every_building() -> None:
    bill = generate_bill(random.Random(4), Features(language="de", buildings=True), 300)
    prices: dict[tuple[str | None, tuple[int, ...]], set[Decimal | None]] = defaultdict(set)
    for line in bill.items():
        prices[(line.family, line.combo)].add(line.unit_price)
    assert all(len(found) == 1 for found in prices.values())
    assert any(bill.identical(line) for line in bill.items())  # positions repeat per building
    assert any(line.item_type == WITHOUT_TOTAL for line in bill.items())


def test_features_are_dealt_as_shares_of_all_bills() -> None:
    features = features_of(random.Random(1), 100, BoqSettings())
    german = [f for f in features if f.language == "de"]
    assert sum(f.language == "en" for f in features) == 25
    assert sum(f.buildings for f in features) == 25
    assert sum(f.keys for f in features) == 25 and sum(bool(f.components) for f in features) == 25
    assert sum(f.type_column for f in german) == round(len(german) * 0.5)
    typed = [f for f in german if f.type_column]  # every second one writes the import's names
    assert [f.type_names for f in typed] == [i % 2 == 1 for i in range(len(typed))]
    assert all(not f.type_names for f in features if not f.type_column)
    assert all(not (f.keys or f.components or f.type_column) for f in features if f not in german)
    assert all(f.components in (0, 2, 3, 4) for f in features)


def _config(seed: int = 11, documents: int = 4) -> CorpusConfig:
    return CorpusConfig(
        seed=seed,
        documents_per_variant=documents,
        max_errors=8,
        variant="boq",
        boq=BoqSettings(positions=(80, 120)),
    )


def test_the_boq_corpus_is_reproducible() -> None:
    first, again = generate_corpus(_config()), generate_corpus(_config())
    assert [d.name[-9:] for d in first] == [f"-{i:03d}.xlsx" for i in range(1, 5)]
    assert [d.name[:7] for d in first].count("boq-en-") == 1  # a quarter of the bills
    assert [d.content for d in first] == [d.content for d in again]
    assert [d.truths for d in first] == [d.truths for d in again]
    other = generate_corpus(_config(seed=12))
    assert [d.content for d in other] != [d.content for d in first]
    assert all(
        set(d.features)
        == {"positions", "buildings", "keys", "components", "type_column", "type_names"}
        for d in first
    )
    kinds = [t.kind for d in first for t in d.truths]
    assert len(kinds) == len({(d.name, t.kind) for d in first for t in d.truths})  # once a bill


def test_german_csv_uses_semicolons_and_decimal_commas() -> None:
    bill = generate_bill(random.Random(8), Features(language="de"), 80)
    text = render_csv(bill).decode("utf-8-sig")
    header = text.splitlines()[bill.header_row - 1]
    assert ";" in header and "Menge" in header
    assert any(
        "," in field and field.replace(",", "").replace(".", "").isdigit()
        for row in text.splitlines()
        for field in row.split(";")
    )


def _three_places(bill: BoqBill) -> list[BoqLine]:
    """The positions whose quantity has a third decimal place (masses in t)."""
    return [
        line
        for line in bill.items()
        if isinstance(line.quantity, Decimal) and line.quantity != line.quantity.quantize(CENT)
    ]


@pytest.mark.parametrize("language", ["de", "en"])
def test_csv_bills_keep_every_decimal_place_of_a_quantity(
    tmp_path: Path, language: Language
) -> None:
    bill = generate_bill(random.Random(1), Features(language=language, buildings=True), 200)
    assert _three_places(bill)  # masses in t carry three decimals
    wb = benchmark_workbench(tmp_path)
    doc = document(bill, name=f"masses-{language}", file_format="csv")
    assert doc.decisions() is None  # nothing to map: no unit price components
    _, dataset = documents.upload(wb, filename=doc.name, chunks=[doc.content], profile_id="boq")
    assert dataset is not None
    [table] = dataset.tables
    source_row = {row.row_id: row.source_row_number for row in table.rows}
    frame = item_frame(make_context(dataset, wb.profiles.get("boq")))
    read = {source_row[record.row_id]: record.quantity for record in frame.records}
    assert read == {bill.row_of(line): line.quantity for line in bill.items()}
    # So the line totals of the clean bill still agree with quantity x unit price.
    result = evaluate(wb, doc, k=5, profile_id="boq")
    assert result.score.false_positives == (), result.score.false_positives
    assert [f.detector_id for f in result.score.correct_notes] == _listings(bill)


def test_a_long_contingency_list_naming_a_normal_position_is_a_false_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 3 through the real evaluation: the list of a bill with more contingency
    positions than highlighted cells (20) wrongly names the bill's last normal position, after
    the cap. The scorer reads the whole list from the evidence and counts it as false."""
    bill = generate_bill(random.Random(2), Features(language="de"), 300)
    doc = document(bill, name="long-list", file_format="xlsx")
    noted = doc.contingency_and_hourly_rows
    assert len(noted) > 20
    wrong = max(r for r, kind in doc.row_kinds.items() if kind == "item" and r not in noted)
    original = position_types._contingency

    def listing_one_more(context: Any, config: Any, item: Any) -> Any:
        found = original(context, config, item)
        if found is None and item.row.source_row_number == wrong:
            cell = context.cell_ref(item.table, item.row, config.description_field)
            return position_types._Found(item, cell, "without")
        return found

    monkeypatch.setattr(position_types, "_contingency", listing_one_more)
    result = evaluate(benchmark_workbench(tmp_path), doc, k=5, profile_id="boq")
    [listing] = [f for f in result.score.false_positives if f.detector_id == POSITION_TYPES]
    assert wrong not in listing.rows  # not among the highlighted cells
    assert wrong in listing.evidence_rows and noted < listing.evidence_rows
    assert result.score.correct_notes == ()


def test_a_near_duplicate_text_changes_little() -> None:
    rng = random.Random(3)
    for text in ("Mauerwerk KS, 17,5 cm, Mörtelgruppe IIa", "Concrete C30/37, slabs"):
        changed = near_text(rng, text, "de" if "," in text[:20] else "en")
        assert changed != text and abs(len(changed) - len(text)) <= 12


# What the product finds today ---------------------------------------------------------------

COMBOS = [
    Features(language="de", buildings=b, keys=k, components=c, type_column=t, type_names=n)
    for b in (False, True)
    for k in (False, True)
    for c in (0, 3)
    for t, n in ((False, False), (True, False), (True, True))
] + [Features(language="en", buildings=b) for b in (False, True)]


def test_clean_boq_bills_produce_no_rule_finding(tmp_path: Path) -> None:
    # Every check runs; signal checks may flag a clean bill, rule checks may not.
    wb = benchmark_workbench(tmp_path)
    signals = signal_checks(wb)
    for index, features in enumerate(COMBOS):
        bill = generate_bill(random.Random(index), features, 80)
        for file_format in ("xlsx", "csv") if index % 9 == 0 else ("xlsx",):
            doc = document(bill, name=f"clean-{index}", file_format=file_format)
            result = evaluate(wb, doc, k=5, profile_id="boq")
            rules = [f for f in result.score.false_positives if f.detector_id not in signals]
            assert rules == [], (features, rules)
            notes = [f.detector_id for f in result.score.correct_notes]
            assert notes == _listings(bill), (features, notes)
            assert result.misclassified == (), features


def test_a_boq_corpus_without_planted_errors_produces_no_rule_finding(tmp_path: Path) -> None:
    corpus = CorpusConfig(
        seed=20261120,
        documents_per_variant=8,
        max_errors=0,
        variant="boq",
        boq=BoqSettings(positions=(80, 200), formats=("xlsx", "csv")),
    )
    report = run_benchmark(BenchmarkConfig(corpus=corpus), tmp_path)
    boq = report["boq"]
    assert boq["bills"] == {
        "bills": 8,
        "buildings": 2,
        "keys": 2,
        "components": 2,
        "type_column": 3,
        "type_names": 1,
        "english": 2,
    }
    # Each German bill of this corpus has contingency positions, so each gets their list: a
    # correct risk note, checked against the generated bill, and no false positive.
    noted = [d["name"] for d in report["documents"] if d["correct_risk_notes"]]
    assert noted == [
        entry["name"]
        for entry in json.loads((tmp_path / "manifest.json").read_text())["documents"]
        if entry["language"] == "de"
    ]
    assert all(d["correct_risk_notes"] <= 1 for d in report["documents"])
    assert report["risk_notes"] == {"correct": len(noted), "false": 0}
    assert (boq["planted_errors"], boq["rule_findings"]) == (0, len(noted))
    # The signal checks run too; whatever they flag here is counted apart, never as a rule
    # finding.
    assert report["synthetic"]["findings"] == len(noted) + boq["signals"]
    assert boq["rule_findings_on_unplanted_rows"]["count"] == 0
    assert report["synthetic"]["row_classification_accuracy"] == 1.0
    # The manifest records the columns the harness mapped as a reviewer would; the two bills
    # with keys ran domain.standard_text_keys, which found nothing in them.
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["documents"]:
        features = entry["features"]
        declared = entry.get("column_fields", {})
        assert sorted(declared.values()) == [
            *(["standard_text_key"] if features["keys"] else []),
            *(f"unit_price_component_{k}" for k in range(1, features["components"] + 1)),
        ]


def test_the_harness_maps_the_key_and_component_columns_as_a_reviewer_would() -> None:
    features = Features(language="de", keys=True, components=3)
    bill = generate_bill(random.Random(2), features, 80)
    doc = document(bill, name="components", file_format="csv")
    header = doc.content.decode("utf-8").splitlines()[bill.header_row - 1].split(";")
    assert {header[n - 1]: f for n, f in doc.column_fields.items()} == {
        "STLB-Bau": "standard_text_key",
        **{f"EP-Anteil {k}": f"unit_price_component_{k}" for k in (1, 2, 3)},
    }
    decisions = doc.decisions()
    table = decisions.for_sheet(0) if decisions is not None else None
    assert table is not None and table.column_fields == doc.column_fields
    plain = document(
        generate_bill(random.Random(2), Features(language="de"), 80), name="p", file_format="csv"
    )
    assert plain.column_fields == {} and plain.decisions() is None


def _key_check(wb: Workbench, bill: BoqBill, name: str) -> tuple[dict[str, Any], list[str]]:
    """The run report of ``domain.standard_text_keys`` on ``bill`` and its findings' rules."""
    doc = document(bill, name=name, file_format="xlsx")
    _, dataset = documents.upload(
        wb, filename=doc.name, chunks=[doc.content], profile_id="boq", decisions=doc.decisions()
    )
    assert dataset is not None
    run = runs.start(wb, dataset.dataset_id)
    [report] = [r for r in run["detector_reports"] if r["detector_id"] == KEY_CHECK]
    with wb.uow() as uow:
        issues = uow.issues.iter_all(IssueQuery(run_id=run["run_id"]))
        rules = [issue.rule_id for issue in issues if issue.detector_id == KEY_CHECK]
    return report, rules


def test_the_standard_text_key_check_runs_on_the_bills_with_keys(tmp_path: Path) -> None:
    wb = benchmark_workbench(tmp_path)
    features = Features(language="de", buildings=True, keys=True)
    clean = generate_bill(random.Random(3), features, 80)
    report, rules = _key_check(wb, clean, "keys")
    assert report["status"] == "completed" and rules == []
    assert report["coverage"]["rows_with_standard_text_key"] == len(clean.items())
    assert report["coverage"]["keys_compared"] > 0  # Haus B repeats Haus A's keys
    # A unit price changed in one building differs from its copy's: one finding.
    _, slipped = _planted(ErrorKind.PRICE_DECIMAL_SLIP, keys=True)
    report, rules = _key_check(wb, slipped, "slip")
    assert report["status"] == "completed" and rules == ["same_key_unit_prices"]


@pytest.mark.parametrize("language", ["de", "en"])
def test_todays_checks_find_their_kinds_in_boq_bills(tmp_path: Path, language: Language) -> None:
    wb = benchmark_workbench(tmp_path)
    signals = signal_checks(wb)
    # The BoQ kinds whose expected checks exist: line_total_slip, and those of B2.
    boq_kinds = (
        ErrorKind.LINE_TOTAL_SLIP,
        ErrorKind.PLACEHOLDER_PRICE,
        ErrorKind.COMPONENT_SUM_ERROR,
        ErrorKind.CODE_OUTSIDE_SECTION,
        ErrorKind.DUPLICATE_POSITION,
    )
    for kind in (*STANDARD_KINDS, *boq_kinds):
        _, bill = _planted(kind, language)
        doc = document(bill, name=f"{kind.value}-{language}", file_format="xlsx")
        result = evaluate(wb, doc, k=5, profile_id="boq")
        [outcome] = result.score.outcomes
        assert outcome.detected and outcome.localized, (kind, outcome)
        assert set(outcome.rules) & set(EXPECTED_RULES[kind]), (kind, outcome.rules)
        rules = [f for f in result.score.false_positives if f.detector_id not in signals]
        assert rules == [], kind
        assert len(result.score.correct_notes) <= int(_lists_contingency(bill)), kind
