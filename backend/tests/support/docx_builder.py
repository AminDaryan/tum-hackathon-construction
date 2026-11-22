"""Small Word documents (.docx) for tests, written as WordprocessingML by hand.

Only the parts Word needs to open a file are written ([Content_Types].xml, the package and
document relationships, word/document.xml), plus styles and numbering when a test asks for
them::

    body = paragraph("Erdarbeiten", style="berschrift1") + table([["Pos."], ["1.10"]])
    path = write_docx(tmp_path / "LV.docx", body, styles=heading_styles())
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from pathlib import Path
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_PACKAGE_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)


def run(text: str) -> str:
    """A run; tabs and line breaks become ``w:tab`` and ``w:br``."""
    parts: list[str] = []
    for index, line in enumerate(text.split("\n")):
        if index:
            parts.append("<w:br/>")
        for position, chunk in enumerate(line.split("\t")):
            if position:
                parts.append("<w:tab/>")
            if chunk:
                parts.append(f'<w:t xml:space="preserve">{escape(chunk)}</w:t>')
    return f"<w:r>{''.join(parts)}</w:r>"


def paragraph(
    text: str = "",
    *,
    style: str | None = None,
    outline: int | None = None,
    numbering: tuple[int, int] | None = None,
    raw: str = "",
) -> str:
    """A body paragraph. ``numbering`` is (numId, ilvl); ``raw`` is extra XML after the run."""
    properties = ""
    if style:
        properties += f'<w:pStyle w:val="{style}"/>'
    if numbering:
        properties += (
            f'<w:numPr><w:ilvl w:val="{numbering[1]}"/><w:numId w:val="{numbering[0]}"/></w:numPr>'
        )
    if outline is not None:
        properties += f'<w:outlineLvl w:val="{outline}"/>'
    p_pr = f"<w:pPr>{properties}</w:pPr>" if properties else ""
    content = run(text) if text else ""
    return f"<w:p>{p_pr}{content}{raw}</w:p>"


def cell(text: str = "", *, span: int = 1, merge: str | None = None, raw: str = "") -> str:
    """A table cell; ``merge`` is ``"restart"`` or ``"continue"`` (vertical merge)."""
    properties = ""
    if span > 1:
        properties += f'<w:gridSpan w:val="{span}"/>'
    if merge == "restart":
        properties += '<w:vMerge w:val="restart"/>'
    elif merge == "continue":
        properties += "<w:vMerge/>"
    tc_pr = f"<w:tcPr>{properties}</w:tcPr>" if properties else ""
    paragraphs = "".join(paragraph(line) for line in text.split("\n")) if text else "<w:p/>"
    return f"<w:tc>{tc_pr}{paragraphs}{raw}</w:tc>"


def table(rows: Sequence[Sequence[str]], *, cells: dict[tuple[int, int], str] | None = None) -> str:
    """A table of plain text cells; ``cells`` replaces the cell at (row, index), 0-based, with
    XML made by :func:`cell` (spans, merges)."""
    out = ["<w:tbl><w:tblPr/>"]
    for r, values in enumerate(rows):
        out.append("<w:tr>")
        for c, value in enumerate(values):
            out.append((cells or {}).get((r, c)) or cell(value))
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def heading_styles() -> str:
    """styles.xml with Word's built-in headings as a German Word names them (style id
    ``berschrift1``, name ``heading 1``), and a list paragraph style."""
    styles = "".join(
        f'<w:style w:type="paragraph" w:styleId="berschrift{n}"><w:name w:val="heading {n}"/>'
        '<w:basedOn w:val="Standard"/></w:style>'
        for n in (1, 2, 3)
    )
    return (
        f'<w:styles xmlns:w="{W}">'
        '<w:style w:type="paragraph" w:styleId="Standard"><w:name w:val="Normal"/></w:style>'
        f"{styles}"
        '<w:style w:type="paragraph" w:styleId="Listenabsatz"><w:name w:val="List Paragraph"/>'
        '<w:basedOn w:val="Standard"/></w:style>'
        "</w:styles>"
    )


def numbering_parts(*, decimal_id: int = 1, bullet_id: int = 2) -> str:
    """numbering.xml with one numbered list (``decimal_id``) and one bulleted (``bullet_id``)."""
    return (
        f'<w:numbering xmlns:w="{W}">'
        '<w:abstractNum w:abstractNumId="10"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/>'
        '<w:lvlText w:val="%1."/></w:lvl></w:abstractNum>'
        '<w:abstractNum w:abstractNumId="20"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/>'
        '<w:lvlText w:val="-"/></w:lvl></w:abstractNum>'
        f'<w:num w:numId="{decimal_id}"><w:abstractNumId w:val="10"/></w:num>'
        f'<w:num w:numId="{bullet_id}"><w:abstractNumId w:val="20"/></w:num>'
        "</w:numbering>"
    )


def document_xml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    )


def write_docx(
    path: Path,
    body: str,
    *,
    styles: str | None = None,
    numbering: str | None = None,
    extra: dict[str, bytes] | None = None,
) -> Path:
    """Write a .docx with ``body`` (paragraph and table XML) and return its path."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _PACKAGE_RELS)
        archive.writestr("word/document.xml", document_xml(body))
        if styles is not None:
            archive.writestr("word/styles.xml", styles)
        if numbering is not None:
            archive.writestr("word/numbering.xml", numbering)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return path


def table_bill() -> str:
    """A bill as a Word table with German headers the BoQ profile maps; the line total of
    item 01.0020 is wrong (18 × 165,00 = 2.970,00, the table says 2.790,00)."""
    rows = [
        ["Pos.", "Kurztext", "Menge", "Einheit", "Einheitspreis", "Gesamtpreis"],
        ["01", "Rohbau", "", "", "", ""],
        ["01.0010", "Mauerwerk aus Kalksandstein, 17,5 cm", "120,000", "m2", "45,50", "5.460,00"],
        ["01.0020", "Beton C25/30 für Fundamente", "18,000", "m3", "165,00", "2.790,00"],
        ["01.0030", "Betonstahl B500B liefern und einbauen", "2,500", "t", "1.450,00", "3.625,00"],
    ]
    title = cell("Leistungsverzeichnis Rohbau", span=6)
    return paragraph("Leistungsverzeichnis", style="berschrift1") + table(
        [["Leistungsverzeichnis Rohbau"], *rows], cells={(0, 0): title}
    )
