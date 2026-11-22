"""PDF import: the text layer, the bill reader, the adapter, and the sample dataset's PDFs.

The PDFs are written by :mod:`tests.support.pdf_builder` (Helvetica text at exact positions),
so every layout rule is tested on a known page. The sample dataset's PDFs are checked against
their GAEB twins (the same bill exported as GAEB) when the folder is present."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.clock import FixedClock
from app.core.config import BUILTIN_PROFILE_DIR, IngestionLimits, ValidationLimits, get_settings
from app.core.errors import ExtractionError, UnsupportedFormatError
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.gaeb90 import read_gaeb90
from app.ingestion.gaeb.model import EntryKind, GaebCategory, GaebEntry
from app.ingestion.gaeb.reader import read_gaeb
from app.ingestion.pdf.adapter import PdfAdapter
from app.ingestion.pdf.bill import german_decimal, read_bill
from app.ingestion.pdf.layout import read_pages
from app.ingestion.security import detect_format
from app.models.dataset import RowKind
from app.models.document import DocumentFormat
from app.models.finding_category import FindingCategory
from app.models.issue import EvidenceClass
from app.models.plan import PlannerKind
from app.models.source import SourceKind
from app.normalization.builder import build_dataset
from app.profiles.loader import ProfileCatalog
from app.validation.domain.boq.position_types import BoqPositionTypesDetector
from app.validation.pipeline import ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry
from tests.support.pdf_builder import (
    OZ_X,
    PRICE_RIGHT,
    QTY_RIGHT,
    TEXT_X,
    TOTAL_RIGHT,
    UNIT_X,
    PdfPage,
    bill_header,
    build_pdf,
    item,
    sample_bill,
)

SAMPLE_DATASET = Path(__file__).parents[4] / "Sample BoQ Dataset"
POSITION_TYPES = BoqPositionTypesDetector.spec.detector_id


def _write(tmp_path: Path, content: bytes, name: str = "bill.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _items(nodes: list[GaebCategory | GaebEntry]) -> list[GaebEntry]:
    out: list[GaebEntry] = []
    for node in nodes:
        if isinstance(node, GaebCategory):
            out.extend(_items(node.children))
        elif node.kind is EntryKind.ITEM:
            out.append(node)
    return out


def _bill(tmp_path: Path, content: bytes):
    document, _ = read_bill(read_pages(_write(tmp_path, content), 100))
    return document, {entry.number: entry for entry in _items(document.body)}


def _dataset(path: Path):
    raw = PdfAdapter().extract(path, IngestionLimits())
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


# --------------------------------------------------------------------------- text layer
def test_words_keep_their_page_position_and_umlauts(tmp_path: Path) -> None:
    page = PdfPage().text(100, 200, "Böschung über 2 m").right(300, 220, "1.655,000")
    [read] = read_pages(_write(tmp_path, build_pdf([page])), 10)
    first, second = read.lines
    assert first.text == "Böschung über 2 m" and read.number == 1
    assert first.words[0].x0 == pytest.approx(100, abs=1.5)
    assert second.words[0].text == "1.655,000"
    assert second.words[0].x1 == pytest.approx(300, abs=1.5)
    box = second.box()
    assert box.page_number == 1 and box.y0 < 220 < box.y1 + 1


def test_a_number_drawn_in_pieces_is_one_word(tmp_path: Path) -> None:
    # drawn as two texts, the second starting where the first one's advance ends (as in the
    # sample bid): the glyph boxes leave a gap of about 2.6 points, like a word space
    page = PdfPage().text(100, 200, "1").text(105.6, 200, ",000").text(150, 200, "psch")
    [read] = read_pages(_write(tmp_path, build_pdf([page])), 10)
    assert [w.text for w in read.lines[0].words] == ["1,000", "psch"]


def test_german_numbers_become_decimal_text() -> None:
    assert german_decimal("1.655,000") == "1655.000"
    assert german_decimal("-12,5") == "-12.5"
    assert german_decimal("72.000,00") == "72000.00"


# --------------------------------------------------------------------------- the bill
def test_a_printed_bill_is_read_item_by_item(tmp_path: Path) -> None:
    document, items = _bill(tmp_path, sample_bill())
    assert list(items) == ["01.10", "01.20", "01.30", "01.40"]
    first = items["01.10"]
    assert (first.qty.text, first.unit.text) == ("120.000", "m2")
    assert (first.unit_price.text, first.total.text) == ("4.50", "540.00")
    assert first.short_text == "Oberboden abtragen"
    # "Dicke 20 cm" is text, not a quantity: it is not in the quantity column
    assert first.long_text == "Oberboden abtragen und seitlich lagern. Dicke 20 cm"
    assert items["01.20"].long_text.endswith("Böschungswinkel nach Wahl.")
    assert (
        first.page == 2 and first.bbox is not None and first.bbox.x0 == pytest.approx(OZ_X, abs=1)
    )
    [category] = document.body
    assert (category.number, category.label, category.total.text) == (
        "01",
        "Erdarbeiten",
        "1223.30",
    )
    assert document.total.text == "1223.30" and document.total_gross.text == "1455.73"
    assert (document.project, document.boq_name, document.currency) == (
        "Testprojekt",
        "Erdarbeiten Testbau",
        "EUR",
    )


def test_an_item_priced_only_by_unit_is_left_out_of_the_totals(tmp_path: Path) -> None:
    _, items = _bill(tmp_path, sample_bill())
    contingency = items["01.40"]
    assert contingency.total is None and contingency.total_undecided
    assert contingency.extra_types == ("Nur Einheitspreis", "Bedarfsposition (laut Text)")


def test_the_bill_becomes_a_declared_table_with_page_sources(tmp_path: Path) -> None:
    raw, dataset, _ = _dataset(_write(tmp_path, sample_bill()))
    assert raw.format is DocumentFormat.PDF
    assert raw.details["bill_pages"] == "2-3" and raw.details["skipped_pages"] == "1"
    table = dataset.tables[0]
    kinds = Counter(row.kind for row in table.rows)
    assert kinds[RowKind.ITEM] == 4 and kinds[RowKind.TEXT] == 1
    assert kinds[RowKind.SUBTOTAL] == 2 and kinds[RowKind.GROSS_TOTAL] == 1
    items = [row for row in table.rows if row.kind is RowKind.ITEM]
    assert [row.counts_toward_totals for row in items] == [True, True, True, None]
    price = items[1].cells[table.column_for_field("unit_price").column_id]
    assert price.normalized_value.value == Decimal("18.20")
    assert price.source.kind is SourceKind.PDF_TEXT
    assert price.source.page_number == 2 and price.source.bbox is not None
    assert price.source.bbox.x1 == pytest.approx(PRICE_RIGHT, abs=1.5)
    warning = next(w for w in raw.warnings if w.code == "pdf_layout_read")
    assert not warning.needs_review and "2 of 3 pages" in warning.message


def test_the_bill_reconciles_and_a_wrong_total_is_found(tmp_path: Path) -> None:
    _, dataset, profile = _dataset(_write(tmp_path, sample_bill()))
    issues = _run(dataset, profile).issues
    # The bill adds up. Since step B2 the baseline plan lists its contingency position, 01.40
    # (Bedarfsposition laut Text), to price at a rate that covers cost: a Risk note, no error.
    assert [issue.title for issue in issues] == [
        "1 contingency position to price at rates that cover cost"
    ]
    [note] = issues
    assert (note.detector_id, note.rule_id) == (POSITION_TYPES, "contingency_and_hourly")
    assert note.finding_category is FindingCategory.RISK
    wrong = sample_bill().replace(b"(646,10)", b"(664,10)")
    _, dataset, profile = _dataset(_write(tmp_path, wrong, "wrong.pdf"))
    issues = _run(dataset, profile).issues
    detectors = {issue.detector_id for issue in issues}
    assert "deterministic.line_total" in detectors
    # PDF values are unverified: a failed rule asks to be checked against the page, and the
    # finding keeps its category (a wrong total is an error, to verify in the source).
    line_total = next(i for i in issues if i.detector_id == "deterministic.line_total")
    assert any(item.label == "Evidence downgraded" for item in line_total.evidence)
    assert line_total.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
    assert line_total.finding_category is FindingCategory.ERROR


def test_a_quantity_on_the_oz_line_with_the_text_below(tmp_path: Path) -> None:
    """The layout of a priced bid: OZ, quantity, unit, unit price and total on one line."""
    page = bill_header(PdfPage(), 1)
    for k, (oz, qty, unit, price, total, text) in enumerate(
        [
            ("2.1.150", "50,000", "m³", "32,00", "1.600,00", "Bodenaustausch mit Vorabsiebung"),
            ("2.1.160", "255,000", "m³", "3,20", "816,00", "Sandbettung Rohrleitung"),
            ("2.1.170", "940,000", "m³", "3,20", "3.008,00", "Sandüberdeckung"),
        ]
    ):
        top = 160 + 40 * k
        page.text(OZ_X, top, oz).right(QTY_RIGHT, top, qty).text(UNIT_X, top, unit)
        page.right(PRICE_RIGHT, top, price).right(TOTAL_RIGHT, top, total)
        page.text(TEXT_X, top + 12, text)
    _, items = _bill(tmp_path, build_pdf([page]))
    assert [(i.number, i.qty.text, i.unit.text, i.total.text) for i in items.values()] == [
        ("2.1.150", "50.000", "m³", "1600.00"),
        ("2.1.160", "255.000", "m³", "816.00"),
        ("2.1.170", "940.000", "m³", "3008.00"),
    ]
    assert items["2.1.160"].short_text == "Sandbettung Rohrleitung"


def test_a_quantity_after_text_and_without_unit_is_kept_and_reported(tmp_path: Path) -> None:
    """Some layouts print the last text line and the quantity on one line; a missing unit is
    reported, not guessed."""
    page = bill_header(PdfPage(), 1)
    top = item(page, 160, "2.6.1", "Türstation", ["Aufputz"], "2,000", "St", None, None)
    top = item(page, top, "2.6.2", "Bus-Netzgerät", ["Hutschiene"], "1,000", "St", None, None)
    page.text(OZ_X, top, "2.6.3", size=8).text(TEXT_X, top, "Kommunikations-Stele", bold=True)
    page.text(TEXT_X, top + 20, "Fabrikat Siedle oder gleichwertig").right(
        QTY_RIGHT, top + 20, "1,000"
    )
    path = _write(tmp_path, build_pdf([page]))
    _, items = _bill(tmp_path, path.read_bytes())
    stele = items["2.6.3"]
    assert stele.qty.text == "1.000" and stele.unit is None
    assert stele.long_text == "Fabrikat Siedle oder gleichwertig"
    _, dataset, profile = _dataset(path)
    titles = [issue.title for issue in _run(dataset, profile).issues]
    assert any("Missing Unit" in title for title in titles)


def test_a_bare_number_is_no_quantity_where_quantities_have_decimals(tmp_path: Path) -> None:
    page = bill_header(PdfPage(), 1)
    page.text(OZ_X, 160, "6.1.", size=8).text(TEXT_X, 160, "Ingenieurleistungen", bold=True)
    page.text(TEXT_X, 172, "Bestandsvermessung, Länge ca.").right(QTY_RIGHT, 172, "400")
    page.text(UNIT_X, 172, "m")
    top = item(
        page, 200, "6.1.10.", "Bestandsplan", ["Pläne erstellen"], "2.380,000", "m", None, None
    )
    item(page, top, "6.1.20.", "Bauwerksplan", ["Maßstab 1:25"], "1,000", "St", None, None)
    document, items = _bill(tmp_path, build_pdf([page]))
    assert list(items) == ["6.1.10", "6.1.20"]
    [section] = document.body
    assert section.number == "6.1" and section.label == "Ingenieurleistungen"


def test_an_item_without_a_quantity_line_is_reported(tmp_path: Path) -> None:
    page = bill_header(PdfPage(), 1)
    top = item(page, 160, "1.10", "Aushub", ["Boden lösen"], "10,000", "m3", None, None)
    page.text(OZ_X, top, "1.20", size=8).text(TEXT_X, top, "Verbau", bold=True)
    page.text(TEXT_X, top + 12, "Menge nach Aufmaß")
    item(page, top + 40, "1.30", "Verfüllen", ["lagenweise"], "8,000", "m3", None, None)
    raw = PdfAdapter().extract(_write(tmp_path, build_pdf([page])), IngestionLimits())
    warning = next(w for w in raw.warnings if w.code == "pdf_items_without_quantity")
    assert warning.needs_review and "1.20" in warning.message


# --------------------------------------------------------------------------- refusals
def test_a_pdf_without_text_is_refused_as_a_possible_scan(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError) as excinfo:
        PdfAdapter().extract(_write(tmp_path, build_pdf([PdfPage()])), IngestionLimits())
    assert excinfo.value.details["reason"] == "pdf_no_text"
    assert "it may be a scan" in excinfo.value.message


def test_a_pdf_without_a_bill_table_is_refused(tmp_path: Path) -> None:
    letter = PdfPage().text(60, 100, "Sehr geehrte Damen und Herren,").text(60, 120, "anbei.")
    with pytest.raises(ExtractionError) as excinfo:
        PdfAdapter().extract(_write(tmp_path, build_pdf([letter])), IngestionLimits())
    assert excinfo.value.details["reason"] == "pdf_no_bill_table"


def test_a_damaged_pdf_and_too_many_pages_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError) as excinfo:
        PdfAdapter().extract(_write(tmp_path, b"%PDF-1.4\nnot really\n"), IngestionLimits())
    assert excinfo.value.details["reason"] == "pdf_unreadable"
    limits = IngestionLimits(max_pdf_pages=2)
    with pytest.raises(ExtractionError) as excinfo:
        PdfAdapter().extract(_write(tmp_path, sample_bill(), "long.pdf"), limits)
    assert excinfo.value.details["reason"] == "pdf_too_many_pages"


def test_format_detection_needs_pdf_content(tmp_path: Path) -> None:
    path = _write(tmp_path, sample_bill())
    assert detect_format(path, "LV 03.PDF") is DocumentFormat.PDF
    text = _write(tmp_path, b"OZ;Kurztext\n1;Aushub\n", "fake.pdf")
    with pytest.raises(UnsupportedFormatError):
        detect_format(text, "fake.pdf")
    with pytest.raises(UnsupportedFormatError) as excinfo:
        detect_format(path, "bill.csv")
    assert ".pdf" in excinfo.value.message


# --------------------------------------------------------------------------- sample dataset
# PDFs of the committed sample dataset whose bill also exists as GAEB, and how many of the
# GAEB items the PDF contains (the bid "Abgabe LV" lacks one item of the award, and the
# anonymisation renamed one item number of the GAEB file).
TWINS = {
    "HEM2301-2_Gesamt-LV.pdf": ("8209.003_Leistungsverzeichnis_leer.X83", 159),
    "LV-Ausdruck-[PROJEKT_004].pdf": ("GAEB-[PROJEKT_004].X83", 50),
    "Leistungsverzeichnis.pdf": ("Angebot AN24-0305.D84", 274),
    "Angebot AN24-0305.pdf": ("Angebot AN24-0305.D84", 274),
    "Leistungsverzeichnis_leer.pdf": ("StBALV23040.D86", 247),
    "Abgabe LV.pdf": ("StBALV23040.D86", 247),
}
needs_samples = pytest.mark.skipif(not SAMPLE_DATASET.is_dir(), reason="sample dataset absent")


def _key(number: str) -> str:
    return ".".join(p.lstrip("0") or "0" for p in re.split(r"[.\s]+", number.strip(". ")) if p)


def _twin(name: str) -> dict[str, GaebEntry]:
    path = SAMPLE_DATASET / name
    phase = path.suffix[-2:]
    document = (
        read_gaeb90(path, phase) if path.suffix.lower().startswith(".d") else read_gaeb(path, phase)
    )
    return {_key(entry.number): entry for entry in _items(document.body)}


def _amount(value) -> Decimal | None:
    return Decimal(value.text) if value is not None else None


@needs_samples
@pytest.mark.parametrize("name", sorted(TWINS))
def test_sample_pdfs_match_their_gaeb_twin(name: str) -> None:
    twin_name, expected = TWINS[name]
    twin = _twin(twin_name)
    document, _ = read_bill(read_pages(SAMPLE_DATASET / name, 2000))
    read = {_key(entry.number): entry for entry in _items(document.body)}
    common = set(read) & set(twin)
    assert len(common) == expected
    assert all(_amount(read[k].qty) == _amount(twin[k].qty) for k in common)
    priced = [k for k in common if read[k].unit_price is not None]
    if name == "Angebot AN24-0305.pdf":  # the same bid: every price agrees
        assert len(priced) == 274
        assert all(_amount(read[k].unit_price) == _amount(twin[k].unit_price) for k in priced)
        assert all(_amount(read[k].total) == _amount(twin[k].total) for k in priced)
        assert document.total.text == "988913.89" and document.total_gross.text == "1176807.53"


@needs_samples
def test_every_sample_pdf_is_read() -> None:
    for path in sorted(SAMPLE_DATASET.glob("*.pdf")):
        raw = PdfAdapter().extract(path, IngestionLimits())
        kinds = Counter(raw.sheets[0].declared.row_kinds.values())
        assert kinds[RowKind.ITEM] > 0, path.name
