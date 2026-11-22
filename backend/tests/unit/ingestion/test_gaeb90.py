"""GAEB 90 import (.d81/.d83/.d84/.d86): record layout, checks, the flattened table, a full run,
and every GAEB file of the committed sample dataset.

The self-made files in ``tests/fixtures/gaeb`` (``small.d83``, ``small.d84``, ``small.d86``) are
written in code page 850 with 80-column records."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.clock import FixedClock
from app.core.config import BUILTIN_PROFILE_DIR, IngestionLimits, ValidationLimits, get_settings
from app.core.errors import ExtractionError, UnsupportedFormatError
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.adapter import Gaeb90Adapter, GaebAdapter
from app.ingestion.gaeb.flatten import COL, item_type
from app.ingestion.gaeb.gaeb90 import decode, read_gaeb90
from app.ingestion.gaeb.model import GaebCategory, GaebEntry
from app.ingestion.security import detect_format
from app.models.dataset import RowKind
from app.models.document import DocumentFormat
from app.models.finding_category import FindingCategory
from app.models.plan import PlannerKind
from app.models.source import SourceKind
from app.normalization.builder import build_dataset
from app.profiles.loader import ProfileCatalog
from app.validation.domain.boq.position_types import BoqPositionTypesDetector
from app.validation.pipeline import ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry

FIXTURES = Path(__file__).parents[2] / "fixtures" / "gaeb"
POSITION_TYPES = BoqPositionTypesDetector.spec.detector_id
D86 = (FIXTURES / "small.d86").read_bytes().decode("cp850")
SAMPLE_DATASET = Path(__file__).parents[4] / "Sample BoQ Dataset"


def _write(tmp_path: Path, text: str, name: str = "bill.d86", encoding: str = "cp850") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def _dataset(path: Path, phase: str, adapter: type[GaebAdapter] = Gaeb90Adapter):
    raw = adapter(phase).extract(path, IngestionLimits())
    profile = ProfileCatalog.from_directories([BUILTIN_PROFILE_DIR]).get("boq")
    dataset = build_dataset(
        raw, profile=profile, document_id="doc", ids=SequentialIdFactory(), clock=FixedClock()
    )
    return raw, dataset, profile


def _run(dataset, profile):
    registry = DetectorRegistry.from_packages(get_settings().detector_packages)
    pipeline = ValidationPipeline(
        registry, ids=SequentialIdFactory(), clock=FixedClock(), limits=ValidationLimits()
    )
    return pipeline.execute(
        dataset=dataset,
        document_id="doc",
        profile=profile,
        plan=BaselinePlanner(registry).plan(dataset, profile),
        plan_source=PlannerKind.BASELINE,
        run_id="run",
    )


def _items(nodes: list) -> list[GaebEntry]:
    out: list[GaebEntry] = []
    for node in nodes:
        if isinstance(node, GaebCategory):
            out.extend(_items(node.children))
        elif node.kind.value == "item":
            out.append(node)
    return out


def _replace_record(text: str, prefix: str, new: str) -> str:
    """Replace the data columns (1-74) of the first record that starts with ``prefix``."""
    lines = text.split("\r\n")
    index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    lines[index] = new.ljust(74)[:74] + lines[index][74:]
    return "\r\n".join(lines)


# --------------------------------------------------------------------------- the record layout
def test_an_award_is_read_record_by_record() -> None:
    document = read_gaeb90(FIXTURES / "small.d86", "86")
    assert (document.version, document.phase, document.encoding) == ("90", "86", "cp850")
    assert document.boq_name == "Testleistungsverzeichnis"
    assert (document.project, document.currency) == ("Testprojekt", "EUR")
    assert document.date == "2026-11-20"  # record 01, columns 43-50 (TT.MM.JJ)
    [title] = document.body
    assert (title.number, title.label, title.total.text) == ("01", "Erdarbeiten", "704.70")
    [area] = title.children
    assert (area.number, area.label, area.level) == ("01.01", "Aushub und Planum", 2)
    note = area.children[0]
    assert note.element == "Remark" and "gegen Einsturz" in note.long_text
    items = {item.number: item for item in _items(document.body)}
    assert list(items) == [f"01.01.{n}" for n in ("10", "20", "30", "40", "50", "60")]
    first = items["01.01.10"]
    assert (first.qty.text, first.unit.text) == ("12.500", "m3")
    assert (first.unit_price.text, first.total.text) == ("42.50", "531.25")
    assert first.short_text == "Aushub"
    # text-supplement markers in columns 3-5 are not text; umlauts come through code page 850
    assert first.long_text == "Boden ausheben und seitlich lagern, Böschung nach Wahl des Bieters."
    assert items["01.01.20"].unit_price.text == "12.345"  # tenth of a cent in column 23
    assert document.total.text == "704.70" and document.total_gross.text == "838.59"
    assert document.vat_percent.text == "19.00"


def test_item_types_map_to_the_gaeb_flags() -> None:
    items = {i.number: i for i in _items(read_gaeb90(FIXTURES / "small.d86", "86").body)}
    assert item_type(items["01.01.10"]) == "Normalposition"
    assert item_type(items["01.01.30"]) == "Grundposition"
    assert item_type(items["01.01.40"]) == "Wahlposition"
    assert item_type(items["01.01.50"]) == "Bedarfsposition ohne GB"
    assert items["01.01.50"].total is None
    assert item_type(items["01.01.60"]) == "Wiederholungsposition"
    assert items["01.01.60"].short_text == "Wie Position 01.01.10, jedoch flach"


def test_a_prices_only_bid_builds_its_categories_from_the_item_numbers() -> None:
    document = read_gaeb90(FIXTURES / "small.d84", "84")
    [title] = document.body
    assert [c.number for c in title.children] == ["01.01", "01.02"]
    assert [c.total.text for c in title.children] == ["654.70", "100.00"]
    assert [i.number for i in _items(document.body)] == ["01.01.10", "01.01.20", "01.02.10"]


def test_a_call_for_bids_has_no_prices_and_no_totals() -> None:
    document = read_gaeb90(FIXTURES / "small.d83", "83")
    assert all(i.unit_price is None and i.total is None for i in _items(document.body))
    assert document.total is None and document.total_gross is None


# --------------------------------------------------------------------------- full runs
@pytest.mark.parametrize(
    ("name", "phase"), [("small.d83", "83"), ("small.d84", "84"), ("small.d86", "86")]
)
def test_the_self_made_files_validate_without_findings_but_their_contingency_list(
    name: str, phase: str
) -> None:
    """Nothing is wrong in the files. Since step B2 the baseline plan lists a bill's contingency
    positions to price at rates that cover cost (a Risk note, not an error): the call for bids
    and the award hold one, 01.01.50 (Bedarfsposition ohne GB)."""
    raw, dataset, profile = _dataset(FIXTURES / name, phase)
    assert raw.format is DocumentFormat(f"gaeb_d{phase}")
    assert raw.details["gaeb_version"] == "90" and raw.details["encoding"] in ("ascii", "cp850")
    issues = _run(dataset, profile).issues
    expected = [] if phase == "84" else ["1 contingency position to price at rates that cover cost"]
    assert [i.title for i in issues] == expected
    table = dataset.tables[0]
    code = table.column_for_field("item_code").column_id
    for issue in issues:
        assert (issue.detector_id, issue.rule_id) == (POSITION_TYPES, "contingency_and_hourly")
        assert issue.finding_category is FindingCategory.RISK
        listed = {cell.row_id for cell in issue.affected_cells}
        rows = [row for row in table.rows if row.row_id in listed]
        assert [row.cells[code].normalized_value.value for row in rows] == ["01.01.50"]


def test_the_award_becomes_a_declared_table_with_line_sources() -> None:
    _, dataset, profile = _dataset(FIXTURES / "small.d86", "86")
    table = dataset.tables[0]
    kinds = Counter(row.kind for row in table.rows)
    assert kinds[RowKind.ITEM] == 6 and kinds[RowKind.SECTION] == 3 and kinds[RowKind.TEXT] == 1
    counts = {
        row.cells[table.column_for_field("item_code").column_id].raw_value: row.counts_toward_totals
        for row in table.rows
        if row.kind is RowKind.ITEM
    }
    assert counts["01.01.40"] is False and counts["01.01.50"] is False  # alternative, contingency
    assert counts["01.01.30"] is True
    [first] = [r for r in table.rows if r.kind is RowKind.ITEM][:1]
    price = first.cells[table.column_for_field("unit_price").column_id]
    assert price.normalized_value.value == Decimal("42.50")
    assert price.source.kind is SourceKind.GAEB_90
    assert price.source.line_number == 12
    assert price.source.describe().startswith("GAEB 90 row")
    reports = {r.detector_id: r for r in _run(dataset, profile).reports}
    assert reports["deterministic.line_total"].coverage["rows_consistent"] >= 4


def test_a_wrong_line_total_is_found(tmp_path: Path) -> None:
    text = _replace_record(D86, "230101  10", "230101  10  0000004250  000000053130")
    _, dataset, profile = _dataset(_write(tmp_path, text), "86")
    detectors = {i.detector_id for i in _run(dataset, profile).issues}
    assert "deterministic.line_total" in detectors


# --------------------------------------------------------------------------- character sets
def test_windows_1252_files_are_recognised(tmp_path: Path) -> None:
    raw = Gaeb90Adapter("86").extract(_write(tmp_path, D86, encoding="cp1252"), IngestionLimits())
    assert raw.details["encoding"] == "cp1252"
    cells = raw.sheets[0].cells
    assert any("Böschung" in c.text for (_, col), c in cells.items() if col == COL["Langtext"])


def test_decode_prefers_ascii_then_utf8() -> None:
    assert decode(b"00 abc")[1] == "ascii"
    assert decode("Böschung".encode())[1] == "utf-8"
    assert decode("Böschung".encode("cp850"))[1] == "cp850"


# --------------------------------------------------------------------------- checks
WRONG = [
    ("wrong phase", lambda t: t, "84", UnsupportedFormatError, "gaeb_phase_mismatch"),
    (
        "unsupported phase",
        lambda t: _replace_record(t, "00", "00        82L".ljust(62) + "1122PPPPI90"),
        "86",
        UnsupportedFormatError,
        "gaeb_phase_unsupported",
    ),
    ("no closing 99", lambda t: t[: t.rindex("99")], "86", ExtractionError, "gaeb90_no_end"),
    (
        "not GAEB 90",
        lambda t: "Pos;Text;Menge\r\n" + t,
        "86",
        UnsupportedFormatError,
        "not_gaeb90",
    ),
    (
        "no record type",
        lambda t: t.replace("\r\n25Aushub", "\r\nxxAushub", 1),
        "86",
        ExtractionError,
        "gaeb90_bad_record",
    ),
    (
        "too long",
        lambda t: t.replace("\r\n25Aushub", "\r\n25" + "A" * 90, 1),
        "86",
        ExtractionError,
        "gaeb90_bad_record",
    ),
    (
        "bad mask",
        lambda t: _replace_record(t, "00", "00        86L".ljust(62) + "11P22PPPI90"),
        "86",
        ExtractionError,
        "gaeb90_bad_mask",
    ),
    (
        "bad number",
        lambda t: _replace_record(t, "210101  10", "210101  10 NNN         000000125x0m3"),
        "86",
        ExtractionError,
        "gaeb90_bad_number",
    ),
]


@pytest.mark.parametrize(
    ("change", "phase", "error", "reason"), [w[1:] for w in WRONG], ids=[w[0] for w in WRONG]
)
def test_each_wrong_file_is_rejected_with_its_reason(
    tmp_path: Path, change, phase: str, error: type[Exception], reason: str
) -> None:
    with pytest.raises(error) as excinfo:
        read_gaeb90(_write(tmp_path, change(D86)), phase)
    assert excinfo.value.details["reason"] == reason  # type: ignore[attr-defined]


def test_an_item_number_with_letters_stays_in_its_category_and_is_flagged(tmp_path: Path) -> None:
    text = D86.replace("210101  60", "21TEL00060", 1).replace("230101  60", "23TEL00060", 1)
    raw, dataset, profile = _dataset(_write(tmp_path, text), "86")
    warning = next(w for w in raw.warnings if w.code == "gaeb90_invalid_item_number")
    assert warning.needs_review and "'TEL00060'" in warning.message
    document = read_gaeb90(_write(tmp_path, text), "86")
    [title] = document.body
    assert [c.number for c in title.children] == ["01.01"]  # no category built from letters
    detectors = {i.detector_id for i in _run(dataset, profile).issues}
    assert "deterministic.subtotal" not in detectors  # the item still counts in 01.01


def test_format_detection_by_extension() -> None:
    for phase in ("83", "84", "86"):
        path = FIXTURES / f"small.d{phase}"
        assert detect_format(path, f"LV.D{phase}") is DocumentFormat(f"gaeb_d{phase}")


# --------------------------------------------------------------------------- the sample dataset
# Every GAEB file of the committed sample dataset: (format, phase, items, findings that are
# facts of the file). The dataset was anonymised; the D86 "StBALV23040" has an item number
# rewritten to "TEL00009" by that, which the import flags for review.
SAMPLE_FILES = {
    "501-24-01_GAEB-XML_sas.x83": ("x", "83", 296),  # DA XML 3.1
    "8209.003_Leistungsverzeichnis_leer.X83": ("x", "83", 159),  # DA XML 3.2
    "GAEB-[PROJEKT_004].X83": ("x", "83", 50),  # DA XML 3.2
    "[NUMMER_001]_leer.X83": ("x", "83", 248),  # DA XML 3.2
    "8209.003_Leistungsverzeichnis_leer.D83": ("d", "83", 159),
    "Angebot AN24-0305.D84": ("d", "84", 274),  # Windows-1252
    "StBALV23040.D84": ("d", "84", 249),  # prices only, after contract terms (T records)
    "StBALV23040.D86": ("d", "86", 249),
    "[ORT_024] LV24069.D86": ("d", "86", 197),
}


@pytest.mark.skipif(not SAMPLE_DATASET.is_dir(), reason="sample dataset not checked out")
@pytest.mark.parametrize("name", sorted(SAMPLE_FILES))
def test_every_gaeb_file_of_the_sample_dataset_is_read(name: str) -> None:
    family, phase, items = SAMPLE_FILES[name]
    path = SAMPLE_DATASET / name
    assert detect_format(path, name) is DocumentFormat(f"gaeb_{family}{phase}")
    adapter = Gaeb90Adapter if family == "d" else GaebAdapter
    _, dataset, profile = _dataset(path, phase, adapter)
    rows = dataset.tables[0].rows
    assert sum(row.kind is RowKind.ITEM for row in rows) == items
    detectors = {i.detector_id for i in _run(dataset, profile).issues}
    # Item totals and category subtotals reconcile in every priced file.
    assert not {"deterministic.line_total", "deterministic.subtotal"} & detectors


@pytest.mark.skipif(not SAMPLE_DATASET.is_dir(), reason="sample dataset not checked out")
def test_the_gaeb_90_and_xml_versions_of_one_bill_agree() -> None:
    def table(path: Path, adapter: type[GaebAdapter]) -> list[tuple[str, str, str]]:
        raw = adapter("83").extract(path, IngestionLimits())
        cells = raw.sheets[0].cells
        rows = [r for r, kind in raw.sheets[0].declared.row_kinds.items() if kind is RowKind.ITEM]
        get = lambda r, h: cells[(r, COL[h])].text if (r, COL[h]) in cells else ""  # noqa: E731
        return [(get(r, "OZ"), get(r, "Menge"), get(r, "Einheit")) for r in rows]

    name = "8209.003_Leistungsverzeichnis_leer"
    assert table(SAMPLE_DATASET / f"{name}.D83", Gaeb90Adapter) == table(
        SAMPLE_DATASET / f"{name}.X83", GaebAdapter
    )
