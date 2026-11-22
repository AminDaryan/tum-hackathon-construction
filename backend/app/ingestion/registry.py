"""Selects the ingestion adapter for a detected document format.

CONTRACT (implemented by the ingestion work package): ``AdapterRegistry`` maps each
:class:`DocumentFormat` to exactly one adapter (duplicate registration raises
:class:`app.core.errors.RegistryError`; an unregistered format raises
:class:`app.core.errors.UnsupportedFormatError`). ``default_adapters()`` returns the built-in
XLSX (openpyxl) and CSV (stdlib csv) adapters. PDF/OCR adapters are added here later without
touching normalization or validation.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.core.config import OcrSettings
from app.core.errors import RegistryError, UnsupportedFormatError
from app.ingestion.base import IngestionAdapter
from app.ingestion.csv_adapter import CsvAdapter
from app.ingestion.docx.adapter import DocxAdapter
from app.ingestion.gaeb.adapter import gaeb_adapters
from app.ingestion.pdf.adapter import PdfAdapter
from app.ingestion.xlsx_adapter import XlsxAdapter
from app.models.document import DocumentFormat


class AdapterRegistry:
    """Immutable mapping from document format to the one adapter that reads it."""

    def __init__(self, adapters: Iterable[IngestionAdapter]) -> None:
        self._adapters: dict[DocumentFormat, IngestionAdapter] = {}
        for adapter in adapters:
            for document_format in sorted(adapter.formats):
                existing = self._adapters.get(document_format)
                if existing is not None:
                    raise RegistryError(
                        f"Format {document_format.value!r} is already handled by adapter "
                        f"{existing.adapter_id!r}; {adapter.adapter_id!r} cannot register it too."
                    )
                self._adapters[document_format] = adapter

    def for_format(self, document_format: DocumentFormat) -> IngestionAdapter:
        """The adapter for ``document_format``; :class:`UnsupportedFormatError` if none."""
        try:
            return self._adapters[document_format]
        except KeyError:
            raise UnsupportedFormatError(
                f"No ingestion adapter is registered for the format {str(document_format)!r}.",
                details={"available": [f.value for f in self.formats()]},
            ) from None

    def formats(self) -> list[DocumentFormat]:
        """Registered formats in :class:`DocumentFormat` declaration order."""
        return [
            document_format
            for document_format in DocumentFormat
            if document_format in self._adapters
        ]


def default_adapters(ocr: OcrSettings | None = None) -> list[IngestionAdapter]:
    """The built-in adapters: XLSX via openpyxl, delimited text via the stdlib csv module,
    GAEB DA XML and GAEB 90 (one adapter per exchange phase), printed bills in PDF (with
    text recognition for scanned pages as ``ocr`` configures it) and Word documents."""
    return [XlsxAdapter(), CsvAdapter(), *gaeb_adapters(), PdfAdapter(ocr), DocxAdapter()]
