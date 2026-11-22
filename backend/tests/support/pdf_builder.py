"""Write small PDFs with text at exact positions, for the PDF import tests.

No PDF library is needed: the file is plain PDF 1.4 with the standard fonts Helvetica and
Helvetica-Bold (WinAnsi encoding, so German umlauts work). Coordinates are points from the top
left of an A4 page, like the reader's. ``right`` places text by its right edge, as printed
bills align their numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

A4 = (595.0, 842.0)
# Helvetica advance widths (1/1000 em) for the characters numbers use; other characters are
# only placed by their left edge, so an average is enough for them.
_WIDTHS = {**dict.fromkeys("0123456789", 556), ".": 278, ",": 278, "-": 333, " ": 278}
_AVERAGE = 556


@dataclass
class PdfPage:
    texts: list[tuple[float, float, str, float, bool]] = field(default_factory=list)

    def text(self, x: float, top: float, text: str, *, size: float = 10, bold: bool = False):
        """``text`` with its left edge at ``x`` and its baseline ``top`` points from the top."""
        self.texts.append((x, top, text, size, bold))
        return self

    def right(self, x1: float, top: float, text: str, *, size: float = 10, bold: bool = False):
        """``text`` with its right edge at ``x1``."""
        width = sum(_WIDTHS.get(char, _AVERAGE) for char in text) * size / 1000
        return self.text(x1 - width, top, text, size=size, bold=bold)


def _literal(text: str) -> bytes:
    raw = text.encode("cp1252")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def build_pdf(pages: list[PdfPage]) -> bytes:
    """A PDF with one page per :class:`PdfPage` (an empty page has no text layer)."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in below
    pages_ref = add(b"")
    regular = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    bold = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    kids: list[int] = []
    for page in pages:
        stream = b"".join(
            b"BT /%s %.1f Tf %.2f %.2f Td %s Tj ET\n"
            % (b"F2" if is_bold else b"F1", size, x, A4[1] - top, _literal(text))
            for x, top, text, size, is_bold in page.texts
        )
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_ref, A4[0], A4[1], regular, bold, content)
            )
        )
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_ref
    objects[pages_ref - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % kid for kid in kids),
        len(kids),
    )
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        xref,
    )
    return bytes(out)


# --------------------------------------------------------------------------- a printed bill
# Column positions of the bill layout below (left edges, and right edges of numbers).
OZ_X, TEXT_X, QTY_RIGHT, UNIT_X, PRICE_RIGHT, TOTAL_RIGHT = 55, 125, 345, 352, 454, 536


def bill_header(page: PdfPage, number: int, *, project: str = "Testprojekt") -> PdfPage:
    page.text(250, 50, "Leistungsverzeichnis", size=12, bold=True)
    page.text(OZ_X, 80, "Projekt:", bold=True).text(TEXT_X, 80, project, bold=True)
    page.text(OZ_X, 92, "LV:", bold=True).text(TEXT_X, 92, "Erdarbeiten Testbau", bold=True)
    page.text(OZ_X, 115, "OZ", bold=True).text(TEXT_X, 115, "Leistungsbeschreibung", bold=True)
    page.text(315, 115, "Menge", bold=True).text(UNIT_X, 115, "ME", bold=True)
    page.text(392, 115, "Einheitspreis", bold=True).text(470, 115, "Gesamtbetrag", bold=True)
    page.text(422, 127, "in EUR", bold=True).text(504, 127, "in EUR", bold=True)
    page.text(OZ_X, 800, "Druckdatum: 20.11.2026").text(480, 800, f"Seite: {number}")
    return page


def item(
    page: PdfPage,
    top: float,
    oz: str,
    short: str,
    lines: list[str],
    qty: str,
    unit: str,
    price: str | None,
    total: str | None,
) -> float:
    """An item block in the layout of many AVA printouts: OZ and short text, long text, then
    the quantity line. Returns the top of the next block."""
    page.text(OZ_X, top, oz, size=8).text(TEXT_X, top, short, bold=True)
    for line in lines:
        top += 12
        page.text(TEXT_X, top, line)
    top += 20
    page.right(QTY_RIGHT, top, qty).text(UNIT_X, top, unit)
    page.right(PRICE_RIGHT, top, price) if price else page.text(
        386, top, "........................."
    )
    if total and total[0].isdigit():
        page.right(TOTAL_RIGHT, top, total)
    else:
        page.text(468, top, total or ".........................")
    return top + 25


def sample_bill() -> bytes:
    """Two pages, one category, four items (one 'Nur Einheitspreis'), net and gross totals.

    1.10  120,000 m2 x 4,50  = 540,00
    1.20   35,500 m3 x 18,20 = 646,10
    1.30   12,000 m2 x 3,10  =  37,20
    1.40    1,000 psch x 250,00 (Nur Einh.-Pr.)
    Summe 01: 1.223,30; netto 1.223,30; Gesamtsumme (19 % MwSt.) 1.455,73
    """
    cover = PdfPage().text(200, 300, "Aufforderung zur Abgabe eines Angebots", size=14)
    first = bill_header(PdfPage(), 2)
    first.text(OZ_X, 160, "01.", size=8).text(TEXT_X, 160, "Erdarbeiten", bold=True)
    top = item(
        first,
        190,
        "01.10.",
        "Oberboden abtragen",
        ["Oberboden abtragen und seitlich lagern.", "Dicke 20 cm"],
        "120,000",
        "m2",
        "4,50",
        "540,00",
    )
    top = item(
        first,
        top,
        "01.20.",
        "Boden ausheben",
        [
            "Boden der Bodenklasse 3 ausheben, laden und abfahren.",
            "Aushubtiefe bis 1,25 m, Böschungswinkel nach Wahl.",
        ],
        "35,500",
        "m3",
        "18,20",
        "646,10",
    )
    first.text(400, top, "Übertrag:").right(TOTAL_RIGHT, top, "1.186,10")
    second = bill_header(PdfPage(), 3)
    second.text(400, 145, "Übertrag:").right(TOTAL_RIGHT, 145, "1.186,10")
    top = item(
        second,
        175,
        "01.30.",
        "Planum herstellen",
        ["Planum auf ± 2 cm herstellen."],
        "12,000",
        "m2",
        "3,10",
        "37,20",
    )
    top = item(
        second,
        top,
        "01.40.",
        "Wasserhaltung (Bedarfsposition)",
        ["Offene Wasserhaltung vorhalten."],
        "1,000",
        "psch",
        "250,00",
        "Nur Einh.-Pr.",
    )
    second.text(OZ_X, top, "Hinweis:", bold=True)
    second.text(TEXT_X, top + 12, "Die Mengen sind Schätzungen des Auftraggebers.")
    top += 40
    second.text(OZ_X, top, "Summe 01.", bold=True).text(TEXT_X + 60, top, "Erdarbeiten", bold=True)
    second.right(TOTAL_RIGHT, top, "1.223,30", bold=True)
    second.text(OZ_X, top + 20, "Summe (netto)", bold=True).right(TOTAL_RIGHT, top + 20, "1.223,30")
    second.text(OZ_X, top + 35, "Gesamtsumme:", bold=True).right(TOTAL_RIGHT, top + 35, "1.455,73")
    return build_pdf([cover, first, second])


def rasterize(pdf: bytes, *, dpi: int = 200, skew_degrees: float = 0.0) -> bytes:
    """``pdf`` as a scan: every page an image of itself (no text layer), rotated by
    ``skew_degrees`` around its centre like a sheet laid crookedly on the scanner."""
    import io as _io

    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    source = pdfium.PdfDocument(pdf)
    scan = pdfium.PdfDocument.new()
    keep = []  # bitmaps must live until the document is saved
    for index in range(len(source)):
        page = source[index]
        width, height = page.get_width(), page.get_height()
        bitmap = page.render(scale=dpi / 72, force_bitmap_format=pdfium_c.FPDFBitmap_BGR)
        keep.append(bitmap)
        target = scan.new_page(width, height)
        image = pdfium.PdfImage.new(scan)
        image.set_bitmap(bitmap)
        matrix = (
            pdfium.PdfMatrix()
            .scale(width, height)
            .translate(-width / 2, -height / 2)
            .rotate(skew_degrees)
            .translate(width / 2, height / 2)
        )
        image.set_matrix(matrix)
        target.insert_obj(image)
        target.gen_content()
    out = _io.BytesIO()
    scan.save(out)
    return out.getvalue()
