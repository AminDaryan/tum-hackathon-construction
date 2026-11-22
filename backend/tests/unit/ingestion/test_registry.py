"""Adapter registry: one adapter per document format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.config import IngestionLimits
from app.core.errors import RegistryError, UnsupportedFormatError
from app.ingestion.base import RawWorkbook
from app.ingestion.csv_adapter import CsvAdapter
from app.ingestion.gaeb.adapter import Gaeb90Adapter, GaebAdapter
from app.ingestion.registry import AdapterRegistry, default_adapters
from app.ingestion.xlsx_adapter import XlsxAdapter
from app.models.document import DocumentFormat


@dataclass
class _StubAdapter:
    """Satisfies the adapter protocol; the registry never calls ``extract``."""

    adapter_id: str
    formats: frozenset[DocumentFormat]
    adapter_version: str = "0.0.1"

    def extract(self, path: Path, limits: IngestionLimits) -> RawWorkbook:
        raise AssertionError("not used by the registry")


class TestDefaultAdapters:
    def test_one_adapter_per_built_in_format(self) -> None:
        registry = AdapterRegistry(default_adapters())
        assert isinstance(registry.for_format(DocumentFormat.XLSX), XlsxAdapter)
        assert isinstance(registry.for_format(DocumentFormat.CSV), CsvAdapter)
        gaeb = registry.for_format(DocumentFormat.GAEB_X83)
        assert isinstance(gaeb, GaebAdapter) and gaeb.phase == "83"
        assert registry.formats() == [
            DocumentFormat.XLSX,
            DocumentFormat.CSV,
            DocumentFormat.GAEB_X81,
            DocumentFormat.GAEB_X83,
            DocumentFormat.GAEB_X84,
            DocumentFormat.GAEB_X86,
            DocumentFormat.GAEB_D81,
            DocumentFormat.GAEB_D83,
            DocumentFormat.GAEB_D84,
            DocumentFormat.GAEB_D86,
            DocumentFormat.PDF,
            DocumentFormat.DOCX,
        ]
        gaeb90 = registry.for_format(DocumentFormat.GAEB_D84)
        assert isinstance(gaeb90, Gaeb90Adapter) and gaeb90.phase == "84"

    def test_adapter_identities(self) -> None:
        assert [(a.adapter_id, a.adapter_version) for a in default_adapters()] == [
            ("xlsx.openpyxl", "1.1.0"),  # 1.1.0: non-finite numbers, hidden rows and columns
            ("csv.stdlib", "1.0.0"),
            # one per exchange phase; 1.1.0: versions 3.1 and 3.2, phase X86
            *[("gaeb.lxml", "1.1.0")] * 4,  # X81, X83, X84, X86
            *[("gaeb.gaeb90", "1.0.0")] * 4,  # D81, D83, D84, D86
            ("pdf.pdfium", "1.1.0"),  # 1.1.0: text recognition (OCR) for scanned pages
            ("docx.ooxml", "1.0.0"),
        ]

    def test_every_format_is_covered(self) -> None:
        assert set(AdapterRegistry(default_adapters()).formats()) == set(DocumentFormat)


class TestRegistration:
    def test_duplicate_format_is_refused(self) -> None:
        with pytest.raises(RegistryError) as excinfo:
            AdapterRegistry(
                [CsvAdapter(), _StubAdapter("csv.other", frozenset({DocumentFormat.CSV}))]
            )
        assert excinfo.value.code == "registry_error"
        assert "'csv'" in excinfo.value.message
        assert "csv.stdlib" in excinfo.value.message
        assert "csv.other" in excinfo.value.message

    def test_one_adapter_may_handle_several_formats(self) -> None:
        both = _StubAdapter("multi", frozenset(DocumentFormat))
        registry = AdapterRegistry([both])
        assert all(registry.for_format(f) is both for f in DocumentFormat)

    def test_formats_follow_the_declaration_order(self) -> None:
        registry = AdapterRegistry([CsvAdapter(), XlsxAdapter()])
        assert registry.formats() == [DocumentFormat.XLSX, DocumentFormat.CSV]


class TestLookup:
    def test_unregistered_format(self) -> None:
        registry = AdapterRegistry([CsvAdapter()])
        with pytest.raises(UnsupportedFormatError) as excinfo:
            registry.for_format(DocumentFormat.XLSX)
        assert excinfo.value.code == "unsupported_format"
        assert excinfo.value.details == {"available": ["csv"]}
        assert "'xlsx'" in excinfo.value.message

    def test_empty_registry(self) -> None:
        registry = AdapterRegistry([])
        assert registry.formats() == []
        with pytest.raises(UnsupportedFormatError):
            registry.for_format(DocumentFormat.CSV)
