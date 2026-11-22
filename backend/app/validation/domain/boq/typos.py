"""Typing slips in the texts of a bill: repeated words, known misspellings, and words that
appear once as a slight variant of a word the bill uses often.

No dictionary is used (construction German is full of compounds a general dictionary does not
know); the bill is its own reference. On item and section rows (short and long text):

* ``repeated_word``: the same lower-case word twice in a row (``und und``, ``nach nach``)
  -> semantic warning, low. Doubled articles (``das das``) are skipped: German allows them.
* ``known_misspelling``: a word from a short list of frequent misspellings (``seperat``,
  ``Standart``, ``wiederrum``, ``Vorraussetzung``) -> low.
* ``rare_variant``: a word of at least ``min_length`` letters that occurs once in the table and
  is one edit (a letter inserted, dropped or replaced, or two neighbouring letters swapped when
  ``transpositions`` is on) from a word occurring at least ``min_frequent`` times
  (``Auftragnehemer`` beside 22 × ``Auftragnehmer``) -> low. Both spellings are named: without
  a dictionary the bill cannot say which one is right (it once used the slip three times).
  Pairs that are usually two real words are not reported: a difference only in the last two
  letters (an ending, a joining ``s``), only at the first letter (``Erfüllung`` /
  ``Verfüllung``), only by an umlaut (``Bogen`` / ``Bögen``), a past participle (``verlegen``
  / ``verlegten``), a pair of ``excluded_pairs`` (``beschreiben`` / ``beschrieben``,
  ``anzulegen`` / ``abzulegen``; a pair also covers words that contain it) and word-initial
  prefixes of ``excluded_prefixes`` (``Abtransport`` / ``Antransport``).

The matcher of ``rare_variant`` is step B2's (2026-11-21, when B2's own ``domain.boq_typos``
merged into this check): 9 letters, 3 uses and transpositions found more real slips at the same
precision on five sample bills than 10 letters, 4 uses and no transpositions, and on the
planted-fault test bill it finds the planted slip that one inserted, dropped or swapped letter
with the same ending did not.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import ClassVar

from pydantic import Field, field_validator

from app.models.dataset import Row, RowKind, Table
from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, Severity
from app.models.values import DataType
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._support import FieldId
from app.validation.domain.boq._bill_text import description_applicability
from app.validation.domain.boq._tender import WORD, anchor, texts

RULE_REPEATED = "repeated_word"
RULE_KNOWN = "known_misspelling"
RULE_VARIANT = "rare_variant"
CATEGORY = "spelling"
WORDS_READ = "words_read"
PAIRS_IGNORED = "similar_pairs_ignored"

MISSPELLINGS: dict[str, str] = {
    "seperat": "separat",
    "seperate": "separate",
    "seperaten": "separaten",
    "seperater": "separater",
    "standart": "Standard",
    "standartmäßig": "standardmäßig",
    "wiederrum": "wiederum",
    "entgültig": "endgültig",
    "entgültige": "endgültige",
    "vorraussetzung": "Voraussetzung",
    "vorraussetzungen": "Voraussetzungen",
    "vorraussichtlich": "voraussichtlich",
    "nähmlich": "nämlich",
    "reperatur": "Reparatur",
    "reperaturen": "Reparaturen",
    "rückgrad": "Rückgrat",
    "ingeneur": "Ingenieur",
    "aluminum": "Aluminium",
    "estrisch": "Estrich",
    "fasade": "Fassade",
    "addresse": "Adresse",
    "rhytmus": "Rhythmus",
    "agressiv": "aggressiv",
    "agressive": "aggressive",
    "nachvollziehbahr": "nachvollziehbar",
    "vorallem": "vor allem",
    "garnicht": "gar nicht",
    "zuende": "zu Ende",
    "tolleranz": "Toleranz",
    "tolleranzen": "Toleranzen",
    "brandschuz": "Brandschutz",
    "isoliertung": "Isolierung",
}
_UMLAUTS = frozenset({("a", "ä"), ("o", "ö"), ("u", "ü"), ("ä", "a"), ("ö", "o"), ("ü", "u")})
DEFAULT_EXCLUDED_PAIRS: tuple[tuple[str, str], ...] = (
    ("leistung", "leitung"),
    ("schichten", "schächten"),
    ("auftrag", "austrag"),
    ("vermeiden", "vermieden"),
    ("beschreiben", "beschrieben"),
    ("vorgeschrieben", "vorbeschrieben"),
    ("verhalten", "vorhalten"),
    ("anzulegen", "abzulegen"),
    ("nahmen", "nehmen"),  # Aufnahmen / aufnehmen, Entnahmen / entnehmen
)
# Separable prefixes one letter apart: ab-/an- (Abtransport, Antransport), auf-/aus-.
DEFAULT_EXCLUDED_PREFIXES: tuple[tuple[str, str], ...] = (("ab", "an"), ("auf", "aus"))
ARTICLES = frozenset({"der", "die", "das", "den", "dem", "des", "the"})


class TyposConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field holding the item number.")
    description_field: FieldId = plannable("description", description="Short text field.")
    long_description_field: FieldId = plannable(
        "long_description", description="Long text field (used when mapped)."
    )
    misspellings: dict[str, str] = Field(
        default_factory=lambda: dict(MISSPELLINGS),
        description="Known misspellings (lower case) and their correct form.",
    )
    min_length: int = Field(default=9, ge=5, le=30, description="Shortest word checked.")
    min_frequent: int = Field(
        default=3, ge=2, le=50, description="How often the reference word must occur."
    )
    transpositions: bool = Field(
        default=True, description="Count two swapped neighbouring letters as one edit."
    )
    excluded_pairs: tuple[tuple[str, str], ...] = Field(
        default=DEFAULT_EXCLUDED_PAIRS,
        description="Real words that differ by one letter; a pair also covers words that "
        "contain it (profile-controlled).",
    )
    excluded_prefixes: tuple[tuple[str, str], ...] = Field(
        default=DEFAULT_EXCLUDED_PREFIXES,
        description="Word-initial prefixes one letter apart that make two real words "
        "(Abtransport / Antransport); a pair differing only there is not reported.",
    )
    max_findings: int = Field(default=200, ge=1, le=5000, description="Findings per table.")

    @field_validator("excluded_pairs", "excluded_prefixes")
    @classmethod
    def _lower_case(cls, value: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
        pairs = tuple((a.lower(), b.lower()) for a, b in value)
        if any(not a or not b or a == b for a, b in pairs):
            raise ValueError("an excluded pair needs two different, non-empty words")
        return pairs


class BoqTyposDetector(Detector[TyposConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_typos",
        name="Typing slips in texts",
        version="1.1.0",
        category=DetectorCategory.SEMANTIC,
        description=(
            "Finds typing slips in item and section texts without a dictionary: a word "
            "repeated, a known misspelling, and a word used once that differs by one letter "
            "from a word the bill uses often (Auftragnehemer beside Auftragnehmer)."
        ),
        required_fields=("description",),
        optional_fields=("long_description", "item_code"),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the item description.",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(CATEGORY,),
        limitations=(
            "The bill is its own reference: a word misspelled the same way throughout is not "
            "found, and a rare correct word can resemble a frequent one.",
            "Text read by OCR has more slips; they are reported like typed ones.",
        ),
        cost="low",
    )
    config_model = TyposConfig

    def required_fields(self, config: TyposConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(self, context: ValidationContext, config: TyposConfig) -> Applicability:
        return description_applicability(context, config.description_field)

    def validate(self, context: ValidationContext, config: TyposConfig) -> DetectorResult:
        result = DetectorResult()
        known = {word.lower(): right for word, right in config.misspellings.items()}
        for table in context.tables():
            if context.has_fields(table, config.description_field):
                self._table(context, config, known, table, result)
        return result

    def _table(
        self,
        context: ValidationContext,
        config: TyposConfig,
        known: dict[str, str],
        table: Table,
        result: DetectorResult,
    ) -> None:
        rows = list(context.rows(table, [RowKind.ITEM, RowKind.SECTION, RowKind.TEXT]))
        fields = (config.description_field, config.long_description_field)
        row_texts = {row.row_id: texts(context, table, row, *fields) for row in rows}
        words = [
            word for pair in row_texts.values() for text in pair for word in WORD.findall(text)
        ]
        frequency: Counter[str] = Counter(word.lower() for word in words)
        frequent = {w: n for w, n in frequency.items() if n >= config.min_frequent}
        shown: dict[str, str] = {}  # a frequent word as the bill writes it most often
        for word, _ in Counter(w for w in words if w.lower() in frequent).most_common():
            shown.setdefault(word.lower(), word)
        index: dict[str, set[str]] = {}  # a frequent word and its one-letter deletions
        for word in frequent:
            for variant in (word, *_deletions(word)):
                index.setdefault(variant, set()).add(word)
        findings = 0
        for row in rows:
            context.checkpoint()
            seen: set[str] = set()
            for text in row_texts[row.row_id]:
                for match in re.finditer(r"\b([a-zäöüß]{2,})\s+\1\b", text):
                    if match.group(1) in ARTICLES:
                        continue
                    if findings < config.max_findings and match.group(0) not in seen:
                        seen.add(match.group(0))
                        findings += 1
                        self._add(
                            context,
                            config,
                            table,
                            row,
                            result,
                            RULE_REPEATED,
                            match.group(0),
                            match.group(1),
                        )
                for word in WORD.findall(text):
                    lower = word.lower()
                    result.count(WORDS_READ)
                    if lower in seen or findings >= config.max_findings:
                        continue
                    if lower in known:
                        seen.add(lower)
                        findings += 1
                        self._add(
                            context, config, table, row, result, RULE_KNOWN, word, known[lower]
                        )
                    elif (
                        len(lower) >= config.min_length
                        and frequency[lower] == 1
                        and not any(c.isupper() for c in word[1:])
                    ):
                        reference = _similar(lower, index, frequency, config, result)
                        if reference is not None:
                            seen.add(lower)
                            findings += 1
                            self._add(
                                context,
                                config,
                                table,
                                row,
                                result,
                                RULE_VARIANT,
                                word,
                                shown[reference],
                                frequent[reference],
                            )

    def _add(
        self,
        context: ValidationContext,
        config: TyposConfig,
        table: Table,
        row: Row,
        result: DetectorResult,
        rule: str,
        found: str,
        right: str,
        count: int = 0,
    ) -> None:
        code = context.text(table, row, config.code_field) or f"row {row.source_row_number}"
        if rule == RULE_REPEATED:
            title = f"'{found}' repeats a word"
            explanation = f"The text of {code} says {found!r}: a word is repeated."
            action = "Delete the repeated word."
        elif rule == RULE_KNOWN:
            title = f"'{found}' is a misspelling of '{right}'"
            explanation = f"The text of {code} writes {found!r}; the correct spelling is {right!r}."
            action = f"Write '{right}'."
        else:
            title = f"'{found}' or '{right}'?"
            explanation = (
                f"The text of {code} writes {found!r} once, while the bill writes {right!r} "
                f"{count} times; the two differ by one letter, so one of them is likely a "
                f"typing slip (usually the rare one)."
            )
            action = (
                f"Check which spelling is right, '{found}' or '{right}', and correct the other."
            )
        cells = anchor(context, table, row, config.description_field)
        result.add(
            context.issues.create(
                self.spec,
                rule_id=rule,
                category=CATEGORY,
                severity=Severity.LOW,
                evidence_class=EvidenceClass.SEMANTIC_WARNING,
                title=f"{code}: {title}"[:200],
                explanation=explanation,
                table=table,
                row=row,
                cells=cells,
                observed_value=found,
                expected_value=right if rule != RULE_REPEATED else None,
                evidence=[
                    EvidenceItem(kind=EvidenceKind.VALUE, label="Word", detail=found, cells=cells)
                ],
                suggested_action=action,
                subject=f"{rule}:{found.lower()}",
            )
        )


def _similar(
    word: str,
    index: dict[str, set[str]],
    frequency: Counter[str],
    config: TyposConfig,
    result: DetectorResult,
) -> str | None:
    """The most frequent word one edit from ``word`` that is not a likely real-word pair."""
    candidates: set[str] = set(index.get(word, ()))
    for variant in _deletions(word):
        candidates |= index.get(variant, set())
    distance = _osa_one if config.transpositions else _levenshtein_one
    for similar in sorted(candidates - {word}, key=lambda w: (-frequency[w], w)):
        if not distance(word, similar):
            continue
        if _ignored(word, similar, config.excluded_pairs, config.excluded_prefixes):
            result.count(PAIRS_IGNORED)
            continue
        return similar
    return None


def _deletions(word: str) -> list[str]:
    return [word[:i] + word[i + 1 :] for i in range(len(word))]


def _osa_one(a: str, b: str) -> bool:
    """Whether the optimal string alignment distance of ``a`` and ``b`` is exactly 1 (an
    insertion, a deletion, a substitution or a swap of two neighbouring letters)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) != len(b):
        return _levenshtein_one(a, b)
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    if len(diff) == 1:
        return True
    return (
        len(diff) == 2
        and diff[1] == diff[0] + 1
        and a[diff[0]] == b[diff[1]]
        and a[diff[1]] == b[diff[0]]
    )


def _levenshtein_one(a: str, b: str) -> bool:
    """Whether the Levenshtein distance of ``a`` and ``b`` is exactly 1."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long[i]:
        i += 1
    return short[i:] == long[i + 1 :]


def _ignored(
    rare: str,
    frequent: str,
    excluded: tuple[tuple[str, str], ...],
    prefixes: tuple[tuple[str, str], ...] = (),
) -> bool:
    """Pairs that are likely two real words (see the module docstring)."""
    for a, b in prefixes:
        for x, y in ((a, b), (b, a)):
            if (
                rare.startswith(x)
                and frequent.startswith(y)
                and rare[len(x) :] == frequent[len(y) :]
            ):
                return True  # separable prefixes: Abtransport / Antransport
    prefix = 0
    while prefix < min(len(rare), len(frequent)) and rare[prefix] == frequent[prefix]:
        prefix += 1
    if len(rare) - prefix <= 2 and len(frequent) - prefix <= 2:
        return True  # only the last two letters differ
    suffix = 0
    while (
        suffix < min(len(rare), len(frequent)) - prefix
        and rare[len(rare) - 1 - suffix] == frequent[len(frequent) - 1 - suffix]
    ):
        suffix += 1
    rare_core = rare[prefix : len(rare) - suffix]
    frequent_core = frequent[prefix : len(frequent) - suffix]
    if prefix == 0 and len(rare_core) <= 1 and len(frequent_core) <= 1:
        return True  # only the first letter differs
    if (rare_core, frequent_core) in _UMLAUTS:
        return True
    if frequent.endswith("en") and rare == frequent[:-2] + "ten":
        return True  # past participle: verlegen / verlegten
    return _excluded_pair(rare, frequent, excluded)


def _excluded_pair(rare: str, frequent: str, excluded: tuple[tuple[str, str], ...]) -> bool:
    for a, b in excluded:
        for x, y in ((a, b), (b, a)):
            at = rare.find(x)
            while at >= 0:
                if frequent == rare[:at] + y + rare[at + len(x) :]:
                    return True
                at = rare.find(x, at + 1)
    return False
