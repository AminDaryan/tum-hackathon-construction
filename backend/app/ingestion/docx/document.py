"""The body of a Word document (.docx, WordprocessingML): its paragraphs and tables, in order.

Read: ``word/document.xml`` (the text), ``word/styles.xml`` (which paragraph styles are
headings) and ``word/numbering.xml`` (which paragraphs Word numbers automatically). Nothing else
is opened: no macros, embedded or linked objects, headers, footers, footnotes or comments. The
container was checked before (:func:`app.ingestion.security.inspect_ooxml_container`); the XML
is parsed without DTDs, entity expansion or network access, and a DOCTYPE is refused.

Text is taken as Word shows it: runs inside hyperlinks, content controls, smart tags, fields
(their result, not their code) and tracked insertions; tabs become ``\\t`` and line breaks
``\\n``; tracked deletions are left out. Text boxes and drawings are not part of a paragraph's
text (they are counted, see :attr:`Body.text_boxes`).

Tables keep Word's grid: a cell spanning columns (``gridSpan``) or continued from the row above
(``vMerge``) becomes a merged range, and its text sits in its first cell. Rows and columns are
numbered from 1 as Word counts them, so a location names the row a reader finds in Word. A table
inside a cell is read as text of that cell (cells separated by tabs, rows by line breaks).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from app.core.errors import ExtractionError, UnsupportedFormatError
from app.ingestion.base import MergedRange

DOCUMENT_PART = "word/document.xml"
STYLES_PART = "word/styles.xml"
NUMBERING_PART = "word/numbering.xml"
# Transitional (what Word writes by default) and Strict Open XML.
_NAMESPACES = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
)
_HEADING_NAME = re.compile(r"^(?:heading|überschrift|berschrift|titre|titolo)\s*(\d)$", re.I)
_TITLE_NAMES = frozenset({"title", "titel"})
_NOT_NUMBERED = frozenset({"bullet", "none"})


@dataclass(frozen=True, slots=True)
class Paragraph:
    """A paragraph of the body (not of a table cell)."""

    number: int  # 1-based position among the body's paragraphs, empty ones included
    text: str
    heading_level: int | None = None  # 1 = top; from the paragraph's outline level or style
    auto_numbered: bool = False  # Word shows a number (1., a), I.) that is not in the text


@dataclass(slots=True)
class Table:
    """A table of the body, as a grid of cell texts (1-based rows and columns)."""

    number: int  # 1-based position among the body's tables
    cells: dict[tuple[int, int], str] = field(default_factory=dict)  # only non-empty cells
    merged: list[MergedRange] = field(default_factory=list)
    rows: int = 0
    columns: int = 0
    nested: int = 0  # tables inside its cells, read as text


@dataclass(slots=True)
class Body:
    paragraphs: list[Paragraph] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    text_boxes: int = 0  # text boxes and shapes with text: not read
    imported_parts: int = 0  # altChunk: content imported from another file, not read


def read_body(path: Path) -> Body:
    """Read the paragraphs and tables of the Word document at ``path``."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            document = _parse(archive, DOCUMENT_PART)
            styles = _parse(archive, STYLES_PART) if STYLES_PART in names else None
            numbering = _parse(archive, NUMBERING_PART) if NUMBERING_PART in names else None
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ExtractionError(
            "The Word document could not be read: its ZIP container or main part is damaged.",
            details={"reason": "docx_unreadable"},
        ) from exc
    root = document.getroot()
    namespace = etree.QName(root).namespace
    if namespace not in _NAMESPACES:
        raise UnsupportedFormatError(
            "The file is not a Word document: its main part is not WordprocessingML.",
            details={"reason": "docx_not_wordprocessingml"},
        )
    reader = _Reader(namespace, _heading_levels(styles, namespace), _numbered(numbering, namespace))
    body = root.find(reader.w("body"))
    if body is None:
        return Body()
    reader.blocks(body)
    reader.body.text_boxes = sum(1 for _ in root.iter(reader.w("txbxContent")))
    reader.body.imported_parts = sum(1 for _ in root.iter(reader.w("altChunk")))
    return reader.body


def _parse(archive: zipfile.ZipFile, name: str) -> Any:
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
    )
    try:
        with archive.open(name) as handle:
            tree = etree.parse(handle, parser)
    except etree.XMLSyntaxError as exc:
        raise ExtractionError(
            f"The Word document is damaged: {name} is not well-formed XML ({exc.msg}).",
            details={"reason": "docx_xml_malformed"},
        ) from None
    if tree.docinfo.doctype:
        raise UnsupportedFormatError(
            f"The Word document declares a DOCTYPE in {name}; Word writes none, and DOCTYPE "
            "declarations are refused for safety.",
            details={"reason": "xml_doctype"},
        )
    return tree


def _val(element: Any, namespace: str) -> str | None:
    if element is None:
        return None
    value = element.get(f"{{{namespace}}}val")
    return value if isinstance(value, str) else None


def _heading_levels(styles: Any, namespace: str) -> dict[str, int]:
    """Paragraph style id -> heading level: a style named "heading N" (Word's built-in
    headings, whatever the display language), "Title", or with an outline level, directly or
    through the style it is based on."""
    if styles is None:
        return {}
    ns = f"{{{namespace}}}"
    own: dict[str, int | None] = {}
    based_on: dict[str, str] = {}
    for style in styles.getroot().iter(f"{ns}style"):
        if style.get(f"{ns}type") != "paragraph":
            continue
        style_id = style.get(f"{ns}styleId")
        if not style_id:
            continue
        name = (_val(style.find(f"{ns}name"), namespace) or "").strip()
        level: int | None = None
        heading = _HEADING_NAME.match(name)
        outline = _val(style.find(f"{ns}pPr/{ns}outlineLvl"), namespace)
        if heading:
            level = int(heading.group(1))
        elif name.lower() in _TITLE_NAMES:
            level = 1
        elif outline is not None and outline.isdigit() and int(outline) < 9:
            level = int(outline) + 1
        own[style_id] = level
        parent = _val(style.find(f"{ns}basedOn"), namespace)
        if parent:
            based_on[style_id] = parent
    levels: dict[str, int] = {}
    for style_id in own:
        current: str | None = style_id
        seen: set[str] = set()
        while current is not None and current not in seen:
            seen.add(current)
            level = own.get(current)
            if level is not None:
                levels[style_id] = level
                break
            current = based_on.get(current)
    return levels


def _numbered(numbering: Any, namespace: str) -> set[tuple[str, str]]:
    """(numId, ilvl) pairs whose list level shows a number or letter, not a bullet."""
    if numbering is None:
        return set()
    ns = f"{{{namespace}}}"
    root = numbering.getroot()
    formats: dict[tuple[str, str], str] = {}
    for abstract in root.iter(f"{ns}abstractNum"):
        abstract_id = abstract.get(f"{ns}abstractNumId")
        for level in abstract.iter(f"{ns}lvl"):
            fmt = _val(level.find(f"{ns}numFmt"), namespace) or "decimal"
            formats[(abstract_id, level.get(f"{ns}ilvl") or "0")] = fmt
    numbered: set[tuple[str, str]] = set()
    for num in root.iter(f"{ns}num"):
        num_id = num.get(f"{ns}numId")
        abstract_id = _val(num.find(f"{ns}abstractNumId"), namespace)
        for (abstract, level), fmt in formats.items():
            if abstract == abstract_id and fmt not in _NOT_NUMBERED and num_id:
                numbered.add((num_id, level))
    return numbered


class _Reader:
    def __init__(
        self, namespace: str, headings: dict[str, int], numbered: set[tuple[str, str]]
    ) -> None:
        self.ns = f"{{{namespace}}}"
        self.namespace = namespace
        self.headings = headings
        self.numbered = numbered
        self.body = Body()
        self.paragraph_count = 0
        self.table_count = 0
        # Elements whose children carry a paragraph's visible text.
        self.containers = {
            self.w(tag)
            for tag in (
                "r",
                "hyperlink",
                "ins",
                "moveTo",
                "smartTag",
                "customXml",
                "fldSimple",
                "sdt",
                "sdtContent",
                "dir",
                "bdo",
            )
        }

    def w(self, tag: str) -> str:
        return f"{self.ns}{tag}"

    # ------------------------------------------------------------------ body
    def blocks(self, parent: Any) -> None:
        for child in parent:
            if child.tag == self.w("p"):
                self.body.paragraphs.append(self.paragraph(child))
            elif child.tag == self.w("tbl"):
                self.table_count += 1
                self.body.tables.append(self.table(child, self.table_count))
            elif child.tag in (self.w("sdt"), self.w("sdtContent"), self.w("customXml")):
                self.blocks(child)

    def paragraph(self, element: Any) -> Paragraph:
        self.paragraph_count += 1
        properties = element.find(self.w("pPr"))
        level: int | None = None
        auto = False
        if properties is not None:
            outline = _val(properties.find(self.w("outlineLvl")), self.namespace)
            style = _val(properties.find(self.w("pStyle")), self.namespace)
            if outline is not None and outline.isdigit() and int(outline) < 9:
                level = int(outline) + 1
            elif style is not None:
                level = self.headings.get(style)
            num = properties.find(self.w("numPr"))
            if num is not None:
                num_id = _val(num.find(self.w("numId")), self.namespace)
                ilvl = _val(num.find(self.w("ilvl")), self.namespace) or "0"
                auto = num_id not in (None, "0") and (num_id, ilvl) in self.numbered
        return Paragraph(self.paragraph_count, self.text(element), level, auto)

    def text(self, element: Any) -> str:
        parts: list[str] = []
        self._collect(element, parts)
        return "".join(parts)

    def _collect(self, element: Any, parts: list[str]) -> None:
        for child in element:
            tag = child.tag
            if tag == self.w("t"):
                parts.append(child.text or "")
            elif tag in (self.w("tab"), self.w("ptab")):
                parts.append("\t")
            elif tag in (self.w("br"), self.w("cr")):
                parts.append("\n")
            elif tag == self.w("noBreakHyphen"):
                parts.append("-")
            elif tag in self.containers:
                self._collect(child, parts)
            # pPr and rPr (tab stops, formatting), deletions, field codes, drawings and text
            # boxes, footnote and comment references: not text of the paragraph

    # ------------------------------------------------------------------ tables
    def table(self, element: Any, number: int) -> Table:
        table = Table(number)
        open_ranges: dict[int, list[int]] = {}  # first column -> [row0, col0, row1, col1]
        row = 0
        for tr in self._rows(element):
            row += 1
            column = 1 + self._int(tr.find(f"{self.w('trPr')}/{self.w('gridBefore')}"), 0)
            continued: set[int] = set()
            for tc in self._cells(tr):
                properties = tc.find(self.w("tcPr"))
                span = max(1, self._int(_find(properties, self.w("gridSpan")), 1))
                merge = _find(properties, self.w("vMerge"))
                restart = merge is not None and _val(merge, self.namespace) == "restart"
                text, nested = self.cell_text(tc)
                table.nested += nested
                if merge is not None and not restart and column in open_ranges:
                    open_ranges[column][2] = row  # continues the cell above
                    continued.add(column)
                    if text:  # Word keeps the text in the first cell; keep stray text too
                        table.cells[(row, column)] = text
                else:
                    if text:
                        table.cells[(row, column)] = text
                    if restart or span > 1:
                        self._close(open_ranges.pop(column, None), table)
                        open_ranges[column] = [row, column, row, column + span - 1]
                        continued.add(column)
                column += span
            table.columns = max(table.columns, column - 1)
            for start in [c for c in open_ranges if c not in continued]:
                self._close(open_ranges.pop(start), table)
        for bounds in open_ranges.values():
            self._close(bounds, table)
        table.rows = row
        return table

    def _rows(self, table: Any) -> list[Any]:
        rows: list[Any] = []
        for child in table:
            if child.tag == self.w("tr"):
                rows.append(child)
            elif child.tag in (self.w("sdt"), self.w("sdtContent"), self.w("customXml")):
                rows.extend(self._rows(child))
        return rows

    def _cells(self, row: Any) -> list[Any]:
        cells: list[Any] = []
        for child in row:
            if child.tag == self.w("tc"):
                cells.append(child)
            elif child.tag in (self.w("sdt"), self.w("sdtContent"), self.w("customXml")):
                cells.extend(self._cells(child))
        return cells

    def cell_text(self, cell: Any) -> tuple[str, int]:
        """The cell's paragraphs joined by line breaks; a nested table as tab-separated rows."""
        lines: list[str] = []
        nested = 0
        for child in cell:
            if child.tag == self.w("p"):
                lines.append(self.text(child))
            elif child.tag == self.w("tbl"):
                nested += 1
                for tr in self._rows(child):
                    values = [self.cell_text(tc)[0].replace("\n", " ") for tc in self._cells(tr)]
                    lines.append("\t".join(values))
            elif child.tag in (self.w("sdt"), self.w("sdtContent"), self.w("customXml")):
                inner, more = self.cell_text(child)
                nested += more
                if inner:
                    lines.append(inner)
        return "\n".join(lines).strip(), nested

    def _int(self, element: Any, default: int) -> int:
        value = _val(element, self.namespace)
        return int(value) if value is not None and value.isdigit() else default

    @staticmethod
    def _close(bounds: list[int] | None, table: Table) -> None:
        if bounds is None:
            return
        row0, col0, row1, col1 = bounds
        if row1 > row0 or col1 > col0:
            table.merged.append(MergedRange(row0, col0, row1, col1))


def _find(element: Any, tag: str) -> Any:
    return None if element is None else element.find(tag)
