"""Delimited-text adapter (CSV, TSV, TXT) built on the standard library :mod:`csv` module.

Every non-empty field becomes a ``STRING`` :class:`~app.ingestion.base.RawCell` holding the text
exactly as written (quotes resolved, nothing stripped or converted); empty fields are not
stored. Numbers, dates and headers are interpreted later by normalization. Delimited text has
no visibility, so nothing is hidden (``RawSheet.hidden_rows`` and ``hidden_columns`` stay
empty); the file counts as a one-table workbook for ``max_cells_per_workbook``.

Encoding: byte-order mark -> strict UTF-8 -> charset_normalizer -> cp1252 -> latin-1. Anything
after strict UTF-8 is a guess and is reported with the ``encoding_guessed`` warning.

Delimiter: each of ``;`` ``,`` TAB ``|`` parses the first 50 records that are not blank lines
(records of empty fields count: ``;;;`` is three fields); the winner is the candidate that splits
records into several fields at all, then the one whose modal field count covers the largest
share of records, then the larger modal count, then the order above. A candidate with a modal
count of 1 only wins when no candidate splits the records (``single_column_file``), so one
ragged record cannot make a comma file look single-column.
"""

from __future__ import annotations

import codecs
import csv
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from charset_normalizer import from_bytes

from app.core.config import IngestionLimits
from app.core.errors import ExtractionError
from app.ingestion.base import RawCell, RawSheet, RawValueType, RawWorkbook
from app.ingestion.security import TableLimitGuard
from app.models.dataset import ExtractionWarning
from app.models.document import DocumentFormat
from app.models.source import SourceKind, SourceLocation

TABLE_NAME = "Table 1"

# (delimiter, name in details) in preference order for ties.
_DELIMITERS: tuple[tuple[str, str], ...] = (
    (";", "semicolon"),
    (",", "comma"),
    ("\t", "tab"),
    ("|", "pipe"),
)
_SAMPLE_RECORDS = 50

# (byte-order mark, reported encoding, codec for the bytes after the mark)
_BOMS: tuple[tuple[bytes, str, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig", "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le", "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be", "utf-16-be"),
)
# Encodings that spreadsheet exports actually use, most common first. charset_normalizer is
# restricted to them because, unrestricted, it picks exotic code pages (mac_latin2, iso8859_10,
# cp1006 ...) for ordinary Western European text; the order also breaks its ties.
_GUESS_ENCODINGS: tuple[str, ...] = (
    "cp1252",
    "cp1250",
    "cp1251",
    "cp1253",
    "cp1254",
    "cp1255",
    "cp1256",
    "cp1257",
    "cp1258",
    "cp932",
    "gb18030",
    "big5",
    "cp949",
    "koi8_r",
)
# charset_normalizer itself treats matches closer than this as a tie (CharsetMatch.__lt__).
_CHAOS_TIE = 0.01
_COHERENCE_TIE = 0.02


class _Dialect(csv.Dialect):
    """Quoted fields use ``"`` with doubled quotes inside; the delimiter is set per call. The
    global ``csv.field_size_limit`` is never changed: its default (131072) is above the default
    ``max_cell_chars``, which is checked separately for every field."""

    delimiter = ","
    quotechar = '"'
    doublequote = True
    skipinitialspace = False
    lineterminator = "\r\n"
    quoting = csv.QUOTE_MINIMAL
    strict = False


# Physical lines as io.StringIO(newline="") yields them: split only at \r\n, \r and \n, endings
# kept. A generator avoids copying the whole text into a 4-bytes-per-character buffer.
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")


class CsvAdapter:
    """Reads delimited text into one raw sheet named ``"Table 1"``."""

    adapter_id = "csv.stdlib"
    adapter_version = "1.0.0"
    formats: frozenset[DocumentFormat] = frozenset({DocumentFormat.CSV})

    def extract(self, path: Path, limits: IngestionLimits) -> RawWorkbook:
        """Read ``path`` (already size/format-checked). Raises
        :class:`~app.core.errors.ExtractionError` when the text cannot be parsed or a limit
        of ``limits`` is exceeded."""
        decoded = decode_text(path.read_bytes())
        delimiter = detect_delimiter(decoded.text)
        parsed = _parse_records(decoded.text, delimiter.character, limits)
        sheet = RawSheet(
            name=TABLE_NAME,
            index=0,
            source_kind=SourceKind.DELIMITED_TEXT,
            cells=parsed.cells,
            max_row=max((row for row, _ in parsed.cells), default=0),
            max_column=max((column for _, column in parsed.cells), default=0),
            warnings=_sheet_warnings(parsed, delimiter),
        )
        return RawWorkbook(
            format=DocumentFormat.CSV,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            sheets=[sheet],
            details={
                "encoding": decoded.encoding,
                "encoding_detection": decoded.detection,
                "delimiter": delimiter.name,
                "records": parsed.records,
            },
            warnings=_encoding_warnings(decoded),
        )


# --------------------------------------------------------------------------- encoding
@dataclass(frozen=True, slots=True)
class DecodedText:
    text: str
    encoding: str  # codec name used, e.g. "utf-8", "utf-16-le", "cp1252"
    detection: str  # "bom" | "utf8_strict" | "charset_normalizer" | "fallback"

    @property
    def guessed(self) -> bool:
        return self.detection not in ("bom", "utf8_strict")


def decode_text(data: bytes) -> DecodedText:
    """Decode ``data`` with the first method of the chain that succeeds strictly:
    byte-order mark, UTF-8, charset_normalizer, cp1252, latin-1 (never fails)."""
    for bom, name, codec in _BOMS:
        if data.startswith(bom):
            try:
                return DecodedText(data[len(bom) :].decode(codec), name, "bom")
            except UnicodeDecodeError:
                break  # a mark followed by invalid data: treat the file as unmarked
    try:
        return DecodedText(data.decode("utf-8"), "utf-8", "utf8_strict")
    except UnicodeDecodeError:
        pass
    guessed = _guess_encoding(data)
    if guessed is not None:
        try:
            return DecodedText(data.decode(guessed), guessed, "charset_normalizer")
        except UnicodeDecodeError:
            pass  # charset_normalizer judged a sample; the whole file must decode strictly
    try:
        return DecodedText(data.decode("cp1252"), "cp1252", "fallback")
    except UnicodeDecodeError:
        return DecodedText(data.decode("latin-1"), "latin-1", "fallback")


def _guess_encoding(data: bytes) -> str | None:
    """charset_normalizer's best match among :data:`_GUESS_ENCODINGS`. Matches it cannot tell
    apart (chaos and coherence within its own tie margins, or identical decodings) are resolved
    by the order of :data:`_GUESS_ENCODINGS` instead of its arbitrary internal order."""
    matches = from_bytes(data, cp_isolation=list(_GUESS_ENCODINGS))
    best = matches.best()
    if best is None:
        return None
    tied = {
        encoding
        for match in matches
        if abs(match.chaos - best.chaos) < _CHAOS_TIE
        and abs(match.coherence - best.coherence) <= _COHERENCE_TIE
        for encoding in match.could_be_from_charset
    }
    return next((name for name in _GUESS_ENCODINGS if name in tied), best.encoding)


def _encoding_warnings(decoded: DecodedText) -> list[ExtractionWarning]:
    if not decoded.guessed:
        return []
    return [
        ExtractionWarning(
            code="encoding_guessed",
            message=f"The file has no byte-order mark and is not valid UTF-8; it was decoded as "
            f"{decoded.encoding}, which is a guess. Check special characters such as umlauts "
            "and currency symbols.",
        )
    ]


# --------------------------------------------------------------------------- delimiter
@dataclass(frozen=True, slots=True)
class DelimiterChoice:
    character: str
    name: str  # "semicolon" | "comma" | "tab" | "pipe"
    modal_fields: int  # most common field count among the sampled records
    share: float  # share of sampled records that have the modal field count
    preference: int  # position in the preference order (0 = preferred)

    @property
    def splits(self) -> bool:
        return self.modal_fields > 1

    @property
    def rank(self) -> tuple[bool, float, int, int]:
        return (self.splits, self.share, self.modal_fields, -self.preference)


def detect_delimiter(text: str) -> DelimiterChoice:
    """Choose the delimiter of ``text``; see the module docstring for the ranking."""
    candidates = [
        _score_delimiter(text, character, name, preference)
        for preference, (character, name) in enumerate(_DELIMITERS)
    ]
    return max(candidates, key=lambda candidate: candidate.rank)


def _score_delimiter(text: str, character: str, name: str, preference: int) -> DelimiterChoice:
    widths: Counter[int] = Counter()
    try:
        for record in csv.reader(_lines(text), _Dialect, delimiter=character):
            if record:  # a blank line has no fields at all
                widths[len(record)] += 1
                if widths.total() >= _SAMPLE_RECORDS:
                    break
    except csv.Error:
        widths.clear()  # this delimiter cannot parse the sample
    modal, frequency = _modal_width(widths)
    total = widths.total()
    return DelimiterChoice(character, name, modal, frequency / total if total else 0.0, preference)


def _modal_width(widths: Counter[int]) -> tuple[int, int]:
    """(field count, frequency) of the most common field count; ties go to the larger count."""
    return max(widths.items(), key=lambda item: (item[1], item[0]), default=(0, 0))


# --------------------------------------------------------------------------- records
@dataclass(slots=True)
class _ParsedRecords:
    cells: dict[tuple[int, int], RawCell] = field(default_factory=dict)
    records: int = 0  # records read, blank ones included
    widths: Counter[int] = field(default_factory=Counter)  # field counts of non-empty records
    first_of_width: dict[int, tuple[int, int]] = field(default_factory=dict)  # (record, line)


def _parse_records(text: str, delimiter: str, limits: IngestionLimits) -> _ParsedRecords:
    """Parse all records. Record numbers count blank lines too, like spreadsheet rows; the line
    number of a record is the physical line it starts on (quoted fields may span lines)."""
    parsed = _ParsedRecords()
    guard = TableLimitGuard("The file", limits)
    reader = csv.reader(_lines(text), _Dialect, delimiter=delimiter)
    previous_line = 0
    try:
        for record_number, record in enumerate(reader, start=1):
            parsed.records = record_number
            line_number = previous_line + 1
            previous_line = reader.line_num
            if not any(record):
                continue
            parsed.widths[len(record)] += 1
            parsed.first_of_width.setdefault(len(record), (record_number, line_number))
            for column, value in enumerate(record, start=1):
                if value:
                    guard.admit(record_number, column)
                    guard.check_text(value, record_number, column)
                    parsed.cells[(record_number, column)] = RawCell(
                        row=record_number,
                        column=column,
                        value_type=RawValueType.STRING,
                        text=value,
                        line_number=line_number,
                    )
    except csv.Error as exc:
        raise ExtractionError(
            f"The file could not be read as delimited text near line {reader.line_num:,} ({exc})."
        ) from exc
    return parsed


def _lines(text: str) -> Iterator[str]:
    for match in _LINE.finditer(text):
        yield match.group()


def _sheet_warnings(parsed: _ParsedRecords, delimiter: DelimiterChoice) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    if parsed.widths and not delimiter.splits:
        warnings.append(
            ExtractionWarning(
                code="single_column_file",
                message="No delimiter (semicolon, comma, tab or pipe) splits the records into "
                "several fields; the file was read as a single column.",
            )
        )
    modal, frequency = _modal_width(parsed.widths)
    ragged = parsed.widths.total() - frequency
    if ragged:
        record, line = min(
            location for width, location in parsed.first_of_width.items() if width != modal
        )
        warnings.append(
            ExtractionWarning(
                code="ragged_rows",
                message=f"{ragged:,} record(s) have a different number of fields than the usual "
                f"{modal}; their values were kept in the positions where they were written.",
                count=ragged,
                source=SourceLocation(
                    kind=SourceKind.DELIMITED_TEXT, row_number=record, line_number=line
                ),
            )
        )
    return warnings
