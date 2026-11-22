"""Ingestion adapters for GAEB bills of quantities: DA XML (X81, X83, X84, X86 in versions 3.1,
3.2 and 3.3) and GAEB 90 (D81, D83, D84, D86).

One adapter instance per format and exchange phase, so the format the upload check derived from
the file extension (``.x83`` -> ``gaeb_x83``, ``.d83`` -> ``gaeb_d83``) tells the reader which
phase the file must declare.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import IngestionLimits
from app.ingestion.base import RawWorkbook
from app.ingestion.gaeb import gaeb90
from app.ingestion.gaeb.flatten import flatten
from app.ingestion.gaeb.model import GaebDocument
from app.ingestion.gaeb.reader import read_gaeb
from app.ingestion.gaeb.schemas import PHASES
from app.models.document import DocumentFormat


class GaebAdapter:
    adapter_id = "gaeb.lxml"
    adapter_version = "1.1.0"

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.format = DocumentFormat(f"gaeb_x{phase}")
        self.formats = frozenset({self.format})

    def read(self, path: Path) -> GaebDocument:
        return read_gaeb(path, self.phase)

    def extract(self, path: Path, limits: IngestionLimits) -> RawWorkbook:
        document = self.read(path)
        sheet, warnings = flatten(document, limits)
        details: dict[str, str | int | float | bool | None] = {
            "gaeb_version": document.version,
            "gaeb_phase": document.phase,
            "gaeb_dp": document.dp,
            "gaeb_schema": document.schema_file,
            "gaeb_schema_sha256": document.schema_sha256,
            "gaeb_boq_id": document.boq_id,
            "project": document.project,
            "currency": document.currency,
            "document_date": document.date,
        }
        if document.encoding is not None:
            details["encoding"] = document.encoding
        return RawWorkbook(
            format=self.format,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            sheets=[sheet],
            details=details,
            warnings=warnings,
        )


class Gaeb90Adapter(GaebAdapter):
    adapter_id = "gaeb.gaeb90"
    adapter_version = "1.0.0"

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.format = DocumentFormat(f"gaeb_d{phase}")
        self.formats = frozenset({self.format})

    def read(self, path: Path) -> GaebDocument:
        return gaeb90.read_gaeb90(path, self.phase)


def gaeb_adapters() -> list[GaebAdapter]:
    return [
        *(GaebAdapter(phase) for phase in PHASES),
        *(Gaeb90Adapter(phase) for phase in gaeb90.PHASES),
    ]
