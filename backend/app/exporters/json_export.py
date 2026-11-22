"""JSON export of one validation run (``docs/api/rest-api.md``, section Exports).

Shape::

    {"export": {"format": "tabular-integrity-workbench/json", "format_version": 1,
                "generated_at": "...Z", "validation_run_id": "run_...", "dataset_id": "ds_...",
                "dataset_revision": 1, "document": {...}, "profile": {"profile_id", "version"}},
     "dataset": Dataset, "validation_run": ValidationRun, "detectors": [DetectorSpec],
     "issues": [ValidationIssue]}

Canonical records are written with ``model_dump(mode="json")``, exactly as the API returns
them: decimals are strings, timestamps ISO 8601 UTC, computed fields included (they are
ignored when the records are parsed back). ``document`` is the API's DocumentSummary without
``last_run`` (the exported run is ``validation_run``; the latest run of the document is not
part of the bundle). Issues keep the bundle's order; detectors are sorted by id and version.

Output is UTF-8 without a byte-order mark, compact, with members in model field order and a
final newline, so the same bundle always gives the same bytes. NaN and infinity are refused
(``allow_nan=False``). Unpaired surrogates in text are written as ``\\uXXXX`` escapes, which
keeps the file valid UTF-8 and the text exact.
"""

from __future__ import annotations

import json
from typing import Any

from app.exporters.bundle import ExportBundle

JSON_FORMAT = "tabular-integrity-workbench/json"
JSON_FORMAT_VERSION = 1


def export_header(bundle: ExportBundle) -> dict[str, Any]:
    """The ``export`` member: what the file is and which run and revision it describes."""
    run = bundle.run
    return {
        "format": JSON_FORMAT,
        "format_version": JSON_FORMAT_VERSION,
        "generated_at": bundle.generated_at_text,
        "validation_run_id": run.run_id,
        "dataset_id": bundle.dataset.dataset_id,
        "dataset_revision": bundle.dataset.revision,
        "document": document_summary(bundle),
        "profile": {"profile_id": run.profile_id, "version": run.profile_version},
    }


def document_summary(bundle: ExportBundle) -> dict[str, Any]:
    """The document as the API's DocumentSummary describes it, without ``last_run``."""
    document = bundle.document.model_dump(mode="json", exclude={"source_file"})
    model = bundle.document.model
    if model is not None:  # as the API's ModelInfo: the file's digest, not its storage key
        document["model"] = {
            "filename": model.filename,
            "sha256": model.file.sha256,
            "size_bytes": model.file.size_bytes,
            **model.model_dump(mode="json", exclude={"file", "filename"}),
        }
    tables = bundle.dataset.tables
    return {
        **document,
        "size_bytes": bundle.document.source_file.size_bytes,
        "sha256": bundle.document.source_file.sha256,
        "dataset_id": bundle.dataset.dataset_id,
        "table_count": len(tables),
        "row_count": sum(len(table.rows) for table in tables),
    }


def export_payload(bundle: ExportBundle) -> dict[str, Any]:
    """The complete JSON document as Python data."""
    detectors = sorted(bundle.detectors, key=lambda spec: (spec.detector_id, spec.version))
    return {
        "export": export_header(bundle),
        "dataset": bundle.dataset.model_dump(mode="json"),
        "validation_run": bundle.run.model_dump(mode="json"),
        "detectors": [spec.model_dump(mode="json") for spec in detectors],
        "issues": [issue.model_dump(mode="json") for issue in bundle.issues],
    }


def dump_json(data: Any, *, indent: int | None = None) -> bytes:
    """Deterministic UTF-8 JSON with a final newline; NaN and infinity are refused."""
    separators = (",", ": ") if indent is not None else (",", ":")
    text = json.dumps(
        data, ensure_ascii=False, allow_nan=False, indent=indent, separators=separators
    )
    # Every non-ASCII character json.dumps leaves in place sits inside a string literal, so a
    # lone surrogate written as a \\uXXXX escape is valid JSON and parses back unchanged.
    return (text + "\n").encode("utf-8", errors="backslashreplace")


def export_json(bundle: ExportBundle) -> bytes:
    """The JSON export file."""
    return dump_json(export_payload(bundle))


class JsonExporter:
    """``GET /validation-runs/{run_id}/export/json``."""

    format_id = "json"
    media_type = "application/json"
    filename_suffix = ".json"

    def export(self, bundle: ExportBundle) -> bytes:
        return export_json(bundle)
