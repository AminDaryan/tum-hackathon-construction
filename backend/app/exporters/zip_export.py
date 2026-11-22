"""``tables.zip``: the issue register, one CSV per table and a manifest.

Entries (``docs/api/rest-api.md``, section Exports):

* ``issues.csv``: as :func:`app.exporters.csv_export.issues_csv` writes it;
* ``<NN>-<safe table name>.csv`` per table (:func:`app.exporters.filenames.table_entry_name`;
  ``NN`` is the 1-based table index), as :func:`app.exporters.csv_export.table_csv` writes it;
* ``manifest.json``: the run, dataset revision, document, profile and ``generated_at`` the
  archive was made from, and every other entry with a one-line description (tables also with
  their id, real name and row count, since entry names are reduced to safe characters).

The archive is deterministic: entries sorted by name, ``ZIP_DEFLATED`` at a fixed level, every
timestamp taken from ``generated_at`` (UTC wall-clock time, clamped to the range ZIP can
store), fixed permissions and creator system, no comments or extra fields. Entry names never
contain a path separator or ``..``.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any

from app.exporters.bundle import ExportBundle
from app.exporters.csv_export import issues_csv, table_csv
from app.exporters.filenames import table_entry_name
from app.exporters.json_export import dump_json

ZIP_FORMAT = "tabular-integrity-workbench/tables-zip"
ZIP_FORMAT_VERSION = 1
ISSUES_ENTRY = "issues.csv"
MANIFEST_ENTRY = "manifest.json"
COMPRESS_LEVEL = 9
_FILE_MODE = 0o100644  # regular file, rw-r--r--
_UNIX = 3  # "made by" system in the ZIP header; fixed so the bytes do not depend on the OS
_ZIP_DATE_RANGE = ((1980, 1, 1, 0, 0, 0), (2107, 12, 31, 23, 59, 58))

NOTES: tuple[str, ...] = (
    "CSV files are UTF-8 with a byte-order mark, comma-separated, RFC 4180 quoting, CRLF line "
    "endings.",
    "Text that a spreadsheet could read as a formula (starting with =, +, -, @, a tab or a "
    "carriage return, also after leading whitespace) is prefixed with an apostrophe ('); "
    "numbers are written in plain notation without one.",
    "The original upload is stored unchanged; these files are derived from the dataset "
    "revision named above.",
)


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def zip_timestamp(moment: datetime) -> tuple[int, int, int, int, int, int]:
    """The ZIP (DOS) timestamp for ``moment``: its fields, clamped to 1980..2107."""
    fields = (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)
    low, high = _ZIP_DATE_RANGE
    return min(max(fields, low), high)


def manifest(bundle: ExportBundle, files: list[dict[str, Any]]) -> dict[str, Any]:
    """What the archive contains and which run, revision and document it describes."""
    run, dataset, document = bundle.run, bundle.dataset, bundle.document
    return {
        "format": ZIP_FORMAT,
        "format_version": ZIP_FORMAT_VERSION,
        "generated_at": bundle.generated_at_text,
        "validation_run_id": run.run_id,
        "dataset_id": dataset.dataset_id,
        "dataset_revision": dataset.revision,
        "document": {
            "document_id": document.document_id,
            "original_filename": document.original_filename,
        },
        "profile": {"profile_id": run.profile_id, "version": run.profile_version},
        "files": files,
        "notes": list(NOTES),
    }


def archive_entries(bundle: ExportBundle) -> dict[str, bytes]:
    """Entry name -> content, including ``manifest.json``."""
    entries: dict[str, bytes] = {ISSUES_ENTRY: issues_csv(bundle)}
    files: list[dict[str, Any]] = [
        {
            "name": ISSUES_ENTRY,
            "description": (
                f"Issue register of validation run {bundle.run.run_id}: one row per finding, "
                f"{_count(len(bundle.issues), 'finding')}."
            ),
        }
    ]
    for index, table in enumerate(bundle.dataset.tables, start=1):
        name = table_entry_name(index, table.name)
        entries[name] = table_csv(table)
        files.append(
            {
                "name": name,
                "description": (
                    f"Table {index}, {_count(len(table.rows), 'row')}: source row number, row "
                    "kind, then one column per table column under its original header; cell "
                    "values as extracted."
                ),
                "table_id": table.table_id,
                "table_name": table.name,
                "row_count": len(table.rows),
            }
        )
    files.sort(key=lambda entry: entry["name"])
    entries[MANIFEST_ENTRY] = dump_json(manifest(bundle, files), indent=2)
    return entries


def tables_zip(bundle: ExportBundle) -> bytes:
    """The deterministic ``tables.zip`` archive."""
    timestamp = zip_timestamp(bundle.generated_at)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(archive_entries(bundle).items()):
            info = zipfile.ZipInfo(filename=name, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _FILE_MODE << 16
            info.create_system = _UNIX
            archive.writestr(info, content, compresslevel=COMPRESS_LEVEL)
    return buffer.getvalue()


class TablesZipExporter:
    """``GET /validation-runs/{run_id}/export/tables.zip``."""

    format_id = "tables.zip"
    media_type = "application/zip"
    filename_suffix = " tables.zip"

    def export(self, bundle: ExportBundle) -> bytes:
        return tables_zip(bundle)
