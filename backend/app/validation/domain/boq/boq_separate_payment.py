"""Work the bill pays "separately", without a position that pays for it.

Read as the bidder pricing a client's tender. A clause such as "Die Bettung wird gesondert
vergütet" says that another position pays for the work. The words before "wird"/"werden" (up
to four, without articles) name the work; its head noun gives a stem (the noun without its
last three letters, at least five letters) and, through the ``synonyms`` map, other words
for it ("Bettung" -> "Sand", "Leitungszone", ...). When no other position's Kurz- or Langtext
contains the stem or a synonym, the clause is listed (``separate_payment_without_payer``):
one finding per table, severity medium, evidence ``semantic_warning``. Finding category (for
the category table): ``domain.boq_separate_payment -> omission``.

Read by hand on five sample bills: fewer than half of the clauses it listed with the brief's
synonyms had no paying position (4 of 9); with the synonyms added from that reading 4 of 7,
measured on the same bills. A clause whose head
noun is shorter than five letters, or follows a preposition ("in Pos. 3 wird gesondert
vergütet"), is skipped and counted. When the work is an anonymisation token ("Das
[PERSON_093] wird gesondert vergütet"), no position can be shown to name it, so the clause is
listed (plan 5a: "or X is a token, it is an Omission") and counted.

Positions are read directly, not through the item frame, see :mod:`._bill_text`; notes are
not read (measured on positions only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field, field_validator

from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, Severity, ValidationIssue
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
from app.validation.deterministic._reference_support import checked_pattern, clip
from app.validation.deterministic._support import FieldId
from app.validation.domain.boq._bill_text import (
    BillFields,
    Entry,
    Found,
    description_applicability,
    entry_cells,
    read_bill,
    search_all,
)
from app.validation.support.tokens import token_spans

RULE_NO_PAYER = "separate_payment_without_payer"
CATEGORY = "separate_payment"
MAX_QUOTES = 3
MAX_WORDS = 4  # words before "wird"/"werden" that name the work
MIN_HEAD_CHARS = 5
STEM_DROP = 3  # letters dropped from the head noun for the stem

ITEMS_READ = "items_read"
CLAUSES_FOUND = "clauses_found"
CLAUSES_SKIPPED_NO_HEAD = "clauses_skipped_no_head_noun"
CLAUSES_PAID = "clauses_with_paying_position"
CLAUSES_ON_TOKENS = "clauses_naming_a_token"

_CLAUSE_BOUNDARIES = ".;:!?()[],\n"  # a line break also ends the Kurztext
_EDGE_PUNCTUATION = ",.()!?"
# Articles, conjunctions and qualifiers dropped from the words before the clause.
_FUNCTION_WORDS = frozenset(
    {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "einem",
        "einen", "und", "oder", "sowie", "bzw", "bzw.", "auch", "ebenfalls", "hierfür",
        "dafür", "diese", "dieser", "dieses", "alle", "sämtliche", "-", "–", "event.",
        "evtl.", "ggf.", "eventuelle", "etwaige",
    }
)  # fmt: skip
# A head noun after one of these is the place or the reference, not the work.
_PREPOSITIONS = frozenset(
    {
        "in", "im", "mit", "von", "vom", "für", "auf", "aus", "an", "am", "bei", "beim",
        "nach", "zu", "zum", "zur", "über", "unter", "binnen", "innerhalb", "außerhalb",
        "durch", "gegen", "ohne", "um", "bis", "ab", "s.", "siehe", "gem.", "gemäß", "lt.",
        "laut",
    }
)  # fmt: skip

_FITTINGS = ("bogen", "winkel", "t-stück", "reduzier", "muffe", "flansch", "formteil")
_BACKFILL = ("verfüll", "anfüll", "hinterfüll")
DEFAULT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "bettung": ("sand", "kies", "bettungsmaterial", "leitungszone", "rohrbettung"),
    "form- und verbindungsstücke": _FITTINGS,
    "formstücke": _FITTINGS,
    "verbau": ("verbau", "grabenverbau"),
    "wasserhaltung": ("wasserhaltung", "pumpe"),
    "gerüst": ("gerüst",),
    # Added after reading the hits on the sample bills.
    "suchgr": ("suchschlitz", "suchschacht", "suchgrab", "suchgräb", "probeschurf"),
    "wiederanfüllung": _BACKFILL,
    "anfüllung": _BACKFILL,
}


class SeparatePaymentConfig(DetectorConfig):
    description_field: FieldId = plannable("description", description="Kurztext field.")
    long_description_field: FieldId = plannable("long_description", description="Langtext field.")
    item_code_field: FieldId = plannable("item_code", description="OZ field.")
    clause_pattern: str = Field(
        default=r"\b(?:wird|werden)\s+(?:gesondert|separat)\s+verg(?:ü|ue)tet\b",
        description="The clause that says another position pays (profile-controlled).",
    )
    synonyms: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: dict(DEFAULT_SYNONYMS),
        description="Head noun (start or end of it; a key with a space: the phrase) -> other "
        "words a paying position may use (lower case, matched as parts of words).",
    )
    max_cells_per_issue: int = Field(
        default=20, ge=1, le=200, description="Rows highlighted in one finding."
    )

    @field_validator("clause_pattern")
    @classmethod
    def _valid_pattern(cls, value: str) -> str:
        return checked_pattern(value, groups=None)

    @field_validator("synonyms")
    @classmethod
    def _lower_case(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        cleaned = {
            key.strip().lower(): tuple(w.strip().lower() for w in words if w.strip())
            for key, words in value.items()
        }
        if any(not key for key in cleaned):
            raise ValueError("a synonym key must not be empty")
        return cleaned


@dataclass(frozen=True, slots=True)
class _Clause:
    entry: Entry
    found: Found  # the clause in entry.text
    head: str  # the head noun as written


class SeparatePaymentDetector(Detector[SeparatePaymentConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_separate_payment",
        name="Paid separately, without a paying position (BoQ)",
        version="1.1.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Lists clauses of a bill of quantities that say work is paid separately "
            "('wird gesondert vergütet') when no other position names that work. One finding "
            "per bill. Not run by default: about half of what it lists is paid under another "
            "name."
        ),
        required_fields=("description",),
        optional_fields=("long_description", "item_code"),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the item description (Kurztext).",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(CATEGORY,),
        limitations=(
            "Matches words, not meaning: a position that pays for the work under another "
            "name is not recognised unless the synonym map names it.",
            "Measured on five sample bills: about half of the listed clauses had a paying "
            "position under another name.",
        ),
        cost="low",
    )
    config_model = SeparatePaymentConfig

    def required_fields(self, config: SeparatePaymentConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(
        self, context: ValidationContext, config: SeparatePaymentConfig
    ) -> Applicability:
        return description_applicability(context, config.description_field)

    def validate(self, context: ValidationContext, config: SeparatePaymentConfig) -> DetectorResult:
        result = DetectorResult()
        fields = BillFields(
            config.description_field, config.long_description_field, config.item_code_field
        )
        for table in context.tables():
            if not context.has_fields(table, config.description_field):
                continue
            context.checkpoint()
            items = read_bill(context, table, fields).items
            result.count(ITEMS_READ, len(items))
            unpaid = _unpaid(items, config, result)
            if unpaid:
                result.add(self._issue(context, config, unpaid))
        return result

    def _issue(
        self, context: ValidationContext, config: SeparatePaymentConfig, unpaid: list[_Clause]
    ) -> ValidationIssue:
        entries: list[Entry] = []
        for clause in unpaid:
            if clause.entry not in entries:
                entries.append(clause.entry)
        cells = entry_cells(context, entries, config.description_field, config.max_cells_per_issue)
        by_head: dict[str, list[str]] = {}
        for clause in unpaid:
            labels = by_head.setdefault(clause.head, [])
            if clause.entry.label not in labels:
                labels.append(clause.entry.label)
        listed = "; ".join(f"{head} ({', '.join(labels)})" for head, labels in by_head.items())
        quotes = "; ".join(
            f'{c.entry.label} "{c.entry.quote(c.found)}"' for c in unpaid[:MAX_QUOTES]
        )
        noun, verb = ("clause", "says") if len(unpaid) == 1 else ("clauses", "say")
        return context.issues.create(
            self.spec,
            rule_id=RULE_NO_PAYER,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(f"Paid separately, but no position names it: {len(unpaid)} {noun}", 200),
            explanation=(
                f"{len(unpaid)} {noun} of this bill {verb} that work is paid separately "
                "(gesondert vergütet), but no other position names that work: "
                f"{quotes}. Work without a paying position: {listed}. This is an advisory "
                "warning: the paying position may use other words."
            ),
            table=entries[0].table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Work paid separately, by position",
                    detail=clip(listed, 2000),
                    cells=cells,
                    data={"clauses": len(unpaid), "work": len(by_head)},
                ),
            ],
            suggested_action=(
                "Ask a bidder question: which position pays for this work? The bill says it is "
                "paid separately, but no position names it. Do not price it into other "
                "positions (BGH, X ZB 7/04); if none pays for it, this may become a change "
                "order after award, subject to the contract."
            ),
            subject=RULE_NO_PAYER,
        )


def _unpaid(
    items: list[Entry], config: SeparatePaymentConfig, result: DetectorResult
) -> list[_Clause]:
    """Clauses whose work no other item names, in source order."""
    found: list[tuple[int, Found, list[str], bool]] = []
    searchable: list[str] = []  # each item's text, lower case, with its clauses blanked out
    for index, item in enumerate(items):
        text = item.text
        blanked = text
        for clause in search_all(config.clause_pattern, text):
            words, start, in_brackets = _words_before(text, clause.start)
            found.append((index, clause, words, in_brackets))
            blanked = blanked[:start] + " " * (clause.end - start) + blanked[clause.end :]
        searchable.append(blanked.lower())
    unpaid: list[_Clause] = []
    for index, clause, words, in_brackets in found:
        result.count(CLAUSES_FOUND)
        head, terms = _head_terms(words, in_brackets, config.synonyms)
        if head is None and (token := _token_work(items[index].original, clause.start)):
            result.count(CLAUSES_ON_TOKENS)  # no position can be shown to name a token
            unpaid.append(_Clause(items[index], clause, token))
            continue
        if head is None or not terms:
            result.count(CLAUSES_SKIPPED_NO_HEAD)
            continue
        paid = any(
            any(term in text for term in terms)
            for other, text in enumerate(searchable)
            if other != index
        )
        if paid:
            result.count(CLAUSES_PAID)
            continue
        unpaid.append(_Clause(items[index], clause, head))
    return unpaid


def _words_before(text: str, start: int) -> tuple[list[str], int, bool]:
    """Up to :data:`MAX_WORDS` words before ``start`` back to the last clause boundary, where
    they start, and whether the clause is in brackets ("Bettung (wird gesondert vergütet)")."""
    stripped = text[:start].rstrip()
    in_brackets = stripped.endswith("(")
    if in_brackets:
        stripped = stripped[:-1].rstrip()
    if stripped.endswith(","):
        stripped = stripped[:-1].rstrip()
    position = max(stripped.rfind(c) for c in _CLAUSE_BOUNDARIES) + 1
    spans: list[tuple[int, int]] = []
    while position < len(stripped):
        while position < len(stripped) and stripped[position].isspace():
            position += 1
        end = position
        while end < len(stripped) and not stripped[end].isspace():
            end += 1
        if end > position:
            spans.append((position, end))
        position = end
    spans = spans[-MAX_WORDS:]
    words = [stripped[a:b] for a, b in spans]
    return words, (spans[0][0] if spans else start), in_brackets


def _token_work(text: str, start: int) -> str | None:
    """The anonymisation token that names the work right before ``start`` ("Das
    [PERSON_093] wird gesondert vergütet"), unless a preposition comes before it."""
    stripped = text[:start].rstrip().removesuffix("(").rstrip().removesuffix(",").rstrip()
    for left, right in token_spans(stripped):
        if right == len(stripped):
            before = stripped[:left].split()
            if before and before[-1].lower().strip(_EDGE_PUNCTUATION) in _PREPOSITIONS:
                return None
            return stripped[left:right]
    return None


def _head_terms(
    words: list[str], in_brackets: bool, synonyms: dict[str, tuple[str, ...]]
) -> tuple[str | None, list[str]]:
    """The head noun of the work and the terms a paying position would contain."""
    clean = [w.strip(_EDGE_PUNCTUATION) for w in words]
    clean = [w for w in clean if w]
    phrase = " ".join(clean).lower()
    for key, others in synonyms.items():
        if " " in key and key in phrase:
            return key, [key, *others]
    content = [w for w in clean if w.lower() not in _FUNCTION_WORDS]
    nouns = [w for w in content if _is_noun(w)]
    if not nouns:
        return None, []
    head = nouns[-1] if in_brackets else nouns[0]
    if not in_brackets and any(w.lower() in _PREPOSITIONS for w in content[: content.index(head)]):
        return None, []
    lower = head.rstrip("-").lower()
    if len(lower) < MIN_HEAD_CHARS:
        return head, []
    terms = [lower[: max(MIN_HEAD_CHARS, len(lower) - STEM_DROP)]]
    for key, others in synonyms.items():
        if " " not in key and (lower.startswith(key) or lower.endswith(key)):
            terms.extend(others)
    return head, terms


def _is_noun(word: str) -> bool:
    return (
        len(word) >= 3
        and word[:1].isupper()
        and not word.isupper()
        and not any(c.isdigit() for c in word)
    )
