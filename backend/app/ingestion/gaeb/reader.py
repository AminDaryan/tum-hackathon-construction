"""Read a GAEB DA XML file into a :class:`~app.ingestion.gaeb.model.GaebDocument`.

Checks, in order, each with its own message (the document is then stored as failed):

1. Well-formed XML, parsed without DTD loading, entity expansion or network access; a file with a
   ``DOCTYPE`` is refused.
2. Root element ``GAEB`` in a GAEB namespace; the namespace names a supported version (3.1,
   3.2, 3.3) and the exchange phase the file extension names (``.x83`` -> ``DA83``; in 3.1,
   whose namespace is the same for every phase, ``Award/DP`` names it).
3. ``GAEBInfo/Version`` is that version and ``Award/DP`` a value allowed in that phase.
4. Valid against the official phase schema (:mod:`app.ingestion.gaeb.schemas`).

Only then is the bill read. Values keep their lexical text; text elements become plain text with
paragraph and line breaks as spaces.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from lxml import etree

from app.core.errors import ExtractionError, UnsupportedFormatError
from app.ingestion.gaeb.model import (
    EntryKind,
    GaebCategory,
    GaebDocument,
    GaebEntry,
    XmlValue,
)
from app.ingestion.gaeb.schemas import (
    NAMESPACE_PATTERN,
    VERSIONS,
    GaebSchema,
    compiled,
    schemas_for,
)

MAX_LISTED_ERRORS = 3
_CLARK = re.compile(r"\{[^}]*\}")
_BREAKS = frozenset({"br", "p", "div", "li", "tr"})
# Item flags shown in the item type, and the item fields read into columns.
_FLAGS = (
    "Provis",
    "ALNGroupNo",
    "ALNSerNo",
    "LumpSumItem",
    "HourIt",
    "KeyIt",
    "NotAppl",
    "NotOffered",
    "QtyTBD",
    "MarkupIt",
    "Markup",
)
_READ = frozenset({*_FLAGS, "Qty", "QU", "UP", "IT", "DiscountPcnt", "Description", "ITMarkup"})
_NOTES = {"Remark": EntryKind.NOTE, "PerfDescr": EntryKind.NOTE}


def read_gaeb(path: Path, expected_phase: str) -> GaebDocument:
    tree = _parse(path)
    root = tree.getroot()
    schema = _identify(root, expected_phase)
    reader = _Reader(schema)
    reader.check_header(root)
    xsd = compiled(schema)
    if not xsd.validate(tree):
        errors = list(xsd.error_log)
        shown = "; ".join(
            f"line {e.line}: {_CLARK.sub('', e.message)}" for e in errors[:MAX_LISTED_ERRORS]
        )
        raise ExtractionError(
            f"The file does not conform to the official {schema.label} schema "
            f"({len(errors)} error{'s' if len(errors) != 1 else ''}). {shown}",
            details={"reason": "gaeb_schema_invalid", "errors": len(errors)},
        )
    return reader.document(root)


def _parse(path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
    )
    try:
        tree = etree.parse(str(path), parser)
    except etree.XMLSyntaxError as exc:
        raise ExtractionError(
            f"The file is not well-formed XML (line {exc.lineno}): {exc.msg}",
            details={"reason": "xml_malformed"},
        ) from None
    if tree.docinfo.doctype:
        raise UnsupportedFormatError(
            "The file declares a DOCTYPE. GAEB DA XML files have none, and DOCTYPE "
            "declarations are refused for safety.",
            details={"reason": "xml_doctype"},
        )
    return tree


def _identify(root: etree._Element, expected_phase: str) -> GaebSchema:
    qname = etree.QName(root)
    namespace = qname.namespace or ""
    if qname.localname != "GAEB" or not namespace.startswith("http://www.gaeb.de/"):
        raise UnsupportedFormatError(
            f"The file is XML but not GAEB DA XML (root element '{qname.localname}').",
            details={"reason": "not_gaeb", "namespace": namespace or None},
        )
    candidates = schemas_for(namespace)
    match = NAMESPACE_PATTERN.match(namespace)
    if not candidates and (match is None or match.group(2) not in VERSIONS):
        version = match.group(2) if match else "of this namespace"
        raise UnsupportedFormatError(
            _unsupported_version(version),
            details={"reason": "gaeb_version_unsupported", "namespace": namespace},
        )
    if match is not None:
        phase, where = match.group(1), "in its namespace"
    else:  # 3.1: one namespace for every phase, Award/DP names it
        dp = root.findtext(f"{{{namespace}}}Award/{{{namespace}}}DP") or ""
        phase, where = dp.strip()[:2] or "?", "in Award/DP"
    if phase != expected_phase:
        raise UnsupportedFormatError(
            f"The file name ends with .x{expected_phase}, but the file is a GAEB X{phase} "
            f"(exchange phase {phase} {where}). Correct the file name.",
            details={"reason": "gaeb_phase_mismatch", "phase": phase},
        )
    schema = next((s for s in candidates if s.phase == phase), None)
    if schema is None:  # a supported version without this phase
        raise UnsupportedFormatError(
            f"GAEB exchange phase X{phase} is not supported.",
            details={"reason": "gaeb_phase_unsupported", "phase": phase},
        )
    return schema


def _unsupported_version(version: str) -> str:
    return (
        f"GAEB DA XML {version} is not supported; versions {', '.join(VERSIONS)} and GAEB 90 "
        "are read. Export the file as GAEB DA XML 3.3 from the AVA program."
    )


class _Reader:
    def __init__(self, schema: GaebSchema) -> None:
        self.schema = schema
        self.ns = schema.namespace
        self.document_: GaebDocument | None = None

    # ------------------------------------------------------------------ helpers
    def q(self, name: str) -> str:
        return f"{{{self.ns}}}{name}"

    def find(self, element: etree._Element | None, path: str) -> etree._Element | None:
        if element is None:
            return None
        return element.find("/".join(self.q(part) for part in path.split("/")))

    def value(self, element: etree._Element | None, path: str) -> XmlValue | None:
        found = self.find(element, path)
        if found is None or found.text is None or not found.text.strip():
            return None
        return XmlValue(found.text.strip(), found.sourceline)

    def text(self, element: etree._Element | None, path: str) -> str | None:
        found = self.value(element, path)
        return found.text if found is not None else None

    # ------------------------------------------------------------------ checks
    def check_header(self, root: etree._Element) -> None:
        version = self.text(root, "GAEBInfo/Version")
        if version != self.schema.version and version not in VERSIONS:
            # 3.0 shares the 3.1 namespace; its schemas are not bundled.
            raise UnsupportedFormatError(
                _unsupported_version(version or "(no GAEBInfo/Version)"),
                details={"reason": "gaeb_version_unsupported"},
            )
        if version != self.schema.version:
            raise UnsupportedFormatError(
                f"GAEBInfo/Version says {version!r}, but the namespace is GAEB DA XML "
                f"{self.schema.version}.",
                details={"reason": "gaeb_version_mismatch"},
            )
        dp = self.text(root, "Award/DP")
        if dp not in self.schema.dp_values:
            allowed = ", ".join(sorted(self.schema.dp_values))
            raise UnsupportedFormatError(
                f"Award/DP says {dp!r}; an X{self.schema.phase} file must say {allowed}.",
                details={"reason": "gaeb_dp_mismatch"},
            )

    # ------------------------------------------------------------------ reading
    def document(self, root: etree._Element) -> GaebDocument:
        award = self.find(root, "Award")
        boq = self.find(award, "BoQ")
        document = GaebDocument(
            version=self.schema.version,
            phase=self.schema.phase,
            dp=self.text(root, "Award/DP") or "",
            schema_file=self.schema.xsd,
            schema_sha256=self.schema.sha256,
            line=boq.sourceline if boq is not None else None,
            project=self.text(root, "PrjInfo/NamePrj"),
            boq_name=self.text(boq, "BoQInfo/Name"),
            boq_id=boq.get("ID") if boq is not None else None,
            currency=self.text(award, "AwardInfo/Cur") or self.text(root, "PrjInfo/Cur"),
            date=_iso_date(self.text(boq, "BoQInfo/Date") or self.text(root, "GAEBInfo/Date")),
            total=self.value(boq, "BoQInfo/Totals/Total"),
            vat_percent=self.value(boq, "BoQInfo/Totals/VAT"),
            total_gross=self.value(boq, "BoQInfo/Totals/TotalGross"),
        )
        self.document_ = document
        document.body = self.body(self.find(boq, "BoQBody"), [], 1, alternative=False)
        return document

    def body(
        self, body: etree._Element | None, path: list[str], level: int, *, alternative: bool
    ) -> list[GaebCategory | GaebEntry]:
        out: list[GaebCategory | GaebEntry] = []
        for element in body if body is not None else ():
            if not isinstance(element.tag, str):
                continue
            name = etree.QName(element).localname
            if name == "BoQCtgy":
                out.append(self.category(element, path, level, alternative=alternative))
            elif name == "Itemlist":
                for entry in element:
                    if isinstance(entry.tag, str):
                        read = self.entry(entry, path, alternative=alternative)
                        if read is not None:
                            out.append(read)
            elif name in _NOTES:
                out.append(self.note(element))
            else:
                self.not_shown(name)
        return out

    def category(
        self, element: etree._Element, path: list[str], level: int, *, alternative: bool
    ) -> GaebCategory:
        number = [*path, element.get("RNoPart", "")]
        serial = self.text(element, "ALNBSerNo")
        alternative = alternative or (serial is not None and serial != "0")
        category = GaebCategory(
            element_id=element.get("ID"),
            number=".".join(number),
            label=_plain(self.find(element, "LblTx")),
            line=element.sourceline,
            level=level,
            alternative=alternative,
            total=self.value(element, "Totals/Total"),
            discount_percent=self.value(element, "Totals/DiscountPcnt"),
            discount_amount=self.value(element, "Totals/DiscountAmt"),
            total_after_discount=self.value(element, "Totals/TotAfterDisc"),
            total_lump_sum=self.value(element, "Totals/TotalLSUM"),
        )
        category.children = self.body(
            self.find(element, "BoQBody"), number, level + 1, alternative=alternative
        )
        return category

    def entry(
        self, element: etree._Element, path: list[str], *, alternative: bool
    ) -> GaebEntry | None:
        name = etree.QName(element).localname
        if name in _NOTES:
            return self.note(element)
        if name not in ("Item", "MarkupItem"):
            self.not_shown(name)
            return None
        number = ".".join([*path, element.get("RNoPart", "")]) + element.get("RNoIndex", "")
        flags: list[str] = []
        for child in element:
            if not isinstance(child.tag, str):
                continue
            local = etree.QName(child).localname
            if local in _FLAGS:
                text = (child.text or "").strip()
                flags.append(local if text in ("", "Yes") else f"{local}={text}")
            elif local not in _READ:
                self.not_shown(local)
        description = self.find(element, "Description")
        entry = GaebEntry(
            kind=EntryKind.ITEM if name == "Item" else EntryKind.MARKUP_ITEM,
            element=name,
            element_id=element.get("ID"),
            number=number,
            line=element.sourceline,
            short_text=self.short_text(description),
            long_text=_plain(self.find(description, "CompleteText/DetailTxt")),
            flags=tuple(flags),
            in_alternative_category=alternative,
            qty=self.value(element, "Qty"),
            unit=self.value(element, "QU"),
            unit_price=self.value(element, "UP"),
            discount_percent=self.value(element, "DiscountPcnt"),
            total=self.value(element, "IT"),
            markup_base=self.value(element, "ITMarkup"),
        )
        entry.standard_text_key, entry.standard_text_catalog = self.standard_text(description)
        return entry

    def note(self, element: etree._Element) -> GaebEntry:
        # A PerfDescr may hold several descriptions, each naming its standard text.
        descriptions = element.findall(self.q("Description"))
        long_texts = [_plain(self.find(d, "CompleteText/DetailTxt")) for d in descriptions]
        entry = GaebEntry(
            kind=EntryKind.NOTE,
            element=etree.QName(element).localname,
            element_id=element.get("ID"),
            number="",
            line=element.sourceline,
            short_text=next((t for t in map(self.short_text, descriptions) if t), ""),
            long_text=" ".join(t for t in long_texts if t),
        )
        found = [self.standard_text(d) for d in descriptions]
        keys = [k for k, _ in found if k]
        catalogues = list(dict.fromkeys(c for _, c in found for c in (c or "").split("; ") if c))
        entry.standard_text_key = "; ".join(keys) or None
        entry.standard_text_catalog = "; ".join(catalogues) or None
        return entry

    def short_text(self, description: etree._Element | None) -> str:
        for path in ("CompleteText/OutlineText/OutlTxt", "OutlineText/OutlTxt"):
            found = self.find(description, path)
            if found is not None:
                return _plain(found)
        return ""

    def standard_text(self, description: etree._Element | None) -> tuple[str | None, str | None]:
        """(key, catalogue) of an STLB-Bau reference or a standard text number (StLNo).

        STLB-Bau: ``"<catalogue> <version> LB <work section> G <group>: <characteristics>"``,
        each characteristic as ``ArtChrIdent-ArtChIdx-ChVIdent`` in source order. StLNo:
        ``"<Type> <number>"``. Several references in one description are joined with "; " in
        source order. Two items with equal keys reference the same standard texts."""
        keys: list[tuple[str, str | None]] = []
        if description is None:
            return None, None
        for stlb in description.findall(self.q("STLBBau")):
            ctlg = self.find(stlb, "STLBBauCtlg")
            name = self.text(ctlg, "CtlgName") or ""
            version = self.text(ctlg, "VersDate") or ""
            catalogue = " ".join(p for p in (name, version) if p)
            head = catalogue
            if (section := self.text(ctlg, "WCtg")) is not None:
                head += f" LB {section}"
            head += f" G {self.text(ctlg, 'Group') or ''}"
            characteristics = [
                "-".join(
                    self.text(characteristic, part) or ""
                    for part in ("ArtChrIdent", "ArtChIdx", "ChVIdent")
                )
                for characteristic in stlb.findall(self.q("STLBBauID"))
            ]
            keys.append((f"{head}: {' '.join(characteristics)}".strip(), catalogue or None))
        for number in description.findall(self.q("StLNo")):
            if (number.text or "").strip():
                kind = number.get("Type") or "StLNo"
                keys.append((f"{kind} {number.text.strip()}", kind))
        if not keys:
            return None, None
        catalogues = list(dict.fromkeys(c for _, c in keys if c))
        return "; ".join(k for k, _ in keys), "; ".join(catalogues) or None

    def not_shown(self, name: str) -> None:
        if self.document_ is not None:
            self.document_.not_shown[name] += 1


def _plain(element: etree._Element | None) -> str:
    """Plain text of a rich-text element; paragraph and line breaks become spaces, runs of
    whitespace one space."""
    if element is None:
        return ""
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            if isinstance(child.tag, str):
                if etree.QName(child).localname in _BREAKS:
                    parts.append(" ")
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(element)
    return " ".join("".join(parts).split())


def _iso_date(text: str | None) -> str | None:
    """An xs:date (YYYY-MM-DD, optionally with a time zone) as YYYY-MM-DD; None otherwise."""
    try:
        return date.fromisoformat((text or "").strip()[:10]).isoformat()
    except ValueError:
        return None
