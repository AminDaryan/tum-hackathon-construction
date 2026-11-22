"""Companion work: work a bill describes without the work that has to go with it.

Read as the bidder pricing a client's tender. Each companion pair names trigger work and its
companion; a trigger item whose companion is named neither in its own text nor in another
item of the bill is listed. One finding per table and pair, listing every trigger position:

* ``penetration_without_seal``: wall penetrations (core holes, wall ducts, sleeves, building
  entries) whose own text names no seal or firestop and no item of the bill seals them.
* ``site_equipment_without_upkeep``: site equipment that is set up and cleared (Bauzaun,
  Container, Baustraße, ...) with no item in the same top-level section (the first OZ
  segment) that keeps the same equipment on site (vorhalten) or is priced per unit of time.
* ``pipe_without_pressure_test``: pressure or drinking-water pipes laid with no pressure or
  leak test named anywhere in the bill.
* ``trench_without_backfill``: trench or pit excavation with no backfill named anywhere in
  the bill.

Severity medium, evidence ``semantic_warning``: the check reads wording, and a companion can
be priced in a position the wording does not reveal. Finding category (for the category
table): ``domain.boq_companion_work -> omission`` for every rule.

A pair is skipped on a bill whose items have no Langtext at all (a bid file with Kurztexts
only would otherwise flag nearly every trigger); the run notes it. Rows are read directly,
not through the item frame, see :mod:`._bill_text`. The pairs are detector configuration
with the defaults below, measured on five sample bills before the GAEB import read them; a
profile can replace them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import Field, field_validator, model_validator

from app.models.base import FrozenModel
from app.models.issue import (
    RULE_ID_PATTERN,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType
from app.profiles.units import unit_key
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
    Bill,
    BillFields,
    Entry,
    description_applicability,
    entry_cells,
    list_codes,
    read_bill,
    search,
)

RULE_PENETRATION = "penetration_without_seal"
RULE_SITE_EQUIPMENT = "site_equipment_without_upkeep"
RULE_PRESSURE_TEST = "pipe_without_pressure_test"
RULE_BACKFILL = "trench_without_backfill"
CATEGORY = "companion_work"
MAX_QUOTES = 3

TABLES_SKIPPED_NO_LONG_TEXTS = "tables_skipped_no_long_texts"
ITEMS_READ = "items_read"  # items of the tables whose pairs were checked
TRIGGER_ITEMS = "trigger_items"
TRIGGERS_SATISFIED_OWN_TEXT = "triggers_satisfied_by_own_text"
TRIGGERS_SATISFIED_ELSEWHERE = "triggers_satisfied_by_bill_text"

# Umlauts as written or transliterated.
_UE, _AE, _OE, _SS = "(?:ü|ue)", "(?:ä|ae)", "(?:ö|oe)", "(?:ß|ss)"


class CompanionText(StrEnum):
    """Where other entries are searched for the companion."""

    ITEM_DESCRIPTIONS = "item_descriptions"  # the Kurztext of items
    ALL_TEXTS = "all_texts"  # Kurz- and Langtext of items and notes


class CompanionScope(StrEnum):
    """Which entries can name the companion of a trigger item."""

    BILL = "bill"
    TOP_SECTION = "top_section"  # the items whose OZ starts with the same first segment


class TriggerTerm(FrozenModel):
    """One kind of trigger work: ``pattern`` searched in the Kurztext."""

    name: str = Field(min_length=1, max_length=60)
    pattern: str

    @field_validator("pattern")
    @classmethod
    def _valid_pattern(cls, value: str) -> str:
        return checked_pattern(value, groups=None)


class CompanionPair(FrozenModel):
    """Trigger work and the companion that must go with it.

    A trigger item's Kurztext matches one of ``triggers`` and every ``trigger_requires``
    pattern, and not ``trigger_exclude``. It is satisfied when its own Kurz- or Langtext
    matches ``own_text_pattern``, or when an entry in ``scope`` matches
    ``companion_pattern`` in its ``companion_text`` (with ``companion_same_term``: and names
    the same trigger term in its Kurztext; with ``companion_time_unit``: or is priced in a
    unit of time and names the same term). Patterns are case-insensitive."""

    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    described: str = Field(min_length=1, max_length=200)
    missing: str = Field(min_length=1, max_length=300)
    companion_words: str = Field(min_length=1, max_length=300)
    triggers: tuple[TriggerTerm, ...] = Field(min_length=1)
    trigger_requires: tuple[str, ...] = ()
    trigger_exclude: str | None = None
    own_text_pattern: str | None = None
    companion_pattern: str
    companion_text: CompanionText = CompanionText.ALL_TEXTS
    companion_same_term: bool = False
    companion_time_unit: bool = False
    scope: CompanionScope = CompanionScope.BILL
    severity: Severity = Severity.MEDIUM
    recommendation: str = Field(min_length=1, max_length=600)

    @field_validator("trigger_exclude", "own_text_pattern", "companion_pattern")
    @classmethod
    def _valid_pattern(cls, value: str | None) -> str | None:
        return None if value is None else checked_pattern(value, groups=None)

    @field_validator("trigger_requires")
    @classmethod
    def _valid_patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(checked_pattern(pattern, groups=None) for pattern in value)

    @model_validator(mode="after")
    def _unique_terms(self) -> CompanionPair:
        names = [term.name for term in self.triggers]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.rule_id}: trigger term names must be unique")
        return self


_ASK_PAYER = (
    "If none pays for it, this may become a change order after award, subject to the contract."
)

PENETRATION_PAIR = CompanionPair(
    rule_id=RULE_PENETRATION,
    title="Wall penetrations without a seal",
    described="pipes passing through walls (core holes, wall ducts or sleeves)",
    missing="no position seals them",
    companion_words=(
        "Ringraumdichtung, Dichtungseinsatz, Link-Seal, Pressio, Mediendurchführung, "
        "Durchführungsdichtung, gas-/wasserdicht, Brandschott, Abschottung, "
        "Brandschutzmanschette"
    ),
    triggers=(
        TriggerTerm(
            name="Wanddurchführung",
            pattern=(
                rf"kern(?:loch)?bohrung|wanddurchf{_UE}hrung|mauerdurchf{_UE}hrung|futterrohr"
                rf"|hauseinf{_UE}hrung|geb{_AE}udeeinf{_UE}hrung"
            ),
        ),
    ),
    # Removing or closing a penetration, sealing it, or the core drill itself.
    trigger_exclude=(
        rf"\b(?:ausbau|ausbauen|r{_UE}ckbau|r{_UE}ckbauen|demontage|demontieren"
        rf"|verschlie{_SS}en|verf{_UE}llen|abdichten)\b|kernbohrger"
    ),
    own_text_pattern=(
        rf"ringraum|dichtungseinsatz|link-?seal|pressio|mediendurchf{_UE}hrung"
        rf"|durchf{_UE}hrungsdichtung|(?:gas|wasser|druckwasser)dicht"
        rf"|gas-\s*(?:und|u\.|/)\s*(?:druck)?wasserdicht|brandschott|abschottung"
        rf"|brandschutzmanschette"
    ),
    companion_pattern=(
        rf"ringraumdichtung|dichtungseinsatz|link-?seal|mediendurchf{_UE}hrung"
        rf"|durchf{_UE}hrungsdichtung|brandschott|abschottung|brandschutzmanschette"
    ),
    companion_text=CompanionText.ITEM_DESCRIPTIONS,
    recommendation=(
        "Ask a bidder question: which position pays for sealing these wall penetrations "
        "(gas- and watertight annular seals, or firestopping in a fire-rated wall)? Do not "
        f"add a position to the bill. {_ASK_PAYER}"
    ),
)

SITE_EQUIPMENT_PAIR = CompanionPair(
    rule_id=RULE_SITE_EQUIPMENT,
    title="Site equipment set up and cleared, but not kept on site",
    described="site equipment that is set up and cleared",
    missing=(
        "no position in the same section keeps that equipment on site (vorhalten) or is "
        "priced per unit of time"
    ),
    companion_words="vorhalten, Vorhaltung, unterhalten, Unterhaltung, or a unit of time",
    triggers=(
        TriggerTerm(name="Bauzaun", pattern=rf"bauz{_AE}un(?:e|en)?\b|bauzaun\w*"),
        TriggerTerm(
            name="Absperrung", pattern=r"absperrung(?:en)?\b|absperrgitter|absperrschranke"
        ),
        TriggerTerm(name="Container", pattern=r"container"),
        TriggerTerm(name="Baustraße", pattern=rf"baustra{_SS}e"),
        TriggerTerm(name="Überfahrt", pattern=rf"{_UE}berfahrt"),
        TriggerTerm(name="Beleuchtung", pattern=r"beleuchtung|warnleuchte"),
        TriggerTerm(name="Verkehrszeichen", pattern=r"verkehrszeichen|beschilderung"),
        TriggerTerm(name="Schutzgerüst", pattern=rf"schutzger{_UE}st"),
        TriggerTerm(name="Rohrbrücke", pattern=rf"rohrbr{_UE}cke"),
        TriggerTerm(name="Baustellenampel", pattern=r"baustellenampel|lichtsignalanlage"),
    ),
    trigger_requires=(
        r"\b(?:aufstellen|herstellen|einrichten|errichten|aufbauen|montieren)\b",
        rf"\b(?:r{_AE}umen|beseitigen|abbauen|entfernen|r{_UE}ckbauen|demontieren)\b",
    ),
    companion_pattern=(
        r"\b(?:vorhalten|vorhaltung|vorhaltezeit|vorhaltedauer|unterhalten|unterhaltung)\b"
    ),
    companion_text=CompanionText.ITEM_DESCRIPTIONS,
    companion_same_term=True,
    companion_time_unit=True,
    scope=CompanionScope.TOP_SECTION,
    recommendation=(
        "Ask a bidder question: which position pays for keeping this equipment on site "
        "(vorhalten) for the construction period? Price the set-up and clearing as the "
        "positions describe them, and never price the upkeep into other positions "
        f"(BGH, X ZB 7/04). {_ASK_PAYER}"
    ),
)

PRESSURE_TEST_PAIR = CompanionPair(
    rule_id=RULE_PRESSURE_TEST,
    title="Pressure pipes without a pressure test",
    described="laying pressure or drinking-water pipes",
    missing="no text of the bill names a pressure or leak test",
    companion_words="Druckprüfung, Druckprobe, Dichtheitsprüfung, Dichtigkeitsprüfung",
    triggers=(
        TriggerTerm(
            name="Druckrohrleitung",
            pattern=(
                rf"druckrohr(?:leitung)?|trinkwasserleitung|wasserleitung"
                rf"|k{_AE}ltefernleitung|fernk{_AE}lteleitung|wasserltg|druckleitung"
            ),
        ),
    ),
    trigger_requires=(r"\bverleg|\beinbau|\bmontier",),
    companion_pattern=(
        rf"druckpr{_UE}fung|druckprobe|dichtheitspr{_UE}fung|dichtheitsprobe"
        rf"|dichtigkeitspr{_UE}fung|dichtigkeitsprobe"
    ),
    recommendation=(
        "Ask a bidder question: which position pays for the pressure test of these pipes "
        f"(and its records)? Do not add a position to the bill. {_ASK_PAYER}"
    ),
)

BACKFILL_PAIR = CompanionPair(
    rule_id=RULE_BACKFILL,
    title="Excavation without backfill",
    described="trench or pit excavation",
    missing="no text of the bill names backfilling",
    companion_words=(
        "verfüllen, Verfüllung, Rückverfüllung, Wiederverfüllung, Leitungszone, "
        "Hinterfüllung, einbauen und verdichten"
    ),
    triggers=(
        TriggerTerm(
            name="Graben",
            pattern=(
                r"rohrgr(?:a|ä|ae)ben|leitungsgr(?:a|ä|ae)ben|kabelgr(?:a|ä|ae)ben|baugrube"
                r"|\bgr(?:a|ä|ae)ben\b"
            ),
        ),
    ),
    trigger_requires=(rf"aushub|ausheben|\bl{_OE}sen|ausschachten|herstellen",),
    companion_pattern=(
        rf"verf{_UE}ll|leitungszone|hinterf{_UE}ll|(?:wieder)?anf{_UE}ll"
        r"|einbauen,?\s+(?:und\s+)?verdichten|\bboden\b(?:\W+\w+){0,4}?\W+einbauen"
    ),
    recommendation=(
        "Ask a bidder question: which position pays for backfilling and compacting the "
        f"excavation? Do not add a position to the bill. {_ASK_PAYER}"
    ),
)

DEFAULT_PAIRS = (PENETRATION_PAIR, SITE_EQUIPMENT_PAIR, PRESSURE_TEST_PAIR, BACKFILL_PAIR)


class CompanionWorkConfig(DetectorConfig):
    description_field: FieldId = plannable("description", description="Kurztext field.")
    long_description_field: FieldId = plannable("long_description", description="Langtext field.")
    item_code_field: FieldId = plannable("item_code", description="OZ field.")
    pairs: tuple[CompanionPair, ...] = Field(
        default=DEFAULT_PAIRS,
        description="Trigger work and the companion it needs (profile-controlled).",
    )
    time_dimensions: tuple[str, ...] = Field(
        default=("time", "count_time", "area_time"),
        description="Unit dimensions that price per unit of time (vorhalten per week).",
    )
    time_unit_texts: tuple[str, ...] = Field(
        default=("mwo", "mxwo", "md", "mxd", "m2d", "sttag", "stxtag"),
        description="Unit texts that price per unit of time but are not in the profile's unit "
        "list (compared as unit keys: case, spaces and dots ignored, m² as m2).",
    )
    max_cells_per_issue: int = Field(
        default=20, ge=1, le=200, description="Rows highlighted in one finding."
    )

    @field_validator("time_unit_texts")
    @classmethod
    def _unit_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(unit_key(text) for text in value)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> CompanionWorkConfig:
        ids = [pair.rule_id for pair in self.pairs]
        if len(set(ids)) != len(ids):
            raise ValueError("companion pairs must have unique rule ids")
        return self


class CompanionWorkDetector(Detector[CompanionWorkConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_companion_work",
        name="Companion work (BoQ)",
        version="1.0.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Lists work a bill of quantities describes without the work that goes with it: "
            "wall penetrations without a seal, site equipment set up and cleared but not kept "
            "on site, pressure pipes without a pressure test, excavation without backfill. "
            "One finding per bill and pair, listing the positions."
        ),
        required_fields=("description",),
        optional_fields=("long_description", "item_code", "unit"),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the item description (Kurztext).",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(CATEGORY,),
        limitations=(
            "Reads German wording only; the companion can be priced in a position whose "
            "wording does not name it, so every finding needs a reviewer.",
            "A bill whose items have no Langtext is not checked (a bid file with Kurztexts "
            "only names too little).",
            "The default word lists were measured on five sample bills; other bills may "
            "word the same work differently.",
        ),
        cost="low",
    )
    config_model = CompanionWorkConfig

    def required_fields(self, config: CompanionWorkConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(
        self, context: ValidationContext, config: CompanionWorkConfig
    ) -> Applicability:
        found = description_applicability(context, config.description_field)
        if found.applicable and not config.pairs:
            return Applicability.no("The profile configures no companion pairs.")
        return found

    def validate(self, context: ValidationContext, config: CompanionWorkConfig) -> DetectorResult:
        result = DetectorResult()
        fields = BillFields(
            config.description_field, config.long_description_field, config.item_code_field
        )
        for table in context.tables():
            if not context.has_fields(table, config.description_field):
                continue
            bill = read_bill(context, table, fields)
            if not bill.items:
                continue
            if not bill.has_long_texts:
                result.count(TABLES_SKIPPED_NO_LONG_TEXTS)
                result.notes.append(
                    f"'{table.name}': no item has a Langtext, so companion work was not "
                    "checked (a bill with Kurztexts only names too little)."
                )
                continue
            result.count(ITEMS_READ, len(bill.items))
            for pair in config.pairs:
                context.checkpoint()
                missing = self._missing(context, config, bill, pair, result)
                if missing:
                    result.add(self._issue(context, config, bill, pair, missing))
        return result

    def _missing(
        self,
        context: ValidationContext,
        config: CompanionWorkConfig,
        bill: Bill,
        pair: CompanionPair,
        result: DetectorResult,
    ) -> list[tuple[Entry, TriggerTerm]]:
        triggers: list[tuple[Entry, TriggerTerm]] = []
        for item in bill.items:
            term = _trigger_term(pair, item)
            if term is None:
                continue
            result.count(TRIGGER_ITEMS)
            if pair.own_text_pattern and search(pair.own_text_pattern, item.text):
                result.count(TRIGGERS_SATISFIED_OWN_TEXT)
                continue
            triggers.append((item, term))
        if not triggers:
            return []
        # Entries that name the companion: their scope and the trigger terms they name.
        candidates = (
            bill.items if pair.companion_text is CompanionText.ITEM_DESCRIPTIONS else bill.entries
        )
        companions: list[tuple[str | None, frozenset[str]]] = []
        for entry in candidates:
            text = (
                entry.short
                if pair.companion_text is CompanionText.ITEM_DESCRIPTIONS
                else entry.text
            )
            named = search(pair.companion_pattern, text) is not None
            if not named and pair.companion_time_unit and entry.is_item:
                named = _priced_per_time(context, config, entry)
            if not named:
                continue
            terms = frozenset(
                term.name
                for term in pair.triggers
                if not pair.companion_same_term or search(term.pattern, entry.short)
            )
            companions.append((entry.top_section, terms))
        missing: list[tuple[Entry, TriggerTerm]] = []
        for item, term in triggers:
            scope = item.top_section if pair.scope is CompanionScope.TOP_SECTION else None
            if any(
                (scope is None or companion_scope == scope) and term.name in terms
                for companion_scope, terms in companions
            ):
                result.count(TRIGGERS_SATISFIED_ELSEWHERE)
                continue
            missing.append((item, term))
        return missing

    def _issue(
        self,
        context: ValidationContext,
        config: CompanionWorkConfig,
        bill: Bill,
        pair: CompanionPair,
        missing: list[tuple[Entry, TriggerTerm]],
    ) -> ValidationIssue:
        items = [item for item, _ in missing]
        cells = entry_cells(context, items, config.description_field, config.max_cells_per_issue)
        quotes = "; ".join(f'{item.label} "{item.quote_short(160)}"' for item in items[:MAX_QUOTES])
        terms = sorted({term.name for _, term in missing})
        noun, verb = ("position", "describes") if len(items) == 1 else ("positions", "describe")
        listed = list_codes(items)
        return context.issues.create(
            self.spec,
            rule_id=pair.rule_id,
            category=CATEGORY,
            severity=pair.severity,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=clip(f"{pair.title}: {len(items)} {noun}", 200),
            explanation=(
                f"{len(items)} {noun} of this bill {verb} {pair.described}, and "
                f"{pair.missing}: {quotes}"
                + (f" (all {len(items)}: {listed})" if len(items) > MAX_QUOTES else "")
                + f". Searched the bill for: {pair.companion_words}. This is an advisory "
                "warning: the work may be priced in a position whose wording does not name it."
            ),
            table=bill.table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Positions without the companion work",
                    detail=clip(f"{listed} ({', '.join(terms)})", 2000),
                    cells=cells,
                    data={"positions": len(items)},
                ),
                EvidenceItem(
                    kind=EvidenceKind.RULE,
                    label="Companion searched for",
                    detail=pair.companion_words,
                ),
            ],
            suggested_action=pair.recommendation,
            subject=pair.rule_id,
        )


def _trigger_term(pair: CompanionPair, item: Entry) -> TriggerTerm | None:
    term = next((t for t in pair.triggers if search(t.pattern, item.short)), None)
    if term is None:
        return None
    if any(search(pattern, item.short) is None for pattern in pair.trigger_requires):
        return None
    if pair.trigger_exclude and search(pair.trigger_exclude, item.short):
        return None
    return term


def _priced_per_time(context: ValidationContext, config: CompanionWorkConfig, entry: Entry) -> bool:
    lookup = context.unit(entry.table, entry.row)
    if lookup is not None:
        return lookup.unit.dimension in config.time_dimensions
    field = context.unit_field_id()
    text = context.text(entry.table, entry.row, field) if field else None
    return text is not None and unit_key(text) in config.time_unit_texts
