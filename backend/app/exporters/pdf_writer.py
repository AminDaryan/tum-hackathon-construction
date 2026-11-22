"""A small PDF writer for the findings reports: A4 landscape pages of text in Helvetica and
Helvetica-Bold (two of the 14 standard PDF fonts every reader has, so nothing is embedded), with
headings, paragraphs and a table whose header repeats on every page.

Text is written in WinAnsiEncoding (Windows-1252: German letters, €, typographic quotes and
dashes); a character outside it is written as ``?``. Lines are wrapped with the fonts' glyph
widths below, taken from Adobe's Helvetica AFM files, which may be used, copied and distributed
for any purpose.

Deterministic: the same content and creation time give byte-identical files.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Glyph widths (1/1000 of the font size) of the characters 32 to 255 in WinAnsiEncoding.
# fmt: off
_HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667,
    611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
    667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500,
    222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
    350, 556, 350, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350, 350,
    222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 350, 500, 667, 278, 333, 556, 556,
    556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 556, 537,
    278, 333, 333, 365, 556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667, 1000, 722, 667, 667,
    667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722,
    667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500
)
_HELVETICA_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667,
    611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
    667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556,
    278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
    350, 556, 350, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350, 350,
    278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 350, 500, 667, 278, 333, 556, 556,
    556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 611, 556,
    278, 333, 333, 365, 556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000, 722, 667, 667,
    667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722,
    667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
    611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556
)
# fmt: on

PAGE_WIDTH = 842.0  # A4 landscape, in points
PAGE_HEIGHT = 595.0
MARGIN = 40.0
_BOTTOM = MARGIN + 14.0  # room for the page number
_CELL_PAD = 4.0
_RULE_GREY = "0.8 0.82 0.85"
_HEADER_FILL = "0.87 0.89 0.92"


def _font(name: bytes) -> bytes:
    return b"<< /Type /Font /Subtype /Type1 /BaseFont /" + name + b" /Encoding /WinAnsiEncoding >>"


def _encode(text: str) -> bytes:
    return text.encode("cp1252", errors="replace")


def text_width(text: str, size: float, *, bold: bool = False) -> float:
    """The width of ``text`` in points at ``size``."""
    widths = _HELVETICA_BOLD if bold else _HELVETICA
    return sum(widths[byte - 32] if byte >= 32 else 0 for byte in _encode(text)) * size / 1000


def wrap(text: str, size: float, width: float, *, bold: bool = False) -> list[str]:
    """``text`` broken into lines no wider than ``width``: at spaces, and inside a word only
    when the word alone is wider. Line breaks in ``text`` are kept."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if text_width(candidate, size, bold=bold) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            for char in word:
                if line and text_width(line + char, size, bold=bold) > width:
                    lines.append(line)
                    line = ""
                line += char
        lines.append(line)
    return lines


@dataclass(frozen=True, slots=True)
class Column:
    title: str
    width: float  # in points


@dataclass(frozen=True, slots=True)
class Cell:
    """One cell: lines of text, the first one bold when ``bold_first``."""

    text: str
    bold_first_line: bool = False
    detail: str = ""  # a second paragraph under the text, in regular weight


@dataclass(slots=True)
class PdfDocument:
    """Pages built top to bottom. ``heading``, ``paragraph`` and ``table`` add content at the
    cursor and start a new page when it does not fit."""

    title: str
    created_at: datetime
    pages: list[list[str]] = field(default_factory=list)
    _y: float = 0.0

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        self._new_page()

    # ------------------------------------------------------------------ layout
    def _new_page(self) -> None:
        self.pages.append([])
        self._y = PAGE_HEIGHT - MARGIN

    def _room(self, height: float) -> bool:
        return self._y - height >= _BOTTOM

    def _ensure(self, height: float) -> None:
        if not self._room(height):
            self._new_page()

    def _text(self, x: float, y: float, text: str, size: float, *, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.pages[-1].append(
            f"BT /{font} {size:g} Tf {x:.2f} {y:.2f} Td <{_encode(text).hex()}> Tj ET"
        )

    def _rule(self, x1: float, y: float, x2: float) -> None:
        self.pages[-1].append(f"{_RULE_GREY} RG 0.5 w {x1:.2f} {y:.2f} m {x2:.2f} {y:.2f} l S")

    def _fill(self, x: float, y: float, width: float, height: float) -> None:
        self.pages[-1].append(
            f"{_HEADER_FILL} rg {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f 0 g"
        )

    # ------------------------------------------------------------------ content
    def heading(self, text: str, size: float = 13.0) -> None:
        lines = wrap(text, size, PAGE_WIDTH - 2 * MARGIN, bold=True)
        leading = size * 1.3
        self._ensure(len(lines) * leading + 6)
        self._y -= 4
        for line in lines:
            self._y -= leading
            self._text(MARGIN, self._y + size * 0.25, line, size, bold=True)
        self._y -= 4

    def paragraph(self, text: str, size: float = 9.5) -> None:
        leading = size * 1.35
        for line in wrap(text, size, PAGE_WIDTH - 2 * MARGIN):
            self._ensure(leading)
            self._y -= leading
            self._text(MARGIN, self._y + size * 0.25, line, size)
        self._y -= 4

    def space(self, height: float) -> None:
        self._y -= height

    def table(
        self, columns: Sequence[Column], rows: Sequence[Sequence[Cell]], size: float = 8.5
    ) -> None:
        """A table with ``columns``; the header row repeats at the top of every page it spans.
        A row never splits across pages (a row taller than a page is cut)."""
        leading = size * 1.3
        header_height = leading + 2 * _CELL_PAD
        right = MARGIN + sum(column.width for column in columns)

        def header() -> None:
            self._fill(MARGIN, self._y - header_height, right - MARGIN, header_height)
            x = MARGIN
            for column in columns:
                self._text(
                    x + _CELL_PAD,
                    self._y - _CELL_PAD - leading + size * 0.3,
                    column.title,
                    size,
                    bold=True,
                )
                x += column.width
            self._y -= header_height

        def cell_lines(cell: Cell, width: float) -> list[tuple[str, bool]]:
            inner = width - 2 * _CELL_PAD
            first = wrap(cell.text, size, inner, bold=cell.bold_first_line)
            lines = [(line, cell.bold_first_line) for line in first]
            if cell.detail:
                lines += [(line, False) for line in wrap(cell.detail, size, inner)]
            return lines

        self._ensure(header_height + leading + 2 * _CELL_PAD)
        header()
        most = int((PAGE_HEIGHT - MARGIN - _BOTTOM - header_height - 2 * _CELL_PAD) // leading)
        for row in rows:
            laid = [
                cell_lines(cell, column.width)[:most]
                for cell, column in zip(row, columns, strict=True)
            ]
            height = max(len(lines) for lines in laid) * leading + 2 * _CELL_PAD
            if not self._room(height):
                self._new_page()
                header()
            x = MARGIN
            for lines, column in zip(laid, columns, strict=True):
                y = self._y - _CELL_PAD
                for line, bold in lines:
                    y -= leading
                    self._text(x + _CELL_PAD, y + size * 0.3, line, size, bold=bold)
                x += column.width
            self._y -= height
            self._rule(MARGIN, self._y, right)
        self._y -= 8

    # ------------------------------------------------------------------ output
    def render(self) -> bytes:
        """The PDF file: every page numbered "Page n of m" at its foot."""
        total = len(self.pages)
        objects: list[bytes] = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"",  # the page tree, filled in once the page objects are numbered
            _font(b"Helvetica"),
            _font(b"Helvetica-Bold"),
        ]
        page_ids: list[int] = []
        for number, operations in enumerate(self.pages, start=1):
            footer = f"Page {number} of {total}"
            size = 8.0
            x = PAGE_WIDTH - MARGIN - text_width(footer, size)
            ops = [*operations, "0.45 g"]
            ops.append(
                f"BT /F1 {size:g} Tf {x:.2f} {MARGIN - 4:.2f} Td <{_encode(footer).hex()}> Tj ET"
            )
            stream = "\n".join(ops).encode("ascii")
            objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            content_id = len(objects)
            objects.append(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
                % (int(PAGE_WIDTH), int(PAGE_HEIGHT), content_id)
            )
            page_ids.append(len(objects))
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {total} >>".encode("ascii")
        stamp = self.created_at.astimezone(UTC).strftime("D:%Y%m%d%H%M%SZ")
        objects.append(
            b"<< /Title <"
            + b"feff"
            + self.title.encode("utf-16-be").hex().encode("ascii")
            + b"> /Producer (Desvio) /CreationDate ("
            + stamp.encode("ascii")
            + b") >>"
        )
        info_id = len(objects)

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for offset in offsets:
            out += b"%010d 00000 n \n" % offset
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1,
            info_id,
            xref,
        )
        return bytes(out)
