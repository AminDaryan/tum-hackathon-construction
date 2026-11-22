"""GAEB DA XML import: schema pinning, the reader's checks, the flattened table and a full run.

The self-made files in ``tests/fixtures/gaeb`` pass the official 3.3 schema. The official BVBS
test files are used only when ``TWB_GAEB_SAMPLES`` names a folder that holds them."""

from __future__ import annotations

import dataclasses
import os
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from app.core.clock import FixedClock
from app.core.config import BUILTIN_PROFILE_DIR, IngestionLimits, ValidationLimits, get_settings
from app.core.errors import ExtractionError, UnsupportedFormatError
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.adapter import GaebAdapter
from app.ingestion.gaeb.reader import read_gaeb
from app.ingestion.gaeb.schemas import SCHEMAS, compiled
from app.ingestion.security import detect_format
from app.models.dataset import RowKind
from app.models.document import DocumentFormat
from app.models.plan import PlannerKind
from app.models.source import SourceKind
from app.normalization.builder import build_dataset
from app.profiles.loader import ProfileCatalog
from app.validation.pipeline import ValidationPipeline
from app.validation.planner import BaselinePlanner
from app.validation.registry.registry import DetectorRegistry

FIXTURES = Path(__file__).parents[2] / "fixtures" / "gaeb"
X83 = (FIXTURES / "small.x83").read_text(encoding="utf-8")
X84 = (FIXTURES / "small.x84").read_text(encoding="utf-8")


def _schema(phase: str):
    return next(s for s in SCHEMAS if s.phase == phase)


def _write(tmp_path: Path, text: str, name: str = "bill.x83") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _dataset(path: Path, phase: str):
    raw = GaebAdapter(phase).extract(path, IngestionLimits())
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


@pytest.mark.parametrize(("name", "phase"), [("small.x83", "83"), ("small.x84", "84")])
def test_the_self_made_files_pass_the_official_schema(name: str, phase: str) -> None:
    document = etree.parse(str(FIXTURES / name))
    assert compiled(_schema(phase)).validate(document)


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda s: s.label)
def test_every_bundled_schema_compiles_offline(schema) -> None:
    assert compiled(schema) is not None


def test_a_changed_schema_file_is_refused() -> None:
    schema = _schema("83")
    changed = dataclasses.replace(schema, files=((schema.xsd, "0" * 64), *schema.files[1:]))
    with pytest.raises(ExtractionError) as excinfo:
        compiled(changed)
    assert excinfo.value.details["reason"] == "schema_hash_mismatch"


NS83 = "http://www.gaeb.de/GAEB_DA_XML/DA83/3.3"
UNSUPPORTED, BROKEN = UnsupportedFormatError, ExtractionError
WRONG = [
    (X83[:-40], "83", BROKEN, "xml_malformed"),
    (X83.replace("<GAEB ", "<!DOCTYPE GAEB []>\n<GAEB ", 1), "83", UNSUPPORTED, "xml_doctype"),
    (X83.replace(NS83, "http://example.com/bill"), "83", UNSUPPORTED, "not_gaeb"),
    (X83.replace(NS83, NS83[:-3] + "3.4"), "83", UNSUPPORTED, "gaeb_version_unsupported"),
    (
        X83.replace(">3.3</Version>", ">3.0</Version>"),
        "83",
        UNSUPPORTED,
        "gaeb_version_unsupported",
    ),
    (X83, "84", UNSUPPORTED, "gaeb_phase_mismatch"),
    (X83.replace(">3.3</Version>", ">3.2</Version>"), "83", UNSUPPORTED, "gaeb_version_mismatch"),
    (X83.replace("<DP>83</DP>", "<DP>84</DP>"), "83", UNSUPPORTED, "gaeb_dp_mismatch"),
    (X83.replace(">12.500</Qty>", ">zwölf</Qty>"), "83", BROKEN, "gaeb_schema_invalid"),
]


@pytest.mark.parametrize(("text", "phase", "error", "reason"), WRONG)
def test_each_wrong_file_is_rejected_with_its_reason(
    tmp_path: Path, text: str, phase: str, error: type[Exception], reason: str
) -> None:
    with pytest.raises(error) as excinfo:
        read_gaeb(_write(tmp_path, text), phase)
    assert excinfo.value.details["reason"] == reason  # type: ignore[attr-defined]


def test_a_schema_error_names_its_line(tmp_path: Path) -> None:
    bad = X83.replace("<Qty>12.500</Qty>", "<Qty>zwölf</Qty>")
    with pytest.raises(ExtractionError) as excinfo:
        read_gaeb(_write(tmp_path, bad), "83")
    line = bad[: bad.index("zwölf")].count("\n") + 1
    assert f"line {line}" in excinfo.value.message


def test_a_call_for_bids_becomes_a_declared_table(tmp_path: Path) -> None:
    raw, dataset, _ = _dataset(_write(tmp_path, X83), "83")
    assert raw.details["gaeb_phase"] == "83" and raw.details["gaeb_version"] == "3.3"
    assert raw.details["document_date"] == "2026-11-20"  # GAEBInfo/Date (no BoQInfo/Date)
    table = dataset.tables[0]
    kinds = Counter(row.kind for row in table.rows)
    assert kinds[RowKind.ITEM] == 1 and kinds[RowKind.SECTION] == 2  # the bill and category 01
    [item] = [row for row in table.rows if row.kind is RowKind.ITEM]
    assert item.classification.rule == "declared"
    quantity = item.cells[table.column_for_field("quantity").column_id]  # type: ignore[union-attr]
    assert quantity.normalized_value.value == Decimal("12.500")  # type: ignore[union-attr]
    assert quantity.source.kind is SourceKind.GAEB_XML
    assert quantity.source.line_number == X83[: X83.index("<Qty>")].count("\n") + 1
    codes = {w.code for w in dataset.extraction.warnings}
    assert "structure_declared" in codes


def test_a_bid_with_a_discount_reconciles(tmp_path: Path) -> None:
    _, dataset, profile = _dataset(_write(tmp_path, X84, "bid.x84"), "84")
    table = dataset.tables[0]
    [item] = [row for row in table.rows if row.kind is RowKind.ITEM]
    assert item.counts_toward_totals is None  # an X84 does not carry the item flags
    outcome = _run(dataset, profile)
    assert [i.title for i in outcome.issues] == []
    reports = {r.detector_id: r for r in outcome.reports}
    assert reports["deterministic.line_total"].coverage["rows_consistent"] == 1


def test_format_detection_by_extension_and_content(tmp_path: Path) -> None:
    path = _write(tmp_path, X83)
    assert detect_format(path, "LV.X83") is DocumentFormat.GAEB_X83
    zipped = tmp_path / "renamed.x83"
    zipped.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    with pytest.raises(UnsupportedFormatError):
        detect_format(zipped, "renamed.x83")
    assert detect_format(path, "LV.x86") is DocumentFormat.GAEB_X86
    assert detect_format(path, "LV.D83") is DocumentFormat.GAEB_D83  # text; the adapter decides
    with pytest.raises(UnsupportedFormatError):
        detect_format(path, "LV.p83")  # GAEB 2000, not supported


def _as_version(text: str, version: str) -> str:
    """A self-made 3.3 file restated as ``version``: namespace, version and schema release."""
    phase = re.search(r"/DA(\d\d)/3\.3", text).group(1)  # type: ignore[union-attr]
    schema = next(s for s in SCHEMAS if s.version == version and s.phase == phase)
    text = text.replace(f"http://www.gaeb.de/GAEB_DA_XML/DA{phase}/3.3", schema.namespace)
    text = text.replace("<Version>3.3</Version>", f"<Version>{version}</Version>")
    return text.replace("<VersDate>2021-05</VersDate>", f"<VersDate>{schema.release}</VersDate>")


@pytest.mark.parametrize("version", ["3.1", "3.2"])
def test_older_versions_are_read_against_their_own_schema(tmp_path: Path, version: str) -> None:
    raw, dataset, _ = _dataset(_write(tmp_path, _as_version(X83, version)), "83")
    assert raw.details["gaeb_version"] == version
    assert raw.details["gaeb_schema"] == next(
        s.xsd for s in SCHEMAS if s.version == version and s.phase == "83"
    )
    assert sum(row.kind is RowKind.ITEM for row in dataset.tables[0].rows) == 1
    _, bid, profile = _dataset(_write(tmp_path, _as_version(X84, version), "bid.x84"), "84")
    assert [i.title for i in _run(bid, profile).issues] == []


def test_the_31_phase_comes_from_award_dp(tmp_path: Path) -> None:
    path = _write(tmp_path, _as_version(X83, "3.1"))
    with pytest.raises(UnsupportedFormatError) as excinfo:
        read_gaeb(path, "84")
    assert excinfo.value.details["reason"] == "gaeb_phase_mismatch"
    assert "Award/DP" in excinfo.value.message


def test_an_award_x86_is_read_and_reconciles(tmp_path: Path) -> None:
    assert compiled(_schema("86")).validate(etree.parse(str(FIXTURES / "small.x86")))
    raw, dataset, profile = _dataset(FIXTURES / "small.x86", "86")
    assert raw.format is DocumentFormat.GAEB_X86
    items = [row for row in dataset.tables[0].rows if row.kind is RowKind.ITEM]
    assert len(items) == 2 and all(row.counts_toward_totals for row in items)
    assert [i.title for i in _run(dataset, profile).issues] == []


SAMPLES = Path(os.environ.get("TWB_GAEB_SAMPLES", "/nonexistent"))
OFFICIAL = {
    "81": "BVBS-AVA-X81/BVBS_Pruefdatei GAEB DA XML 3.3 - AVA - V 11 06 2021.X81",
    "83": "BVBS-Bau-X83/Pruefdatei GAEB DA XML 3.3 - Bauausfuehrung - V 04 04 2024.x83",
    "84": "BVBS-AVA-X84/BVBS_Pruefdatei GAEB DA XML 3.3 - AVA - V 11 06 2021.X84",
}


@pytest.mark.skipif(not SAMPLES.is_dir(), reason="TWB_GAEB_SAMPLES (BVBS test files) not set")
@pytest.mark.parametrize("phase", sorted(OFFICIAL))
def test_official_bvbs_files(phase: str) -> None:
    path = SAMPLES / OFFICIAL[phase]
    xml = etree.parse(str(path))
    items = len(xml.findall(".//{*}Item"))
    _, dataset, profile = _dataset(path, phase)
    table = dataset.tables[0]
    assert sum(row.kind is RowKind.ITEM for row in table.rows) == items  # one row per Item
    if phase == "81":  # 12 STLBBau + 29 StLNo, of which 3 sit in sub-descriptions (not shown)
        column = table.column_for_field("standard_text_key")
        assert column is not None
        texts = [
            r.cells[column.column_id].raw_value for r in table.rows if column.column_id in r.cells
        ]
        assert sum(len(text.split("; ")) for text in texts if text) == 12 + 26
    titles = [i.title for i in _run(dataset, profile).issues]
    assert not any("Missing" in title for title in titles)
