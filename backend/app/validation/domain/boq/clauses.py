"""Clauses in the texts of a bill that a bidder must price, ask about or keep a record of.

Six rules read the Kurztext and Langtext of every item (plan 5a, B2 brief A). The finding
category of each rule (the six categories of the Kontroller's review) is given in brackets;
the category table itself is maintained elsewhere.

* ``risk_shifting_clause`` [risk]: a sentence names a subject (the ground, water, shoring,
  construction time and weather, work of the client or other trades) and, within
  ``max_subject_gap_chars`` characters, a phrase that puts its cost into the unit price
  ("einzukalkulieren", "abgegolten", "wird nicht gesondert vergütet"). One finding per table
  and subject, listing the positions; semantic warning, medium for ground, water and shoring,
  low for the others. A subject named just before "wird gesondert vergütet" is paid
  separately and does not count; neither does one named before a shift phrase that opens a
  list ("Folgende Leistungen sind einzukalkulieren: ..."), whose items follow it. The distance
  matters in STLB texts, whose comma lists run to hundreds of characters in one sentence:
  measured on the sample bills, real pairs lay at most 80 characters apart, unrelated ones
  more than 100.
* ``assumed_condition`` [change_order_opportunity]: a condition stated as an assumption
  ("vermutlich", "voraussichtlich", "vorläufig ermittelt", "Untersuchungsergebnisse liegen
  noch nicht vor"). One finding per position; semantic warning, medium.
* ``deferred_decision`` [change_order_opportunity]: a decision about the work left until later
  ("endgültige Festlegung", "erst nach ... festgelegt"). One finding per position; semantic
  warning, medium.
* ``vague_wording`` [ambiguity]: open-ended inclusions ("einschl. aller erforderlichen
  Maschinen", not small material such as "Befestigungsmaterial") and details left open ("in
  geeigneter Weise", "nach Wahl des AN", "nach Bedarf", "sinngemäß"). One finding per table;
  semantic warning, low. A phrase that ``open_lump_sum`` reports in a lump sum is left to it.
* ``open_lump_sum`` [risk]: a lump sum whose text depends on an amount it does not fix ("nach
  tatsächlichem Aufwand", "je Charge", "nach Bedarf"). One finding per table; semantic
  warning, medium.
* ``document_reference`` [ambiguity]: a position refers to a plan, drawing, calculation or
  report ("gemäß Zeichnung", "lt. Gutachten", "siehe Anlage 4"). One finding per table; needs
  external context, info.

Texts are read from the rows (``_clause_support``), so tables without a unit price column are
read too, and a bill without a Langtext column is read from its Kurztext and continuation
lines. Each finding quotes at most ``max_quotes`` clauses, lists every position and highlights
the cells the clauses are in. Matches on anonymisation tokens ("nach [PERSON_125] des AN") are
skipped; patterns examine one sentence at a time, at most ``MAX_MATCH_CHARS`` characters per
search.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import patterns
from app.models.dataset import Table
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
from app.validation.domain.boq._clause_support import (
    NOTE_ITEM_TYPE_PATTERN,
    ItemText,
    MatchStats,
    Phrase,
    TextCell,
    cell_refs,
    excerpt,
    find_in_sentence,
    is_lump_sum,
    item_texts,
    positions_list,
    sentences_of,
    text_tables,
    unit_keys,
)
from app.validation.support.sentences import Sentence

RULE_RISK = "risk_shifting_clause"
RULE_ASSUMED = "assumed_condition"
RULE_DEFERRED = "deferred_decision"
RULE_VAGUE = "vague_wording"
RULE_LUMP_SUM = "open_lump_sum"
RULE_DOCUMENT = "document_reference"
CATEGORY_CLAUSE = "contract_clause"
CATEGORY_WORDING = "wording"
CATEGORY_LUMP_SUM = "lump_sum"
CATEGORY_DOCUMENT = "reference"

ITEMS_READ = "items_with_text"
SENTENCES_READ = "sentences_read"
SENTENCES_IN_WINDOWS = "sentences_read_in_windows"
SKIPPED_ON_TOKENS = "matches_on_tokens_skipped"

# ------------------------------------------------------------------ default word lists
GROUND_PATTERN = (
    r"\bbodenklassen?\b|\bhomogenbereich(?:e|en|es|s)?\b|\bbodenverhältnissen?\b"
    r"|\bbaugrund(?:es|s)?\b|\bfels\w*|\bgesteins?\b|\bgesteine\b|\bgesteinsfestigkeit(?:en)?\b"
    r"|\bhindernis(?:se|sen)?\b|\bfindling(?:e|en)?\b|\bsparten\b|\bbestandsleitung(?:en)?\b"
    r"|\bvorhandene[nr]?\s+(?:[\w-]+\s+){0,3}?[\w-]*leitungen\b|\bmaschinenschachtung\b"
)
WATER_PATTERN = (
    r"\bgrundwasser\w*|\bwasserhaltung\w*|\bschichtenwasser\w*|\btagw[aä]sser\w*"
    r"|\bregenwasser\b|\boberflächenwasser\w*|\bsickerwasser\w*"
)
SHORING_PATTERN = r"\b(?:graben)?verbau(?:s|es)?\b|\bböschung\w*|\bgeböscht\w*"
# "Bauzeit" as a word: "Bauzeitenplan" is a document. "Winterbauumlage" is a levy and
# "Frostschutzschicht" a road layer, so neither counts.
TIME_WEATHER_PATTERN = (
    r"\bbauzeit\b|\bbauzeitverlängerung(?:en)?\b"
    r"|\bwinter(?:bau|monate|monaten|zeit|liche[nmrs]?)?\b|\bfrost(?:es|perioden?|tagen?)?\b"
    r"|\bwitterung(?:en|seinflüssen?|sbedingte?[nmrs]?|sverhältnissen?)?\b"
    r"|\bschlechtwetter\w*|\bbehinderung(?:en)?\b"
)
INTERFACES_PATTERN = (
    r"\bbauseit(?:s|ig\w*)\b|\bandere[nrsm]?\s+gewerke?n?\b|\bfremdfirm(?:a|en)\b"
    r"|\bdurch\s+dritte\b|\bvom\s+(?:ag|auftraggeber)\b"
)
# The cost goes into the unit price; "nicht einzukalkulieren" says the opposite.
SHIFT_PATTERN = (
    r"(?<!\bnicht\s)(?<!\bnicht\smit\s)"
    r"\b(?:einzukalkulieren|einzurechnen|einkalkuliert|eingerechnet|abgegolten)\b"
    r"|\b(?:wird|werden)\s+(?:\w+\s+){0,2}?nicht\s+(?:gesondert|separat)\s+vergütet\b"
    r"|\bkeine\s+(?:gesonderte|separate)\s+vergütung\b"
    r"|(?<!\bnicht\s)\bim\s+einheitspreis\s+enthalten\b"
    r"|\bträgt\s+der\s+(?:an|auftragnehmer|bieter)\b"
    r"|\bzu\s+lasten\s+des\s+(?:an|auftragnehmers)\b"
)
PAID_SEPARATELY_PATTERN = (
    r"\b(?:wird|werden|ist|sind)\s+(?:(?!nicht\b)\w+\s+){0,2}?"
    r"(?:gesondert|separat|extra)\s+(?:vergütet|abgerechnet|bezahlt)\b"
)
ASSUMED_CONDITION_PATTERN = (
    r"\bvermutlich\w*|\bvoraussichtlich\w*|\bmutmaßlich\w*"
    r"|\bvorläufig\s+(?:ermittelt|festgelegt|angenommen)\w*"
    r"|\bnach\s+(?:derzeitigem|heutigem)\s+(?:kenntnis|wissens)stand\b"
    r"|\buntersuchungsergebnisse?\s+liegen\s+noch\s+nicht\s+vor\b"
    r"|\beventuell\s+auftretende[nmrs]?\b"
)
DEFERRED_DECISION_PATTERN = (
    r"\bendgültige[nr]?\s+(?:festlegung|entscheidung)\b"
    r"|\berst\s+nach\b.{0,80}?\b(?:festgelegt|festlegung|festgestellt|entschieden|bestimmt)\b"
    r"|\bwird\s+erst\s+(?:vor\s+ort|nach\s+freilegung)\s+(?:festgelegt|entschieden)\b"
)
# The group is the first word of what is included.
INCLUSION_PATTERN = (
    r"(?:\beinschl\.|\beinschließlich\b|\binkl\.|\binklusive\b)\s*"
    r"(?:aller|sämtlicher|allem|sämtlichem)\s+"
    r"(?:notwendigen|erforderlichen|erfordelichen|benötigten|notwendiger|erforderlicher)\s+"
    r"(\S+)"
)
# Applied to that first word: small material ("Schrauben-, Dichtungs- und Befestigungsmaterial").
SMALL_MATERIAL_PATTERN = (
    r"^(?:befestigungs|montage|verbindungs|schrauben|dichtungs|klein|hilfs|verbrauchs)"
    r"(?:-|material|mittel)|^zubehör"
)
# "sinngemäß" followed by the position it refers to ("sinngemäß wie Pos. 01.0010, jedoch ...")
# names what is meant, like "wie vor, jedoch": normal bill language, not vague.
OPEN_DETAIL_PATTERN = (
    r"\bin\s+geeigneter\s+weise\b|\bnach\s+wahl\s+des\s+(?:an|auftragnehmers)\b"
    r"|\bnach\s+(?:örtlichem\s+)?erfordernis\b|\bnach\s+bedarf\b"
    r"|\bsinngemäß\w*\b(?!\s+(?:wie\s+(?:in\s+)?)?(?:pos(?:ition)?|oz)\b\.?\s*\d)"
)
OPEN_LUMP_SUM_PATTERN = (
    r"\bnach\s+tatsächlich(?:em|en|er)?\s+(?:anfallende[mn]\s+)?(?:stunden)?aufwand\b"
    r"|\bnach\s+(?:tatsächlichem\s+)?aufwand\b|\bnach\s+bedarf\b"
    r"|\bnach\s+(?:örtlichem\s+)?erfordernis\b|\bjede[rnms]?\s+charge\b|\bje\s+charge\b"
    r"|\bnach\s+aufmaß\b|\bmengenermittlung\s+nach\b|\bnach\s+anfall\b"
)
LUMP_SUM_UNITS = ("psch", "pauschal", "pa")
LUMP_SUM_ITEM_TYPE_PATTERN = r"\bpauschalposition\b"
DOCUMENT_REFERENCE_PATTERN = (
    r"(?:\bgem\.|\bgemäß\b|\blt\.|\blaut\b|\bsiehe\b|\bs\.|\bnach\b|\bentsprechend\b"
    r"|\bbeiliegende[rmns]?\b)\s*(?:[\w./-]+\s+){0,2}?"
    r"(?:pläne|plänen|plan|zeichnungen|zeichnung|statik|statische[nrs]?\s+berechnung(?:en)?"
    r"|details?|bodengutachten|baugrundgutachten|gutachten|geotechnische[rn]?\s+bericht\w*"
    r"|lageplan|leitungsplan|anlage\s+\d+|regelzeichnung(?:en)?|regelblatt|systemskizze"
    r"|skizze|fließbild)\b"
)

RISK_RECOMMENDATION = (
    "Price {label} in these positions, as the clauses say, and never in other positions "
    "(BGH, X ZB 7/04). If the bill does not describe the conditions well enough to estimate "
    "the cost, ask a bidder question early: site conditions such as soil and water must be "
    "described (§ 7 (1) Nr. 6 VOB/A)."
)
ASSUMPTION_RECOMMENDATION = (
    "Price the work as the bill describes it, on the stated assumption, and do not price the "
    "uncertainty in. Keep a record of it. If the condition or the later decision changes the "
    "work after award, announce the claim in writing before you carry out the changed or "
    "additional work (§ 2 (6) VOB/B), subject to the contract."
)
VAGUE_RECOMMENDATION = (
    "Where these words leave open what to supply and the cost may matter, ask a bidder "
    "question about what is meant. Price what the text lets you estimate and keep a record of "
    "your assumption."
)
LUMP_SUM_RECOMMENDATION = (
    "Ask a bidder question about the scope the lump sum covers (for example the number of "
    "batches, cleanings or hours) or how it is billed when the effort differs. Price the scope "
    "the bill states and keep a record of the assumption."
)
DOCUMENT_RECOMMENDATION = (
    "Check that the tender documents include each plan, drawing, calculation or report these "
    "positions refer to; the prices depend on them. Ask a bidder question early for any that "
    "is missing."
)


class RiskSubject(BaseModel):
    """A subject whose cost a clause can put on the bidder: ``pattern`` finds its words."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=120)
    pattern: str
    severity: Severity

    @field_validator("pattern")
    @classmethod
    def _valid_pattern(cls, value: str) -> str:
        return checked_pattern(value, groups=None)


RISK_SUBJECTS = (
    RiskSubject(
        subject="ground",
        label="the ground (soil, rock, obstacles, existing utilities)",
        pattern=GROUND_PATTERN,
        severity=Severity.MEDIUM,
    ),
    RiskSubject(
        subject="water",
        label="water (groundwater, dewatering, surface water)",
        pattern=WATER_PATTERN,
        severity=Severity.MEDIUM,
    ),
    RiskSubject(
        subject="shoring",
        label="shoring and slopes (Verbau, Böschung)",
        pattern=SHORING_PATTERN,
        severity=Severity.MEDIUM,
    ),
    RiskSubject(
        subject="time_weather",
        label="construction time, weather and hindrance",
        pattern=TIME_WEATHER_PATTERN,
        severity=Severity.LOW,
    ),
    RiskSubject(
        subject="interfaces",
        label="work of the client, other trades or third parties",
        pattern=INTERFACES_PATTERN,
        severity=Severity.LOW,
    ),
)

_PATTERN_FIELDS = (
    "note_item_type_pattern",
    "shift_pattern",
    "paid_separately_pattern",
    "assumed_condition_pattern",
    "deferred_decision_pattern",
    "small_material_pattern",
    "open_detail_pattern",
    "lump_sum_item_type_pattern",
    "open_lump_sum_pattern",
    "document_reference_pattern",
)


class BoqClausesConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field holding the position number.")
    description_field: FieldId = plannable(
        "description", description="Field holding the short text (Kurztext)."
    )
    long_description_field: FieldId = plannable(
        "long_description", description="Field holding the long text (Langtext)."
    )
    item_type_field: FieldId = plannable(
        "item_type", description="Field holding the item type (GAEB Positionsart)."
    )
    note_item_type_pattern: str = Field(
        default=NOTE_ITEM_TYPE_PATTERN,
        description="Item types of notes that stand on their own (Hinweis): not item text.",
    )
    risk_subjects: tuple[RiskSubject, ...] = Field(
        default=RISK_SUBJECTS,
        description="Subjects whose cost a clause can put on the bidder, with their severity.",
    )
    shift_pattern: str = Field(
        default=SHIFT_PATTERN,
        description="Phrases that put a cost into the unit price (einzukalkulieren, abgegolten).",
    )
    paid_separately_pattern: str = Field(
        default=PAID_SEPARATELY_PATTERN,
        description="Phrases that pay a subject separately ('wird gesondert vergütet').",
    )
    max_subject_gap_chars: int = Field(
        default=100,
        ge=0,
        le=400,
        description="Most characters between a subject and a shift phrase of one sentence.",
    )
    assumed_condition_pattern: str = Field(
        default=ASSUMED_CONDITION_PATTERN,
        description="Phrases that state a condition as an assumption (vermutlich, vorläufig).",
    )
    deferred_decision_pattern: str = Field(
        default=DEFERRED_DECISION_PATTERN,
        description="Phrases that leave a decision until later (endgültige Festlegung).",
    )
    inclusion_pattern: str = Field(
        default=INCLUSION_PATTERN,
        description="Open-ended inclusions; the one group is the first word of what is included.",
    )
    small_material_pattern: str = Field(
        default=SMALL_MATERIAL_PATTERN,
        description="First words of an inclusion that name small material (not reported).",
    )
    open_detail_pattern: str = Field(
        default=OPEN_DETAIL_PATTERN,
        description="Phrases that leave a detail open (in geeigneter Weise, nach Bedarf).",
    )
    lump_sum_units: tuple[str, ...] = Field(
        default=LUMP_SUM_UNITS,
        description="Unit texts of a lump sum besides the units of the lump sum dimension.",
    )
    lump_sum_item_type_pattern: str = Field(
        default=LUMP_SUM_ITEM_TYPE_PATTERN, description="Item types of a lump sum."
    )
    open_lump_sum_pattern: str = Field(
        default=OPEN_LUMP_SUM_PATTERN,
        description="Phrases that make a lump sum depend on an unknown amount (je Charge).",
    )
    document_reference_pattern: str = Field(
        default=DOCUMENT_REFERENCE_PATTERN,
        description="References to plans, drawings, calculations and reports.",
    )
    max_quotes: int = Field(default=3, ge=1, le=10, description="Clauses quoted in one finding.")
    max_cells_per_issue: int = Field(
        default=20, ge=1, le=200, description="Cells highlighted in one finding."
    )

    @field_validator(*_PATTERN_FIELDS)
    @classmethod
    def _valid_pattern(cls, value: str) -> str:
        return checked_pattern(value, groups=None)

    @field_validator("inclusion_pattern")
    @classmethod
    def _valid_inclusion(cls, value: str) -> str:
        return checked_pattern(value, groups=1)


@dataclass(frozen=True, slots=True)
class _Hit:
    """The first clause of one position that a rule reports: ``phrase`` is the match,
    ``focus`` the span a quote is built around."""

    item: ItemText
    phrase: Phrase
    focus: tuple[int, int]
    detail: str  # the words that made the match, for the evidence


@dataclass(slots=True)
class _Table:
    """What the rules found in one table."""

    table: Table
    risks: dict[str, list[_Hit]]
    assumed: list[list[_Hit]]
    deferred: list[list[_Hit]]
    vague: list[_Hit]
    lump_sums: list[_Hit]
    documents: list[_Hit]


class BoqClausesDetector(Detector[BoqClausesConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_clauses",
        name="Bill clauses (risk, assumptions, vague wording, references)",
        version="1.1.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Reads the short and long texts of a German bill of quantities for clauses a "
            "bidder must price or ask about: costs put into the unit prices (ground, water, "
            "shoring, time and weather, work of others), conditions stated as assumptions, "
            "decisions left until later, open-ended or vague wording, lump sums whose scope "
            "depends on the effort, and references to plans or reports outside the bill."
        ),
        required_fields=("description",),
        optional_fields=("long_description", "item_code", "unit", "item_type"),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the short or the long description.",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING, EvidenceClass.NEEDS_EXTERNAL_CONTEXT),
        issue_categories=(
            CATEGORY_CLAUSE,
            CATEGORY_WORDING,
            CATEGORY_LUMP_SUM,
            CATEGORY_DOCUMENT,
        ),
        limitations=(
            "Clauses are found by German word lists, not understood: a clause worded "
            "otherwise is missed, and a listed word used in another sense can be reported.",
            "Only the texts of positions and of their continuation lines are read; notes and "
            "preliminary texts that stand on their own are not.",
            "Risk-shifting clauses are found where a subject and a shift phrase stand within a "
            "configured distance in one sentence; a clause that spreads over two sentences is "
            "missed.",
        ),
        references=(
            "VOB/A 2019 § 7 (1) Nr. 6 (site conditions must be described)",
            "VOB/B § 2 (6) (claims for additional work are announced before the work starts)",
            "BGH, decision of 18 May 2004, X ZB 7/04 (no costs moved into other positions)",
        ),
        cost="low",
    )
    config_model = BoqClausesConfig

    def required_fields(self, config: BoqClausesConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(self, context: ValidationContext, config: BoqClausesConfig) -> Applicability:
        tables = text_tables(context, _text_fields(config))
        if not tables:
            return Applicability.no("No table maps the short or the long description.")
        return Applicability.yes(f"Item texts are mapped in: {', '.join(t.name for t in tables)}.")

    def validate(self, context: ValidationContext, config: BoqClausesConfig) -> DetectorResult:
        result = DetectorResult()
        stats = MatchStats()
        lump_units = unit_keys(config.lump_sum_units)
        for table in text_tables(context, _text_fields(config)):
            found = _Table(table, {}, [], [], [], [], [])
            for item in item_texts(
                context,
                table,
                _text_fields(config),
                code_field=config.code_field,
                item_type_field=config.item_type_field,
                note_item_type_pattern=config.note_item_type_pattern,
            ):
                if not item.cells:
                    continue
                context.checkpoint()
                result.count(ITEMS_READ)
                lump_sum = is_lump_sum(item, lump_units, config.lump_sum_item_type_pattern)
                self._read_item(config, item, lump_sum, stats, found)
            self._report(context, config, found, result)
        result.count(SENTENCES_READ, stats.sentences)
        result.count(SENTENCES_IN_WINDOWS, stats.long_sentences)
        result.count(SKIPPED_ON_TOKENS, stats.token_matches)
        if stats.long_sentences:
            result.notes.append(
                f"{stats.long_sentences} sentence(s) are longer than the pattern window; they "
                "were searched in overlapping windows, so a clause in one is still found."
            )
        return result

    # ------------------------------------------------------------------ reading
    def _read_item(
        self,
        config: BoqClausesConfig,
        item: ItemText,
        lump_sum: bool,
        stats: MatchStats,
        found: _Table,
    ) -> None:
        risks: dict[str, _Hit] = {}
        assumed: list[_Hit] = []
        deferred: list[_Hit] = []
        vague: list[_Hit] = []
        lump: list[_Hit] = []
        documents: list[_Hit] = []
        for cell, sentence in sentences_of(item, stats):
            for subject, hit in _risk_hits(config, item, cell, sentence, stats):
                risks.setdefault(subject, hit)
            assumed += _hits(config.assumed_condition_pattern, item, cell, sentence, stats)
            deferred += _hits(config.deferred_decision_pattern, item, cell, sentence, stats)
            open_lump = (
                _hits(config.open_lump_sum_pattern, item, cell, sentence, stats) if lump_sum else []
            )
            lump += open_lump
            vague += _inclusions(config, item, cell, sentence, stats)
            taken = {h.phrase.start for h in open_lump}
            vague += [
                hit
                for hit in _hits(config.open_detail_pattern, item, cell, sentence, stats)
                if hit.phrase.start not in taken
            ]
            documents += _hits(config.document_reference_pattern, item, cell, sentence, stats)
        for subject, hit in risks.items():
            found.risks.setdefault(subject, []).append(hit)
        if assumed:
            found.assumed.append(assumed)
        if deferred:
            found.deferred.append(deferred)
        found.vague += vague[:1]
        found.lump_sums += lump[:1]
        found.documents += documents[:1]

    # ------------------------------------------------------------------ reporting
    def _report(
        self,
        context: ValidationContext,
        config: BoqClausesConfig,
        found: _Table,
        result: DetectorResult,
    ) -> None:
        for subject in config.risk_subjects:
            hits = found.risks.get(subject.subject)
            if hits:
                result.add(self._risk_issue(context, config, found.table, subject, hits))
        for rule, groups in ((RULE_ASSUMED, found.assumed), (RULE_DEFERRED, found.deferred)):
            for hits in groups:
                result.add(self._position_issue(context, config, rule, hits))
        if found.vague:
            result.add(self._vague_issue(context, config, found.table, found.vague))
        if found.lump_sums:
            result.add(self._lump_sum_issue(context, config, found.table, found.lump_sums))
        if found.documents:
            result.add(self._document_issue(context, config, found.table, found.documents))

    def _risk_issue(
        self,
        context: ValidationContext,
        config: BoqClausesConfig,
        table: Table,
        subject: RiskSubject,
        hits: list[_Hit],
    ) -> ValidationIssue:
        n = len(hits)
        why = f"{_agree(n, 'position', 'puts')} the cost of {subject.label} into the bidder's unit "
        return self._grouped_issue(
            context,
            config,
            table,
            hits,
            rule_id=RULE_RISK,
            category=CATEGORY_CLAUSE,
            severity=subject.severity,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=f"Cost of {subject.label} put on the bidder in {_count(n, 'position')}",
            lead=why + "prices",
            rule=(
                f"A sentence names {subject.label} and, at most {config.max_subject_gap_chars} "
                "characters from it, a phrase that puts the cost into the unit price (such as "
                "'einzukalkulieren', 'abgegolten' or 'wird nicht gesondert vergütet')."
            ),
            action=RISK_RECOMMENDATION.format(label=subject.label),
            subject=subject.subject,
        )

    def _vague_issue(
        self, context: ValidationContext, config: BoqClausesConfig, table: Table, hits: list[_Hit]
    ) -> ValidationIssue:
        n = len(hits)
        return self._grouped_issue(
            context,
            config,
            table,
            hits,
            rule_id=RULE_VAGUE,
            category=CATEGORY_WORDING,
            severity=Severity.LOW,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=f"Vague wording in {_count(n, 'position')}",
            lead=f"{_agree(n, 'position', 'leaves')} open what is to be supplied or how",
            rule=(
                "Open-ended inclusions ('einschl. aller erforderlichen ...', small material "
                "such as Befestigungsmaterial excepted) and details left open ('in geeigneter "
                "Weise', 'nach Wahl des AN', 'nach Bedarf', 'nach Erfordernis', 'sinngemäß')."
            ),
            action=VAGUE_RECOMMENDATION,
            subject="vague_wording",
        )

    def _lump_sum_issue(
        self, context: ValidationContext, config: BoqClausesConfig, table: Table, hits: list[_Hit]
    ) -> ValidationIssue:
        n = len(hits)
        return self._grouped_issue(
            context,
            config,
            table,
            hits,
            rule_id=RULE_LUMP_SUM,
            category=CATEGORY_LUMP_SUM,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=f"Lump sum with an open scope in {_count(n, 'position')}",
            lead=(
                f"{_agree(n, 'lump sum', 'depends')} on an amount the bill does not fix; a lump "
                "sum is one price for the whole scope, whatever the effort"
            ),
            rule=(
                "A lump sum (unit psch or pauschal, or item type Pauschalposition) whose text "
                "bills by effort, batch or need ('nach tatsächlichem Aufwand', 'je Charge', "
                "'nach Bedarf', 'nach Aufmaß')."
            ),
            action=LUMP_SUM_RECOMMENDATION,
            subject="open_lump_sum",
        )

    def _document_issue(
        self, context: ValidationContext, config: BoqClausesConfig, table: Table, hits: list[_Hit]
    ) -> ValidationIssue:
        n = len(hits)
        return self._grouped_issue(
            context,
            config,
            table,
            hits,
            rule_id=RULE_DOCUMENT,
            category=CATEGORY_DOCUMENT,
            severity=Severity.INFO,
            evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            title=f"{_agree(n, 'position', 'refers')} to plans, drawings or reports",
            lead=(
                f"{_agree(n, 'position', 'refers')} to documents that are not part of this bill, "
                f"so the bill alone cannot show what {'it asks' if n == 1 else 'they ask'} for"
            ),
            rule=(
                "A reference such as 'gemäß Zeichnung', 'lt. Gutachten', 'siehe Lageplan' or "
                "'siehe Anlage 4'."
            ),
            action=DOCUMENT_RECOMMENDATION,
            subject="document_reference",
        )

    def _grouped_issue(
        self,
        context: ValidationContext,
        config: BoqClausesConfig,
        table: Table,
        hits: list[_Hit],
        *,
        rule_id: str,
        category: str,
        severity: Severity,
        evidence_class: EvidenceClass,
        title: str,
        lead: str,
        rule: str,
        action: str,
        subject: str,
    ) -> ValidationIssue:
        """One finding for a table: quotes of the first clauses, every position listed."""
        quoted = hits[: config.max_quotes]
        cells = cell_refs(context, [hit.phrase for hit in hits], config.max_cells_per_issue)
        labels = [hit.item.label for hit in hits]
        explanation = f"{lead}: {_quotes(quoted)}."
        if len(hits) > len(quoted):
            explanation += f" All positions: {positions_list(labels)}."
        return context.issues.create(
            self.spec,
            rule_id=rule_id,
            category=category,
            severity=severity,
            evidence_class=evidence_class,
            title=clip(title, 200),
            explanation=explanation,
            table=table,
            cells=cells,
            evidence=[
                *(_quote_evidence(context, hit) for hit in quoted),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Clause rule",
                    detail=rule,
                    data={"rule_id": rule_id, "subject": subject, "positions": len(hits)},
                ),
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Positions",
                    detail=clip(positions_list(labels), 2000),
                    cells=cells,
                    data={"positions": len(hits)},
                ),
            ],
            suggested_action=action,
            subject=subject,
        )

    def _position_issue(
        self,
        context: ValidationContext,
        config: BoqClausesConfig,
        rule_id: str,
        hits: list[_Hit],
    ) -> ValidationIssue:
        item = hits[0].item
        quoted = _unique_sentences(hits)[: config.max_quotes]
        words = positions_list([f"'{clip(hit.phrase.matched, 60)}'" for hit in hits[:3]])
        if rule_id == RULE_ASSUMED:
            title = f"{item.label} assumes a condition: {words}"
            lead = (
                f"{item.label} describes the work on an assumption ({words}), and its price "
                "rests on it"
            )
            rule = (
                "Phrases that state a condition as an assumption: 'vermutlich', "
                "'voraussichtlich', 'mutmaßlich', 'vorläufig ermittelt', 'nach derzeitigem "
                "Kenntnisstand', 'Untersuchungsergebnisse liegen noch nicht vor', 'eventuell "
                "auftretend'."
            )
        else:
            title = f"{item.label} leaves a decision until later: {words}"
            lead = (
                f"{item.label} leaves a decision about the work until later ({words}); the price "
                "rests on what the bill describes now"
            )
            rule = (
                "Phrases that defer a decision: 'endgültige Festlegung', 'endgültige "
                "Entscheidung', 'erst nach ... festgelegt', 'wird erst vor Ort festgelegt'."
            )
        cells = cell_refs(context, [hit.phrase for hit in hits], config.max_cells_per_issue)
        return context.issues.create(
            self.spec,
            rule_id=rule_id,
            category=CATEGORY_CLAUSE,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(title, 200),
            explanation=f"{lead}: {_quotes(quoted, with_label=False)}.",
            table=item.table,
            row=item.row,
            cells=cells,
            evidence=[
                *(_quote_evidence(context, hit) for hit in quoted),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Clause rule",
                    detail=rule,
                    data={"rule_id": rule_id},
                ),
            ],
            suggested_action=ASSUMPTION_RECOMMENDATION,
        )


# ---------------------------------------------------------------------------- matching
def _text_fields(config: BoqClausesConfig) -> tuple[str, ...]:
    return (config.description_field, config.long_description_field)


def _hits(
    pattern: str, item: ItemText, cell: TextCell, sentence: Sentence, stats: MatchStats
) -> list[_Hit]:
    return [
        _Hit(item=item, phrase=phrase, focus=(phrase.start, phrase.end), detail=phrase.matched)
        for phrase in find_in_sentence(pattern, cell, sentence, stats)
    ]


def _inclusions(
    config: BoqClausesConfig, item: ItemText, cell: TextCell, sentence: Sentence, stats: MatchStats
) -> list[_Hit]:
    """Open-ended inclusions whose first included word is not small material."""
    hits = []
    for phrase in find_in_sentence(config.inclusion_pattern, cell, sentence, stats):
        included = (phrase.captured or "").strip(" ,.;:")
        if included and patterns.search(config.small_material_pattern, included) is None:
            hits.append(
                _Hit(item=item, phrase=phrase, focus=(phrase.start, phrase.end), detail=included)
            )
    return hits


def _risk_hits(
    config: BoqClausesConfig,
    item: ItemText,
    cell: TextCell,
    sentence: Sentence,
    stats: MatchStats,
) -> list[tuple[str, _Hit]]:
    """``(subject, hit)`` for each subject this sentence puts on the bidder."""
    shifts = find_in_sentence(config.shift_pattern, cell, sentence, stats)
    if not shifts:
        return []
    paid = find_in_sentence(config.paid_separately_pattern, cell, sentence)
    hits: list[tuple[str, _Hit]] = []
    for subject in config.risk_subjects:
        for word in find_in_sentence(subject.pattern, cell, sentence, stats):
            if _paid_separately(cell.text, word, paid):
                continue
            shift = _nearest_shift(cell.text, word, shifts, config.max_subject_gap_chars)
            if shift is None:
                continue
            focus = (min(word.start, shift.start), max(word.end, shift.end))
            detail = f"{word.matched} ... {shift.matched}"
            hits.append((subject.subject, _Hit(item=item, phrase=word, focus=focus, detail=detail)))
            break
    return hits


def _nearest_shift(text: str, word: Phrase, shifts: Sequence[Phrase], gap: int) -> Phrase | None:
    """The shift phrase closest to ``word`` within ``gap`` characters. A word before a shift
    phrase that opens a list (a colon follows it) does not count: the list follows."""
    best: tuple[int, Phrase] | None = None
    for shift in shifts:
        if word.end <= shift.start:
            if _opens_list(text, shift):
                continue
            distance = shift.start - word.end
        elif shift.end <= word.start:
            distance = word.start - shift.end
        else:
            distance = 0
        if distance <= gap and (best is None or distance < best[0]):
            best = (distance, shift)
    return None if best is None else best[1]


def _opens_list(text: str, shift: Phrase) -> bool:
    following = text[shift.end : shift.end + 3].lstrip()
    return following.startswith(":")


def _paid_separately(text: str, word: Phrase, paid: Sequence[Phrase]) -> bool:
    """Whether ``word`` is the subject of a "wird gesondert vergütet" phrase right after it."""
    return any(
        0 <= phrase.start - word.end <= 40
        and not any(c in ",;:" for c in text[word.end : phrase.start])
        for phrase in paid
    )


# ---------------------------------------------------------------------------- formatting
def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _agree(n: int, noun: str, verb: str) -> str:
    """The count, its noun and a verb in the third person that agrees with it: "1 position
    refers", "3 positions refer" (``verb`` is the singular form, ending in "s")."""
    return f"{_count(n, noun)} {verb if n == 1 else verb.removesuffix('s')}"


def _quotes(hits: Sequence[_Hit], *, with_label: bool = True) -> str:
    parts = []
    for hit in hits:
        quote = f'"{excerpt(hit.phrase, hit.focus)}"'
        parts.append(f"{hit.item.label} {quote}" if with_label else quote)
    return "; ".join(parts)


def _quote_evidence(context: ValidationContext, hit: _Hit) -> EvidenceItem:
    cell = context.cell_ref(hit.phrase.cell.table, hit.phrase.row, hit.phrase.cell.field_id)
    return EvidenceItem(
        kind=EvidenceKind.VALUE,
        label=f"Clause in {hit.item.label}",
        detail=f'"{excerpt(hit.phrase, hit.focus)}"',
        cells=[cell],
        data={"item_code": hit.item.label, "matched": clip(hit.detail, 120)},
    )


def _unique_sentences(hits: Sequence[_Hit]) -> list[_Hit]:
    """The hits of a position, one per sentence."""
    seen: set[tuple[str, str, int]] = set()
    unique = []
    for hit in hits:
        key = (hit.phrase.cell.row.row_id, hit.phrase.cell.field_id, hit.phrase.sentence.start)
        if key not in seen:
            seen.add(key)
            unique.append(hit)
    return unique
