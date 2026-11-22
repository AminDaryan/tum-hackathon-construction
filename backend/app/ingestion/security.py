"""Upload safety checks, run before any parser touches a file.

CONTRACT (implemented by the ingestion work package):

* ``sanitize_filename``: display-safe name. Unicode NFC; only the last path component is kept
  (a client-side directory such as ``C:\\fakepath\\`` is not part of the name); Unicode
  categories Cc, Cf, Zl, Zp and Cs are dropped; each of ``\\ / : * ? " < > | ;`` becomes ``_``;
  leading and trailing dots and whitespace are stripped (Windows drops trailing ones); a
  reserved Windows device name (``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM0``-``COM9``,
  ``LPT0``-``LPT9`` and the superscript ``COM¹``-``LPT³`` variants, any case, with or without
  an extension) gets a ``_`` prefix; at most 255 UTF-8 bytes, cut at a character boundary and
  keeping a short extension; ``"upload"`` when nothing remains. The result is metadata only:
  originals are stored under their SHA-256 (:mod:`app.storage.file_store` takes no name).
* ``detect_format``: extension allowlist (``.xlsx``; ``.csv``, ``.tsv``, ``.txt``; GAEB DA XML
  ``.x81``, ``.x83``, ``.x84``, ``.x86``; GAEB 90 ``.d81``, ``.d83``, ``.d84``, ``.d86``; ``.pdf``;
  ``.docx``) **and** content sniffing must agree. A PDF must start with ``%PDF-``. XLSX must be
  a ZIP whose entries include ``[Content_Types].xml`` and ``xl/workbook.xml``, a Word document
  (DOCX) one whose entries include ``[Content_Types].xml`` and ``word/document.xml``; a legacy
  ``.doc`` is refused with the advice to save it as ``.docx``; delimited text and
  GAEB files must not start with ZIP/OLE/PDF magic bytes and must not contain NUL bytes in
  their first 64 KiB (the
  GAEB adapter then checks namespace, phase, version and the official schema). Mismatch ->
  :class:`UnsupportedFormatError`. An OLE2 compound file (signature ``D0 CF 11 E0 A1 B1 1A E1``:
  a password-protected workbook, whose encrypted package is an OLE container, or a legacy
  ``.xls``) is rejected with "Password-protected workbook or legacy .xls file (not supported)."
  whatever its extension (named as a Word document for ``.docx``), before any parser runs.
  It is a format problem like the other sniffing results, hence :class:`UnsupportedFormatError`
  (415 ``unsupported_format``, a subclass of :class:`FileRejectedError`).
* ``inspect_xlsx_container`` and ``inspect_docx_container`` (both
  ``inspect_ooxml_container``): read only the ZIP central directory (no decompression) and reject
  archives with too many entries, total uncompressed size over the limit, any entry whose
  compression ratio exceeds the limit (zip bombs), encrypted entries, absolute paths, ``..``
  segments, backslashes or NUL bytes in entry names. They return warnings (not errors) for
  macro projects (``vbaProject.bin``: ignored, never executed) and, in a workbook, external
  links (never fetched).

Implementation notes:

* Text that starts with a UTF-16 byte-order mark has a zero byte in every ASCII character, so for
  such text the NUL check applies to the decoded UTF-16 code units instead of raw bytes.
  Otherwise UTF-16 exports (Excel's "Unicode Text") could never be uploaded although the CSV
  adapter reads them.
* An empty file is rejected with :class:`FileRejectedError`: there is nothing to sniff or extract.
* :class:`TableLimitGuard` is the one place where the per-table limits of
  :class:`~app.core.config.IngestionLimits` are enforced while adapters extract cells; it
  charges every admitted cell to a :class:`WorkbookCellBudget` shared by all tables of the
  workbook, which enforces ``max_cells_per_workbook``.

No message echoes a filesystem path.
"""

from __future__ import annotations

import codecs
import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.core.config import IngestionLimits
from app.core.errors import ExtractionError, FileRejectedError, UnsupportedFormatError
from app.models.dataset import ExtractionWarning
from app.models.document import DocumentFormat

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Extension allowlist: the single source for the detected format and the stored media type.
_EXTENSIONS: dict[str, tuple[DocumentFormat, str]] = {
    ".xlsx": (DocumentFormat.XLSX, XLSX_MEDIA_TYPE),
    ".csv": (DocumentFormat.CSV, "text/csv"),
    ".tsv": (DocumentFormat.CSV, "text/tab-separated-values"),
    ".txt": (DocumentFormat.CSV, "text/plain"),
    # GAEB DA XML: the extension names the exchange phase; the adapter checks the file agrees.
    ".x81": (DocumentFormat.GAEB_X81, "application/xml"),
    ".x83": (DocumentFormat.GAEB_X83, "application/xml"),
    ".x84": (DocumentFormat.GAEB_X84, "application/xml"),
    ".x86": (DocumentFormat.GAEB_X86, "application/xml"),
    # GAEB 90: fixed-column text, the extension names the exchange phase in the same way.
    ".d81": (DocumentFormat.GAEB_D81, "text/plain"),
    ".d83": (DocumentFormat.GAEB_D83, "text/plain"),
    ".d84": (DocumentFormat.GAEB_D84, "text/plain"),
    ".d86": (DocumentFormat.GAEB_D86, "text/plain"),
    # A printed bill of quantities: its text layer is read; the content must be a PDF.
    ".pdf": (DocumentFormat.PDF, "application/pdf"),
    # A Word document: its tables, or a bill written as item paragraphs.
    ".docx": (DocumentFormat.DOCX, DOCX_MEDIA_TYPE),
}
# Extensions that are refused with advice instead of the list of supported ones.
_UNSUPPORTED_ADVICE: dict[str, str] = {
    ".doc": "Legacy Word .doc files are not supported. Save the document as .docx (Word: File > "
    "Save As > Word Document) or as PDF, and upload that.",
}
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(_EXTENSIONS)
REQUIRED_XLSX_PARTS: frozenset[str] = frozenset({"[Content_Types].xml", "xl/workbook.xml"})
REQUIRED_DOCX_PARTS: frozenset[str] = frozenset({"[Content_Types].xml", "word/document.xml"})

_SNIFF_BYTES = 64 * 1024
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PDF_MAGIC = b"%PDF-"
_UTF16_BOMS = ((codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"))
# Errors raised by zipfile for archives whose central directory cannot be read.
_ZIP_READ_FAILURES = (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError)
_ENCRYPTED_FLAG = 0x1

_FALLBACK_FILENAME = "upload"
_MAX_FILENAME_BYTES = 255  # UTF-8; the common file-system limit for one name
_MAX_KEPT_EXTENSION_CHARS = 16
_REPLACEMENT = "_"
_REPLACED_FILENAME_CHARS = frozenset('\\/:*?"<>|;')
# Controls, format characters (e.g. bidi overrides used to disguise extensions), surrogates and
# line/paragraph separators.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_DIRECTORY_SEPARATORS = re.compile(r"[/\\]")
_OUTER_DOTS_AND_SPACES = re.compile(r"^[\s.]+|[\s.]+$")
# Windows device names, reserved with any extension ("con.txt" opens the console). Microsoft's
# list includes COM0/LPT0 and the superscript digits ¹ ² ³.
_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"{device}{digit}" for device in ("COM", "LPT") for digit in "0123456789¹²³"}
)
_DRIVE_PREFIX = re.compile(r"[A-Za-z]:")


@dataclass(frozen=True, slots=True)
class UploadCheck:
    format: DocumentFormat
    media_type: str
    warnings: list[ExtractionWarning] = field(default_factory=list)


class _Content(StrEnum):
    """What the first bytes (and, for ZIPs, the central directory) say a file is."""

    XLSX = "xlsx"
    DOCX = "docx"
    ZIP = "zip"
    OLE = "ole"
    PDF = "pdf"
    BINARY = "binary"
    TEXT = "text"


OLE_CONTAINER_MESSAGE = "Password-protected workbook or legacy .xls file (not supported)."
OLE_WORD_MESSAGE = (
    "Password-protected or legacy Word document (not supported). Save it as an unprotected .docx "
    "and upload that."
)

# Descriptions for extension/content mismatches; OLE containers have their own message.
_CONTENT_DESCRIPTIONS: dict[_Content, str] = {
    _Content.XLSX: "an XLSX workbook",
    _Content.DOCX: "a Word document (DOCX)",
    _Content.ZIP: "a ZIP archive that is neither a valid XLSX workbook nor a Word document",
    _Content.PDF: "a PDF document",
    _Content.BINARY: "binary data (it contains NUL bytes)",
    _Content.TEXT: "plain text",
}


# --------------------------------------------------------------------------- file names
def sanitize_filename(name: str | None) -> str:
    """Return a display-safe version of a user-supplied file name (rules in the module
    docstring). Returns ``"upload"`` when nothing usable remains. The result is metadata only
    and must never be used to build a filesystem path."""
    if not name:
        return _FALLBACK_FILENAME
    base = _DIRECTORY_SEPARATORS.split(unicodedata.normalize("NFC", name))[-1]
    cleaned = _strip_outer_dots_and_spaces("".join(_clean_filename_char(char) for char in base))
    if _is_reserved_device_name(cleaned):
        cleaned = _REPLACEMENT + cleaned
    cleaned = _strip_outer_dots_and_spaces(_truncate_filename(cleaned))
    return cleaned or _FALLBACK_FILENAME


def _clean_filename_char(char: str) -> str:
    """``""`` for invisible or control characters, ``"_"`` for reserved ones, else ``char``."""
    if unicodedata.category(char) in _STRIPPED_CATEGORIES:
        return ""
    return _REPLACEMENT if char in _REPLACED_FILENAME_CHARS else char


def _strip_outer_dots_and_spaces(name: str) -> str:
    return _OUTER_DOTS_AND_SPACES.sub("", name)


def _is_reserved_device_name(name: str) -> bool:
    """Windows treats ``CON``, ``con.txt`` and ``CON .tar.gz`` alike: the part before the first
    dot, without trailing spaces, decides."""
    return name.partition(".")[0].rstrip(" ").upper() in _RESERVED_DEVICE_NAMES


def _truncate_filename(name: str) -> str:
    """At most :data:`_MAX_FILENAME_BYTES` UTF-8 bytes, cut at a character boundary; a short
    extension (up to 16 characters) is kept when the stem can give way."""
    if _utf8_length(name) <= _MAX_FILENAME_BYTES:
        return name
    stem, dot, extension = name.rpartition(".")
    if dot and stem and len(extension) <= _MAX_KEPT_EXTENSION_CHARS:
        suffix = f".{extension}"
        return _truncate_utf8(stem, _MAX_FILENAME_BYTES - _utf8_length(suffix)) + suffix
    return _truncate_utf8(name, _MAX_FILENAME_BYTES)


def _utf8_length(text: str) -> int:
    return len(text.encode("utf-8"))


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """The longest prefix of ``text`` that fits ``max_bytes`` UTF-8 bytes. Surrogates were
    dropped before, so every character encodes; ``errors="ignore"`` only drops the character
    the byte cut went through."""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _extension_of(filename: str) -> str:
    """Lower-case extension (with the dot) of the sanitized name, or ``""``."""
    _, dot, extension = sanitize_filename(filename).rpartition(".")
    return f".{extension.lower()}" if dot else ""


# --------------------------------------------------------------------------- format detection
def detect_format(path: Path, filename: str) -> DocumentFormat:
    """Return the format of the upload at ``path`` when its extension and content agree.

    Raises :class:`UnsupportedFormatError` for extensions outside the allowlist and for content
    that does not match the extension, and :class:`FileRejectedError` for an empty file.
    """
    extension = _extension_of(filename)
    entry = _EXTENSIONS.get(extension)
    if entry is None and extension in _UNSUPPORTED_ADVICE:
        raise UnsupportedFormatError(
            _UNSUPPORTED_ADVICE[extension],
            details={"extension": extension, "supported": list(SUPPORTED_EXTENSIONS)},
        )
    if entry is None:
        shown = f"'{extension}'" if 0 < len(extension) <= 20 else "this type"
        raise UnsupportedFormatError(
            f"Files of {shown} are not supported. Upload one of: "
            f"{', '.join(SUPPORTED_EXTENSIONS)}.",
            details={"extension": extension or None, "supported": list(SUPPORTED_EXTENSIONS)},
        )
    expected = entry[0]
    with path.open("rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    if not head:
        raise FileRejectedError("The file is empty.", details={"reason": "empty_file"})
    if head.startswith(_OLE_MAGIC):  # before _sniff, which opens ZIP archives
        message = OLE_WORD_MESSAGE if expected is DocumentFormat.DOCX else OLE_CONTAINER_MESSAGE
        raise UnsupportedFormatError(
            message, details={"extension": extension, "detected": _Content.OLE.value}
        )
    content = _sniff(path, head)
    wanted = _WANTED_CONTENT.get(expected, _Content.TEXT)
    if content is not wanted:
        raise UnsupportedFormatError(
            _mismatch_message(extension, content),
            details={"extension": extension, "detected": content.value},
        )
    return expected


_WANTED_CONTENT: dict[DocumentFormat, _Content] = {
    DocumentFormat.XLSX: _Content.XLSX,
    DocumentFormat.PDF: _Content.PDF,
    DocumentFormat.DOCX: _Content.DOCX,
}


def _sniff(path: Path, head: bytes) -> _Content:
    """What a non-empty file that is not an OLE container is (see :func:`detect_format`)."""
    if head.startswith(_ZIP_MAGIC):
        names = _zip_entry_names(path)
        if names is not None and names >= REQUIRED_XLSX_PARTS:
            return _Content.XLSX
        if names is not None and names >= REQUIRED_DOCX_PARTS:
            return _Content.DOCX
        return _Content.ZIP
    if head.startswith(_PDF_MAGIC):
        return _Content.PDF
    if _contains_nul(head):
        return _Content.BINARY
    return _Content.TEXT


def _zip_entry_names(path: Path) -> set[str] | None:
    try:
        with zipfile.ZipFile(path) as archive:
            return set(archive.namelist())
    except _ZIP_READ_FAILURES:
        return None


def _contains_nul(head: bytes) -> bool:
    """NUL characters mark binary content. For text with a UTF-16 byte-order mark the check runs
    on code units, because every ASCII character of UTF-16 text contains a zero byte."""
    for bom, codec in _UTF16_BOMS:
        if head.startswith(bom):
            payload = head[len(bom) :]
            payload = payload[: len(payload) - len(payload) % 2]  # the window may split a unit
            return "\x00" in payload.decode(codec, errors="replace")
    return b"\x00" in head


def _mismatch_message(extension: str, content: _Content) -> str:
    message = (
        f"The file name ends with {extension} but the content is {_CONTENT_DESCRIPTIONS[content]}."
    )
    if content is _Content.XLSX:
        return f"{message} Upload it with the extension .xlsx."
    if content is _Content.DOCX:
        return f"{message} Upload it with the extension .docx."
    if content is _Content.TEXT:
        return f"{message} Upload delimited text as .csv, .tsv or .txt."
    if content is _Content.PDF:
        return f"{message} Upload it with the extension .pdf."
    return message


# --------------------------------------------------------------------------- OOXML containers
@dataclass(frozen=True, slots=True)
class _Container:
    noun: str  # "workbook" or "document", in messages
    invalid: str  # "a valid XLSX workbook", "a valid Word document"
    required: frozenset[str]


_XLSX_CONTAINER = _Container("workbook", "a valid XLSX workbook", REQUIRED_XLSX_PARTS)
_DOCX_CONTAINER = _Container("document", "a valid Word document", REQUIRED_DOCX_PARTS)


def inspect_xlsx_container(path: Path, limits: IngestionLimits) -> list[ExtractionWarning]:
    """Check the ZIP container of an XLSX file using only its central directory.

    Raises :class:`FileRejectedError` (zip bombs, encryption, unsafe entry names, too many
    entries) or :class:`UnsupportedFormatError` (not a readable XLSX container). Returns
    warnings for content that is present but ignored: macro projects and external links.
    """
    return inspect_ooxml_container(path, limits, _XLSX_CONTAINER)


def inspect_docx_container(path: Path, limits: IngestionLimits) -> list[ExtractionWarning]:
    """The same check for the ZIP container of a Word document (``word/document.xml``)."""
    return inspect_ooxml_container(path, limits, _DOCX_CONTAINER)


def inspect_ooxml_container(
    path: Path, limits: IngestionLimits, container: _Container
) -> list[ExtractionWarning]:
    noun = container.noun
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except _ZIP_READ_FAILURES as exc:
        raise UnsupportedFormatError(
            f"The file is not {container.invalid}: its ZIP container cannot be read."
        ) from exc
    if len(entries) > limits.max_zip_entries:
        raise _rejected(
            f"The {noun} archive has {len(entries):,} entries; the limit is "
            f"{limits.max_zip_entries:,}.",
            "too_many_entries",
        )
    if not {entry.filename for entry in entries} >= container.required:
        raise UnsupportedFormatError(
            f"The file is not {container.invalid}: required parts are missing.",
            details={"required": sorted(container.required)},
        )
    for entry in entries:
        _check_entry(entry, limits, noun)
    total = sum(entry.file_size for entry in entries)
    if total > limits.max_uncompressed_bytes:
        raise _rejected(
            f"The {noun} would expand to {total:,} bytes when decompressed; the limit is "
            f"{limits.max_uncompressed_bytes:,} bytes.",
            "uncompressed_size",
        )
    return _container_warnings(entries, noun)


def _check_entry(entry: zipfile.ZipInfo, limits: IngestionLimits, noun: str) -> None:
    if _is_unsafe_entry_name(entry.orig_filename):
        raise _rejected(
            f"The {noun} archive contains an entry with an unsafe name (absolute path, '..' "
            "segment, backslash or NUL byte).",
            "unsafe_entry_name",
        )
    if entry.flag_bits & _ENCRYPTED_FLAG:
        raise _rejected(
            f"The {noun} archive contains encrypted entries; encrypted files are not supported.",
            "encrypted_entry",
        )
    if entry.file_size / max(entry.compress_size, 1) > limits.max_compression_ratio:
        raise _rejected(
            f"An entry of the {noun} archive is compressed more than "
            f"{limits.max_compression_ratio:g}:1, which is typical of ZIP bombs.",
            "compression_ratio",
        )


def _is_unsafe_entry_name(name: str) -> bool:
    """``orig_filename`` is checked: zipfile truncates ``filename`` at NUL and, on Windows,
    turns backslashes into slashes."""
    return (
        name.startswith("/")
        or _DRIVE_PREFIX.match(name) is not None
        or "\\" in name
        or "\x00" in name
        or ".." in name.split("/")
    )


def _container_warnings(
    entries: list[zipfile.ZipInfo], noun: str = "workbook"
) -> list[ExtractionWarning]:
    names = [entry.filename.lower() for entry in entries]
    warnings: list[ExtractionWarning] = []
    macro_parts = sum(1 for name in names if posixpath.basename(name) == "vbaproject.bin")
    if macro_parts:
        warnings.append(
            ExtractionWarning(
                code="macro_project_ignored",
                message=f"The {noun} contains a VBA macro project. Macros are ignored and "
                "never executed.",
                count=macro_parts,
                needs_review=False,  # informational: no cell value depends on running them
            )
        )
    link_parts = sum(
        1 for name in names if name.startswith("xl/externallinks/") and name.endswith(".xml")
    )
    if link_parts:
        warnings.append(
            ExtractionWarning(
                code="external_links_ignored",
                message=f"The workbook links to {link_parts} external workbook(s). External "
                "links are never followed; formulas that use them keep the results cached in "
                "the file.",
                count=link_parts,
                needs_review=False,  # informational: the cached results are what is extracted
            )
        )
    return warnings


def _rejected(message: str, reason: str) -> FileRejectedError:
    return FileRejectedError(message, details={"reason": reason})


# --------------------------------------------------------------------------- entry point
def validate_upload(path: Path, filename: str, limits: IngestionLimits) -> UploadCheck:
    """Run :func:`detect_format` and the format-specific container checks."""
    document_format = detect_format(path, filename)
    media_type = _EXTENSIONS[_extension_of(filename)][1]
    if document_format is DocumentFormat.XLSX:
        warnings = inspect_xlsx_container(path, limits)
    elif document_format is DocumentFormat.DOCX:
        warnings = inspect_docx_container(path, limits)
    else:
        warnings = []
    return UploadCheck(format=document_format, media_type=media_type, warnings=warnings)


# --------------------------------------------------------------------------- extraction limits
class WorkbookCellBudget:
    """Counts the cells stored for all tables of one workbook against
    ``max_cells_per_workbook``. One budget is shared by the :class:`TableLimitGuard` of every
    table of the workbook; the first cell over the limit raises
    :class:`~app.core.errors.ExtractionError`."""

    def __init__(self, label: str, limits: IngestionLimits) -> None:
        self._label = label  # e.g. "The workbook" or "The file"; never a filesystem path
        self._maximum = limits.max_cells_per_workbook
        self._cells = 0

    def admit(self) -> None:
        self._cells += 1
        if self._cells > self._maximum:
            raise ExtractionError(
                f"{self._label} has more than {self._maximum:,} non-empty cells, the limit per "
                "workbook (all sheets together).",
                details={"limit": "max_cells_per_workbook", "maximum": self._maximum},
            )


class TableLimitGuard:
    """Enforces the per-table limits while an adapter stores cells.

    Adapters call :meth:`admit` once for every cell they store and :meth:`check_text` for every
    text they keep (values and formulas). The first violation raises
    :class:`~app.core.errors.ExtractionError`, so oversized input is rejected early and never
    silently truncated. Row and column limits apply to the table's extent: the highest row and
    column that hold a value. Positions are 1-based; a cell at row or column 0 or below (which a
    malformed sheet can declare) is rejected, because no source coordinate could name it.

    ``workbook`` is the budget shared with the workbook's other tables; without one the table
    is a workbook of its own (delimited text), so ``max_cells_per_workbook`` still applies.
    """

    def __init__(
        self, label: str, limits: IngestionLimits, workbook: WorkbookCellBudget | None = None
    ) -> None:
        self._label = label  # e.g. "Sheet 'LV'" or "The file"; never a filesystem path
        self._limits = limits
        self._cells = 0
        self._workbook = workbook if workbook is not None else WorkbookCellBudget(label, limits)

    def admit(self, row: int, column: int) -> None:
        limits = self._limits
        if row < 1 or column < 1:
            raise ExtractionError(
                f"{self._label} has a cell at an invalid position (row {row:,}, column "
                f"{column:,}); rows and columns start at 1, so the file is malformed.",
                details={"reason": "invalid_cell_position"},
            )
        if row > limits.max_rows_per_table:
            raise self._exceeded(
                f"{self._label} has a value in row {row:,}; the limit is "
                f"{limits.max_rows_per_table:,} rows per table.",
                "max_rows_per_table",
                limits.max_rows_per_table,
            )
        if column > limits.max_columns_per_table:
            raise self._exceeded(
                f"{self._label} has a value in column {column:,}; the limit is "
                f"{limits.max_columns_per_table:,} columns per table.",
                "max_columns_per_table",
                limits.max_columns_per_table,
            )
        self._cells += 1
        if self._cells > limits.max_cells_per_sheet:
            raise self._exceeded(
                f"{self._label} has more than {limits.max_cells_per_sheet:,} non-empty cells, "
                "the limit per table.",
                "max_cells_per_sheet",
                limits.max_cells_per_sheet,
            )
        self._workbook.admit()

    def check_text(self, text: str | None, row: int, column: int) -> None:
        maximum = self._limits.max_cell_chars
        if text is not None and len(text) > maximum:
            raise self._exceeded(
                f"{self._label} has a value longer than {maximum:,} characters (row {row:,}, "
                f"column {column:,}).",
                "max_cell_chars",
                maximum,
            )

    @staticmethod
    def _exceeded(message: str, limit: str, maximum: int) -> ExtractionError:
        return ExtractionError(message, details={"limit": limit, "maximum": maximum})
