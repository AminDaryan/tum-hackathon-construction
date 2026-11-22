"""Safe names for downloaded files and for the entries of export archives.

Document file names, run ids and table names are untrusted or at least uncontrolled text, but
they end up in ``Content-Disposition`` headers and in ZIP entry names, where a path separator,
``..``, a quote, a control or bidi-override character could traverse directories, inject
header parameters or spoof a name. Every name built here keeps only:

* Unicode letters (categories ``L*``) and decimal digits (``Nd``), after NFC normalization,
* a small set of punctuation (space, ``-``, ``_``, and ``.`` in file stems only);

any other character becomes ``_``. Whitespace runs become one space, runs of ``_`` and ``.``
are collapsed, spaces, ``.``, ``_`` and ``-`` are trimmed at both ends, and the result is cut
to a maximum length; a name without any letter or digit falls back to a fixed word. A name
therefore never contains a path separator or ``..`` and never starts with a dot.

Document and project names are written by people, so their other punctuation (commas,
slashes, parentheses) becomes a space rather than ``_``: ``LV (Kopie) (2).xlsx`` gives the stem
``LV Kopie 2``.

The names may contain non-ASCII letters (``Übersicht``): the API derives the
``Content-Disposition`` header with an ASCII fallback plus ``filename*`` (RFC 6266).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC

from app.models.document import Document
from app.models.run import ValidationRun

MAX_STEM_CHARS = 80
MAX_TABLE_NAME_CHARS = 60
STEM_FALLBACK = "export"
TABLE_NAME_FALLBACK = "table"

_SUFFIX_PATTERN = re.compile(r"[A-Za-z0-9 ._-]{0,32}")
_TRIMMED = " ._-"


def _is_letter_or_digit(char: str) -> bool:
    category = unicodedata.category(char)
    return category.startswith("L") or category == "Nd"


def safe_name(text: str, *, punctuation: str, max_chars: int, fallback: str) -> str:
    """``text`` reduced to letters, digits and ``punctuation`` (see the module docstring)."""
    kept: list[str] = []
    for char in unicodedata.normalize("NFC", text):
        if char.isspace():
            kept.append(" " if " " in punctuation else "_")
        elif _is_letter_or_digit(char) or char in punctuation:
            kept.append(char)
        else:
            kept.append("_")
    name = re.sub(r"\.{2,}", ".", re.sub(r"_{2,}", "_", re.sub(r" {2,}", " ", "".join(kept))))
    name = name.strip(_TRIMMED)[:max_chars].strip(_TRIMMED)
    return name if any(_is_letter_or_digit(char) for char in name) else fallback


def _words(text: str, punctuation: str) -> str:
    """``text`` with every character that is not a letter, a digit or in ``punctuation``
    turned into a space."""
    return "".join(
        char if _is_letter_or_digit(char) or char in punctuation else " "
        for char in unicodedata.normalize("NFC", text)
    )


def document_stem(original_filename: str) -> str:
    """The safe stem of a document name: without its last extension, at most 80 characters,
    never empty (``"export"``)."""
    head, dot, _ = original_filename.rpartition(".")
    stem = head if dot and head.strip(_TRIMMED) else original_filename
    return safe_name(
        _words(stem, "-_."), punctuation=" -_.", max_chars=MAX_STEM_CHARS, fallback=STEM_FALLBACK
    )


def export_filename(document: Document, run: ValidationRun, suffix: str) -> str:
    """``<document-stem> <run start><suffix>``, e.g. ``Angebot März 2026-03-01 09-00 issues.csv``.

    The run is named by when it started (UTC, to the minute), not by its internal id, so two
    runs of a bill on the same day still get different names. ``suffix`` comes from the
    exporter (``.json``, `` issues.csv``, `` tables.zip``) and may contain only ASCII letters,
    digits, space, ``.``, ``_`` and ``-``."""
    if _SUFFIX_PATTERN.fullmatch(suffix) is None:
        raise ValueError(f"unsafe filename suffix {suffix!r}")
    started = run.started_at.astimezone(UTC).strftime("%Y-%m-%d %H-%M")
    return f"{document_stem(document.original_filename)} {started}{suffix}"


def dataset_export_filename(document: Document, dataset_id: str, suffix: str) -> str:
    """``<document-stem>-<dataset_id><suffix>``, e.g. ``LV_03-ds_1a2b-extracted.xlsx``."""
    if _SUFFIX_PATTERN.fullmatch(suffix) is None:
        raise ValueError(f"unsafe filename suffix {suffix!r}")
    dataset_part = safe_name(dataset_id, punctuation="-_", max_chars=64, fallback="dataset")
    return f"{document_stem(document.original_filename)}-{dataset_part}{suffix}"


def safe_table_name(name: str) -> str:
    """A table name usable inside an archive entry name: letters, digits, space, ``-`` and
    ``_``; at most 60 characters; ``"table"`` when nothing usable remains."""
    return safe_name(
        name, punctuation=" -_", max_chars=MAX_TABLE_NAME_CHARS, fallback=TABLE_NAME_FALLBACK
    )


def table_entry_name(index: int, name: str, extension: str = ".csv") -> str:
    """``<NN>-<safe table name><extension>`` for the 1-based table ``index`` (``01-LV.csv``).
    The number prefix also keeps reserved device names (``CON``, ``NUL``) out of the base
    name."""
    if index < 1:
        raise ValueError("table index is 1-based")
    return f"{index:02d}-{safe_table_name(name)}{extension}"


def project_export_filename(project_name: str, suffix: str) -> str:
    """``<project-name><suffix>``, e.g. ``Brücke Nord report.pdf``. Punctuation in the name
    (``Kalkufer 17, anchored excavation``) becomes a space rather than ``_``: a project name is
    written by a person, and its commas and slashes only separate words."""
    if _SUFFIX_PATTERN.fullmatch(suffix) is None:
        raise ValueError(f"unsafe filename suffix {suffix!r}")
    words = _words(project_name, "-_")
    stem = safe_name(words, punctuation=" -_", max_chars=MAX_STEM_CHARS, fallback="project")
    return f"{stem}{suffix}"
