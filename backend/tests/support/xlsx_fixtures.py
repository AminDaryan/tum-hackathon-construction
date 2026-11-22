"""XLSX test files: workbooks written with openpyxl, cached formula results (which openpyxl
cannot write), and hostile archives for the upload and extraction safety checks.

Every helper writes to ``path`` and returns it, so they compose with pytest's ``tmp_path``::

    book = write_xlsx(tmp_path / "lv.xlsx", {"LV": [["Qty", "Rate", "Amount"], [2, 3.5, "=A2*B2"]]})
    inject_cached_values(book, {("LV", "C2"): 7})

Hostile builders start from a valid workbook, so a file is rejected for the one property under
test. They only produce small files; limits are lowered in tests where a property needs size.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from openpyxl import Workbook

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_FIRST_SHEET = "xl/worksheets/sheet1.xml"
EXCEL_FULL_RANGE = "A1:XFD1048576"  # every cell of a sheet: 17,179,869,184 cells

PartTransform = Callable[[str, bytes], bytes | None]  # (name, data) -> new data, None = drop


OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # compound file: encrypted package or .xls


@dataclass(frozen=True)
class CachedError:
    """A cached error result such as ``#DIV/0!`` for :func:`inject_cached_values`."""

    code: str


@dataclass(frozen=True)
class CachedNumberText:
    """A cached number written verbatim into ``<v>``, e.g. ``"1E999"``, which overflows to
    infinity when parsed (Python's ``str(float("inf"))`` would not parse at all)."""

    text: str


# --------------------------------------------------------------------------- valid workbooks
def write_xlsx(
    path: Path,
    sheets: Mapping[str, Sequence[Sequence[Any]]],
    *,
    number_formats: Mapping[tuple[str, str], str] | None = None,
    merged: Mapping[str, Iterable[str]] | None = None,
    hidden: Iterable[str] = (),
    very_hidden: Iterable[str] = (),
    hidden_rows: Mapping[str, Iterable[int]] | None = None,
    hidden_columns: Mapping[str, Iterable[str]] | None = None,
    outline_levels: Mapping[str, Mapping[int, int]] | None = None,
) -> Path:
    """Write a workbook with openpyxl: one sheet per entry of ``sheets``, in order, rows given
    as lists (``None`` leaves a cell empty; strings starting with ``=`` become formulas).

    ``number_formats`` maps ``(sheet, "B2")`` to a format; setting one on an otherwise empty
    cell creates a styled empty cell, which inflates the sheet dimension. ``merged`` maps a
    sheet to ranges such as ``"A1:C1"``. ``hidden`` and ``very_hidden`` set sheet states;
    ``hidden_rows`` maps a sheet to row numbers, ``hidden_columns`` to columns or column ranges
    (``"C"``, ``"B:D"``; a range becomes one ``<col min max>`` element) and ``outline_levels``
    to ``{row: level}``. Formula cells carry no cached results; add them with
    :func:`inject_cached_values`.
    """
    if not sheets:
        raise ValueError("a workbook needs at least one sheet")
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        for row_number, row in enumerate(rows, start=1):
            for column_number, value in enumerate(row, start=1):
                if value is not None:
                    worksheet.cell(row=row_number, column=column_number, value=value)
    for (title, coordinate), number_format in (number_formats or {}).items():
        workbook[title][coordinate].number_format = number_format
    for title, ranges in (merged or {}).items():
        for cell_range in ranges:
            workbook[title].merge_cells(cell_range)
    for title in hidden:
        workbook[title].sheet_state = "hidden"
    for title in very_hidden:
        workbook[title].sheet_state = "veryHidden"
    _set_row_and_column_visibility(workbook, hidden_rows, hidden_columns, outline_levels)
    workbook.save(path)
    return path


def _set_row_and_column_visibility(
    workbook: Workbook,
    hidden_rows: Mapping[str, Iterable[int]] | None,
    hidden_columns: Mapping[str, Iterable[str]] | None,
    outline_levels: Mapping[str, Mapping[int, int]] | None,
) -> None:
    for title, rows in (hidden_rows or {}).items():
        for row in rows:
            workbook[title].row_dimensions[row].hidden = True
    for title, columns in (hidden_columns or {}).items():
        for column in columns:
            first, _, last = column.partition(":")
            workbook[title].column_dimensions.group(first, last or first, hidden=True)
    for title, levels in (outline_levels or {}).items():
        for row, level in levels.items():
            workbook[title].row_dimensions[row].outline_level = level


def write_sheet_xml(
    path: Path, rows_xml: str, *, before_sheet_data: str = "", sheet: str = "Sheet1"
) -> Path:
    """A workbook whose only sheet is exactly ``<worksheet>before_sheet_data<sheetData>rows_xml
    </sheetData></worksheet>``: for XML that openpyxl would never write (``<cols>``,
    ``<sheetFormatPr>``, ``<dimension>``, rows without coordinates, verbatim values)."""
    xml = (
        f'<worksheet xmlns="{MAIN_NS}">{before_sheet_data}<sheetData>{rows_xml}</sheetData>'
        "</worksheet>"
    )
    book = write_xlsx(path, {sheet: [["placeholder"]]})
    return replace_part(book, _FIRST_SHEET, xml.encode())


def inject_cached_values(path: Path, values: Mapping[tuple[str, str], Any]) -> Path:
    """Store cached results for formula cells, keyed by ``(sheet name, "C2")``, as Excel does
    after a recalculation. Values: numbers, ``bool``, ``str`` or :class:`CachedError`.

    openpyxl cannot write cached results, so the saved sheet XML is rewritten in the archive.
    """
    by_part: dict[str, dict[str, Any]] = {}
    for (sheet, coordinate), value in values.items():
        by_part.setdefault(sheet_part_name(path, sheet), {})[coordinate] = value

    def transform(name: str, data: bytes) -> bytes:
        return _with_cached_values(data, by_part[name]) if name in by_part else data

    return rewrite_parts(path, transform)


def sheet_part_name(path: Path, sheet: str) -> str:
    """Archive name of the XML part that holds ``sheet`` (resolved through the relationships)."""
    with zipfile.ZipFile(path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.get("Id"): rel.get("Target", "") for rel in rels.iter(f"{{{_PKG_REL_NS}}}Relationship")
    }
    for element in workbook.iter(f"{{{MAIN_NS}}}sheet"):
        if element.get("name") == sheet:
            target = targets[element.get(f"{{{_DOC_REL_NS}}}id")]
            return target[1:] if target.startswith("/") else f"xl/{target}"
    raise KeyError(sheet)


def _with_cached_values(data: bytes, values: Mapping[str, Any]) -> bytes:
    root = ElementTree.fromstring(data)
    pending = dict(values)
    for cell in root.iter(f"{{{MAIN_NS}}}c"):
        coordinate = cell.get("r")
        if coordinate not in pending:
            continue
        if cell.find(f"{{{MAIN_NS}}}f") is None:
            raise ValueError(f"{coordinate} is not a formula cell")
        cell_type, text = _cached_representation(pending.pop(coordinate))
        if cell_type is None:
            cell.attrib.pop("t", None)
        else:
            cell.set("t", cell_type)
        value = cell.find(f"{{{MAIN_NS}}}v")
        if value is None:
            value = ElementTree.SubElement(cell, f"{{{MAIN_NS}}}v")
        value.text = text
    if pending:
        raise KeyError(f"no cells {sorted(pending)}")
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _cached_representation(value: Any) -> tuple[str | None, str]:
    """(cell type attribute, <v> text) of a cached result."""
    if isinstance(value, CachedError):
        return "e", value.code
    if isinstance(value, CachedNumberText):
        return None, value.text
    if isinstance(value, bool):
        return "b", "1" if value else "0"
    if isinstance(value, int | float | Decimal):
        return None, str(value)
    if isinstance(value, str):
        return "str", value
    raise TypeError(f"unsupported cached value {value!r}")


# --------------------------------------------------------------------------- archive editing
def rewrite_parts(
    path: Path,
    transform: PartTransform | None = None,
    *,
    extra: Iterable[tuple[str, bytes]] = (),
    after_write: Callable[[zipfile.ZipFile], None] | None = None,
) -> Path:
    """Rewrite the archive: ``transform`` may change or drop (``None``) each part, ``extra``
    parts are appended, and ``after_write`` may edit the written entries' ``ZipInfo`` (the
    central directory is written from them when the archive closes)."""
    with zipfile.ZipFile(path) as source:
        parts = [(info.filename, source.read(info)) for info in source.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in parts:
            new = transform(name, data) if transform else data
            if new is not None:
                target.writestr(name, new)
        for name, data in extra:
            target.writestr(name, data)
        if after_write is not None:
            after_write(target)
    return path


def replace_part(path: Path, name: str, data: bytes) -> Path:
    """Replace one archive part by ``data``."""
    return rewrite_parts(path, lambda part, old: data if part == name else old)


def append_to_first_sheet(path: Path, fragment: bytes) -> Path:
    """Insert raw XML right after ``</sheetData>`` of the first sheet (e.g. ``<mergeCells>``)."""

    def transform(name: str, data: bytes) -> bytes:
        return (
            data.replace(b"</sheetData>", b"</sheetData>" + fragment, 1)
            if name == _FIRST_SHEET
            else data
        )

    return rewrite_parts(path, transform)


def _base_workbook(path: Path) -> Path:
    return write_xlsx(path, {"Sheet1": [["value"], [1]]})


# --------------------------------------------------------------------------- hostile archives
def write_zip_bomb(path: Path, *, uncompressed_bytes: int = 8 * 1024 * 1024) -> Path:
    """A workbook plus one entry of zeros compressing about 1000:1 (the limit is 200:1)."""
    return rewrite_parts(
        _base_workbook(path), extra=[("xl/media/padding.bin", bytes(uncompressed_bytes))]
    )


def write_many_entries(path: Path, count: int) -> Path:
    """A workbook plus ``count`` tiny extra entries."""
    extra = [(f"customXml/item{number}.xml", b"<item/>") for number in range(count)]
    return rewrite_parts(_base_workbook(path), extra=extra)


def write_hostile_entry_name(path: Path, name: str) -> Path:
    """A workbook plus an entry whose name in the central directory is exactly ``name``, e.g.
    ``../evil.xml``, ``/etc/evil.xml``, ``xl\\evil.xml`` or ``xl/evil\\x00.xml``.

    zipfile truncates names at NUL and (on Windows) converts backslashes when writing, so the
    entry is written under a placeholder and renamed in the central directory record only.
    """
    placeholder = "xl/placeholder-entry.xml"

    def rename(archive: zipfile.ZipFile) -> None:
        info = archive.getinfo(placeholder)
        info.filename = name
        info.orig_filename = name

    return rewrite_parts(_base_workbook(path), extra=[(placeholder, b"<x/>")], after_write=rename)


def write_encrypted_entry(path: Path, part: str = _FIRST_SHEET) -> Path:
    """A workbook whose ``part`` has the "encrypted" flag (bit 0) set in the central directory."""

    def flag(archive: zipfile.ZipFile) -> None:
        archive.getinfo(part).flag_bits |= 0x1

    return rewrite_parts(_base_workbook(path), after_write=flag)


def write_missing_part(path: Path, part: str) -> Path:
    """A workbook without ``part`` (e.g. ``[Content_Types].xml`` or ``xl/workbook.xml``)."""
    return rewrite_parts(_base_workbook(path), lambda name, data: None if name == part else data)


def _entity_chain(levels: int) -> str:
    """``lol0`` = "lol" and each further level ten references to the previous one."""
    declarations = ['<!ENTITY lol0 "lol">']
    for level in range(1, levels + 1):
        reference = f"&lol{level - 1};"
        declarations.append(f'<!ENTITY lol{level} "{reference * 10}">')
    return "\n".join(declarations)


BILLION_LAUGHS = (
    f'<?xml version="1.0"?>\n<!DOCTYPE worksheet [\n{_entity_chain(9)}\n]>\n'
    f'<worksheet xmlns="{MAIN_NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>'
    "&lol9;</t></is></c></row></sheetData></worksheet>"
).encode()

EXTERNAL_ENTITY = (
    b'<?xml version="1.0"?>\n<!DOCTYPE worksheet [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
    + f'<worksheet xmlns="{MAIN_NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>'
    "&xxe;</t></is></c></row></sheetData></worksheet>".encode()
)


def write_billion_laughs(path: Path, part: str = _FIRST_SHEET) -> Path:
    """A workbook whose ``part`` is the classic exponential entity expansion (10^9 "lol")."""
    return replace_part(_base_workbook(path), part, BILLION_LAUGHS)


def write_external_entity(path: Path, part: str = _FIRST_SHEET) -> Path:
    """A workbook whose ``part`` references a local file through an external entity (XXE)."""
    return replace_part(_base_workbook(path), part, EXTERNAL_ENTITY)


def write_range_bomb(path: Path, kind: str, ref: str = EXCEL_FULL_RANGE) -> Path:
    """A tiny workbook that makes openpyxl create one object per cell of ``ref``:
    ``kind`` is ``"merge"`` (merged range), ``"hyperlink"`` or ``"comment"`` (a comments part,
    linked from the first sheet, with a range reference). With the default ``ref`` and without
    the pre-parse scan, loading it never finishes."""
    book = _base_workbook(path)
    if kind == "merge":
        return append_to_first_sheet(
            book, f'<mergeCells count="1"><mergeCell ref="{ref}"/></mergeCells>'.encode()
        )
    if kind == "hyperlink":
        fragment = f'<hyperlinks><hyperlink ref="{ref}" location="Sheet1!A1"/></hyperlinks>'
        return append_to_first_sheet(book, fragment.encode())
    if kind == "comment":
        comments = (
            f'<comments xmlns="{MAIN_NS}"><authors><author>x</author></authors><commentList>'
            f'<comment ref="{ref}" authorId="0"><text><t>x</t></text></comment>'
            "</commentList></comments>"
        )
        # openpyxl only reads a comments part that the sheet's relationships point to.
        rels = (
            f'<Relationships xmlns="{_PKG_REL_NS}"><Relationship Id="rId1" '
            f'Type="{_DOC_REL_NS}/comments" Target="../comments1.xml"/></Relationships>'
        )
        extra = [
            ("xl/comments1.xml", comments.encode()),
            ("xl/worksheets/_rels/sheet1.xml.rels", rels.encode()),
        ]
        return rewrite_parts(book, extra=extra)
    raise ValueError(f"unknown range bomb kind {kind!r}")


def write_padded_sheet(path: Path, padding_bytes: int) -> Path:
    """A workbook whose first sheet is well-formed XML padded with ``padding_bytes`` spaces: an
    XML "zip bomb" that decompresses far beyond its size and that every XML parser must read."""
    sheet = f'<worksheet xmlns="{MAIN_NS}"><sheetData/>{" " * padding_bytes}</worksheet>'
    return replace_part(_base_workbook(path), _FIRST_SHEET, sheet.encode())


def write_shared_formula_bomb(path: Path, *, formula_chars: int, dependents: int) -> Path:
    """A sheet whose cell A1 holds a shared formula of about ``formula_chars`` characters that
    ``dependents`` further cells reuse; openpyxl re-creates the full text for each of them."""
    terms = max(1, formula_chars // 6)
    formula = "+".join(f"B{number}" for number in range(1, terms + 1))
    cells = [f'<c r="A1"><f t="shared" ref="A1:A{dependents + 1}" si="0">{formula}</f></c>']
    cells += [f'<c r="A{row}"><f t="shared" si="0"/></c>' for row in range(2, dependents + 2)]
    rows = "".join(f'<row r="{number}">{cell}</row>' for number, cell in enumerate(cells, start=1))
    sheet = f'<worksheet xmlns="{MAIN_NS}"><sheetData>{rows}</sheetData></worksheet>'
    return replace_part(_base_workbook(path), _FIRST_SHEET, sheet.encode())


def write_formatted_rows(path: Path, count: int) -> Path:
    """A sheet of ``count`` empty ``<row>`` elements that each carry a height: no cell, but one
    row-dimension object per row in openpyxl."""
    rows = "".join(
        f'<row r="{number}" ht="20" customHeight="1"/>' for number in range(1, count + 1)
    )
    return write_sheet_xml(path, rows)


_SHARED_STRINGS_PART = "xl/sharedStrings.xml"
_SHARED_STRINGS_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
)


def write_shared_strings(path: Path, items_xml: str) -> Path:
    """A workbook with a shared string table of exactly the ``<si>`` items ``items_xml``; the
    first sheet's A1 refers to item 0. (openpyxl writes inline strings, so the table, and its
    content-type entry, through which openpyxl finds it, are added here.)"""
    book = write_sheet_xml(path, '<row r="1"><c r="A1" t="s"><v>0</v></c></row>')
    override = (
        f'<Override PartName="/{_SHARED_STRINGS_PART}" ContentType="{_SHARED_STRINGS_TYPE}"/>'
    )

    def register(name: str, data: bytes) -> bytes:
        if name != "[Content_Types].xml":
            return data
        return data.replace(b"</Types>", override.encode() + b"</Types>", 1)

    table = f'<sst xmlns="{MAIN_NS}">{items_xml}</sst>'
    return rewrite_parts(book, register, extra=[(_SHARED_STRINGS_PART, table.encode())])


def write_undefined_number_format(path: Path) -> Path:
    """A workbook whose cell A1 uses a style that points at number format 999, which the style
    sheet does not define (openpyxl raises ``IndexError`` when the format is read)."""
    book = write_xlsx(path, {"Sheet1": [[1.5, 2]]}, number_formats={("Sheet1", "A1"): "0.000"})

    def transform(name: str, data: bytes) -> bytes:
        if name != "xl/styles.xml":
            return data
        broken = data.replace(b'numFmtId="164" fontId', b'numFmtId="999" fontId')
        if broken == data:
            raise ValueError("the style sheet layout changed; the fixture needs an update")
        return broken

    return rewrite_parts(book, transform)


def write_ole2_container(path: Path) -> Path:
    """The start of an OLE2 compound file, as Excel writes for a password-protected workbook
    (the ``EncryptedPackage`` stream) and for legacy ``.xls`` files."""
    path.write_bytes(OLE2_SIGNATURE + bytes(504) + "EncryptedPackage".encode("utf-16-le") * 32)
    return path
