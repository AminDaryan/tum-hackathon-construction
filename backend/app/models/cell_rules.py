"""The normalization output rules for single cells, in one tested place.

Normalization (``app.normalization``) and the dataset builders of the test suite
(``tests/support/builders.py``) both construct canonical cells through these functions, so a
detector that passes its unit tests sees exactly the cells real files produce. The output
matrix (the same table, with examples, is in ``docs/architecture/data-model.md``), as
``raw content -> data_type / parse_status / parsed_value / normalized_value``:

* missing cell, empty, or blank text -> EMPTY / not_applicable / None / None
* typed number (XLSX) or unambiguous number text -> NUMBER / exact / NumberValue / same value
* number text resolved by column or document evidence -> NUMBER / inferred / NumberValue / same
* number text with several readings (``1.234``) -> UNKNOWN / ambiguous / None / None
* text in a numeric or date field that is not one, or a number outside ``BoundedDecimal`` ->
  TEXT / failed / TextValue(raw) / TextValue(collapsed), with a ``parse_note``
* profile value marker in a numeric field (``Incl.``) -> TEXT / marker / TextValue(raw) /
  TextValue(collapsed), with ``Cell.marker`` set (the only case where it is set)
* plain text (text field or unmapped column) -> TEXT / not_applicable / TextValue(raw) /
  TextValue(collapsed)
* unit text -> TEXT / not_applicable / TextValue(raw) / TextValue(unit_id) when the unit
  catalogue or a reviewer's unit alias resolves it, else TextValue(collapsed)
* boolean, date, datetime -> BOOLEAN, DATE or DATETIME / exact (inferred for parsed dates that
  needed the profile's date order) / the typed value / the same value; an undecidable
  day/month order -> UNKNOWN / ambiguous / None / None
* spreadsheet error literal (``#REF!``) -> ERROR / exact / ErrorValue / same value
* formula whose cached result is not stored -> UNKNOWN / unavailable / None / None

* **Blank text**: only whitespace (``str.isspace``, which includes NBSP and the other Unicode
  spaces) or invisible format characters (Unicode category ``Cf``, e.g. a zero-width space).
  A blank cell is EMPTY, but ``raw_value`` keeps the text exactly as extracted.
* **Collapsed text** (:func:`normalize_text`): Unicode NFC, runs of whitespace replaced by one
  space, outer whitespace removed. No case folding and no NFKC: the normalized text is still
  what the document says (``m²`` stays ``m²``); comparison keys are derived separately.
* ``raw_value`` is always the text as extracted (never stripped); ``None`` only for cells that
  did not exist in the source.
* ``extraction_confidence`` is copied from engines that report one (PDF/OCR) and stays ``None``
  for verbatim digital sources.
"""

from __future__ import annotations

import unicodedata

from app.models.dataset import Cell, FormulaInfo
from app.models.source import SourceLocation
from app.models.values import (
    CellValue,
    DataType,
    ErrorValue,
    NumberValue,
    ParseStatus,
    TextValue,
    ValueMarker,
)

UNAVAILABLE_NOTE = "Formula has no cached result; formulas are never evaluated."


def is_blank(text: str | None) -> bool:
    """True for ``None`` and for text made only of whitespace or invisible format characters."""
    if text is None:
        return True
    return all(ch.isspace() or unicodedata.category(ch) == "Cf" for ch in text)


def normalize_text(text: str) -> str:
    """Collapsed text: NFC, whitespace runs to one space, stripped (``'a\\u00a0 b '`` gives
    ``'a b'``)."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _cell(
    *,
    raw: str | None,
    data_type: DataType,
    status: ParseStatus,
    source: SourceLocation,
    parsed: CellValue | None = None,
    normalized: CellValue | None = None,
    note: str | None = None,
    formula: FormulaInfo | None = None,
    number_format: str | None = None,
    confidence: float | None = None,
    marker: ValueMarker | None = None,
) -> Cell:
    return Cell(
        raw_value=raw,
        parsed_value=parsed,
        normalized_value=normalized,
        data_type=data_type,
        parse_status=status,
        parse_note=note,
        formula=formula,
        number_format=number_format,
        source=source,
        extraction_confidence=confidence,
        marker=marker,
    )


def empty_cell(
    source: SourceLocation,
    *,
    raw: str | None = None,
    formula: FormulaInfo | None = None,
    number_format: str | None = None,
    confidence: float | None = None,
) -> Cell:
    """A missing cell, or one whose text is blank (``raw`` keeps that text)."""
    return _cell(
        raw=raw,
        data_type=DataType.EMPTY,
        status=ParseStatus.NOT_APPLICABLE,
        source=source,
        formula=formula,
        number_format=number_format,
        confidence=confidence,
    )


def text_cell(
    raw: str,
    source: SourceLocation,
    *,
    formula: FormulaInfo | None = None,
    number_format: str | None = None,
    confidence: float | None = None,
) -> Cell:
    """Plain text: parsed value is the raw text, normalized value the collapsed text."""
    if is_blank(raw):
        return empty_cell(
            source, raw=raw, formula=formula, number_format=number_format, confidence=confidence
        )
    return _cell(
        raw=raw,
        data_type=DataType.TEXT,
        status=ParseStatus.NOT_APPLICABLE,
        source=source,
        parsed=TextValue(value=raw),
        normalized=TextValue(value=normalize_text(raw)),
        formula=formula,
        number_format=number_format,
        confidence=confidence,
    )


def unit_cell(
    raw: str,
    source: SourceLocation,
    unit_id: str | None,
    *,
    formula: FormulaInfo | None = None,
    confidence: float | None = None,
) -> Cell:
    """Unit text: normalized value is the canonical ``unit_id`` when the catalogue (or a
    reviewer's unit alias) resolved it, else the collapsed text."""
    if is_blank(raw):
        return empty_cell(source, raw=raw, formula=formula, confidence=confidence)
    return _cell(
        raw=raw,
        data_type=DataType.TEXT,
        status=ParseStatus.NOT_APPLICABLE,
        source=source,
        parsed=TextValue(value=raw),
        normalized=TextValue(value=unit_id if unit_id else normalize_text(raw)),
        formula=formula,
        confidence=confidence,
    )


def number_cell(
    value: NumberValue,
    source: SourceLocation,
    *,
    raw: str | None,
    status: ParseStatus = ParseStatus.EXACT,
    note: str | None = None,
    formula: FormulaInfo | None = None,
    number_format: str | None = None,
    confidence: float | None = None,
) -> Cell:
    """A number read exactly or by documented inference (``status`` ``exact`` / ``inferred``)."""
    if status not in (ParseStatus.EXACT, ParseStatus.INFERRED):
        raise ValueError("number cells are exact or inferred")
    return _cell(
        raw=raw,
        data_type=DataType.NUMBER,
        status=status,
        source=source,
        parsed=value,
        normalized=value,
        note=note,
        formula=formula,
        number_format=number_format,
        confidence=confidence,
    )


def typed_cell(
    value: CellValue,
    data_type: DataType,
    source: SourceLocation,
    *,
    raw: str | None,
    status: ParseStatus = ParseStatus.EXACT,
    note: str | None = None,
    formula: FormulaInfo | None = None,
    number_format: str | None = None,
    confidence: float | None = None,
) -> Cell:
    """A boolean, date or datetime value (typed source value or parsed text)."""
    if data_type not in (DataType.BOOLEAN, DataType.DATE, DataType.DATETIME):
        raise ValueError("typed_cell is for boolean, date and datetime values")
    return _cell(
        raw=raw,
        data_type=data_type,
        status=status,
        source=source,
        parsed=value,
        normalized=value,
        note=note,
        formula=formula,
        number_format=number_format,
        confidence=confidence,
    )


def failed_cell(
    raw: str,
    source: SourceLocation,
    note: str,
    *,
    formula: FormulaInfo | None = None,
    number_format: str | None = None,
    confidence: float | None = None,
) -> Cell:
    """Text in a typed (numeric/date) field that could not be read as that type."""
    return _cell(
        raw=raw,
        data_type=DataType.TEXT,
        status=ParseStatus.FAILED,
        source=source,
        parsed=TextValue(value=raw),
        normalized=TextValue(value=normalize_text(raw)),
        note=note,
        formula=formula,
        number_format=number_format,
        confidence=confidence,
    )


def marker_cell(
    raw: str,
    source: SourceLocation,
    marker: ValueMarker,
    *,
    note: str | None = None,
    formula: FormulaInfo | None = None,
    confidence: float | None = None,
) -> Cell:
    """A conventional token ("Incl.", "entfällt", "psch") in a numeric field: no number is
    invented; ``marker`` carries its meaning."""
    return _cell(
        raw=raw,
        data_type=DataType.TEXT,
        status=ParseStatus.MARKER,
        source=source,
        parsed=TextValue(value=raw),
        normalized=TextValue(value=normalize_text(raw)),
        note=note,
        formula=formula,
        confidence=confidence,
        marker=marker,
    )


def ambiguous_cell(
    raw: str,
    source: SourceLocation,
    note: str,
    *,
    formula: FormulaInfo | None = None,
    number_format: str | None = None,
    confidence: float | None = None,
) -> Cell:
    """Several readings remained (e.g. ``1.234``): no value is chosen."""
    return _cell(
        raw=raw,
        data_type=DataType.UNKNOWN,
        status=ParseStatus.AMBIGUOUS,
        source=source,
        note=note,
        formula=formula,
        number_format=number_format,
        confidence=confidence,
    )


def error_cell(
    code: str,
    source: SourceLocation,
    *,
    raw: str | None = None,
    formula: FormulaInfo | None = None,
    confidence: float | None = None,
) -> Cell:
    """A spreadsheet error literal such as ``#REF!`` (the spreadsheet's own cached result)."""
    value = ErrorValue(code=code)
    return _cell(
        raw=raw if raw is not None else code,
        data_type=DataType.ERROR,
        status=ParseStatus.EXACT,
        source=source,
        parsed=value,
        normalized=value,
        formula=formula,
        confidence=confidence,
    )


def unavailable_cell(
    source: SourceLocation,
    formula: FormulaInfo,
    *,
    raw: str | None = None,
    number_format: str | None = None,
) -> Cell:
    """A formula whose result the file does not store (formulas are never evaluated)."""
    return _cell(
        raw=raw,
        data_type=DataType.UNKNOWN,
        status=ParseStatus.UNAVAILABLE,
        source=source,
        note=UNAVAILABLE_NOTE,
        formula=formula,
        number_format=number_format,
    )
