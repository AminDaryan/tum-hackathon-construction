"""The risk tables: typed configuration loaded from ``app/risk/data/<profile_id>/*.yaml``.

Every word list, pattern, threshold, tier rule and text of the risk module lives in these
files, not in code (the team rule "no business rules in generic code"). Loading validates the
shape of every file (unknown keys fail), compiles every pattern and checks the references
between the files, so a typo fails at start-up or in the tests, never during a run.

Patterns are applied to folded text (lower case, umlauts spelled out): umlauts written in a
pattern are folded here, when the table is loaded.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator

from app.core.errors import InvalidInputError
from app.core.patterns import compile_pattern
from app.models.base import FrozenModel
from app.models.issue import Severity
from app.models.values import ExactDecimal
from app.risk.models import Certainty, Direction, Harm, Method, MoneyKind, Priority, State
from app.risk.text import fold, fold_pattern

DATA_DIR = Path(__file__).resolve().parent / "data"
OTHER = "other"


def _patterns(values: list[str]) -> list[str]:
    folded = [fold_pattern(value) for value in values]
    for pattern in folded:
        compile_pattern(pattern)  # ValueError for an invalid pattern
    return folded


def _pattern(value: str | None) -> str | None:
    return None if value is None else _patterns([value])[0]


def _stems(values: list[str]) -> list[str]:
    stems = [fold(value) for value in values]
    if any(not stem for stem in stems):
        raise ValueError("empty word in a word list")
    return stems


class _Table(FrozenModel):
    version: str


# ----------------------------------------------------------------------------- catalogue
class RiskType(FrozenModel):
    id: str = Field(pattern=r"^(R\d{3}|other)$")
    name: str
    detect: str
    category: str
    priority: Priority
    harm: Harm
    direction: Direction
    methods: list[str] = Field(default_factory=list)
    flag_needs: list[str] = Field(default_factory=list)
    confirm_needs: list[str] = Field(default_factory=list)
    confirm_basis: str


class Catalogue(_Table):
    risk_types: list[RiskType] = Field(min_length=1)
    other: RiskType

    @model_validator(mode="after")
    def _unique(self) -> Catalogue:
        ids = [t.id for t in self.risk_types]
        if len(ids) != len(set(ids)) or OTHER in ids or self.other.id != OTHER:
            raise ValueError("risk type ids must be unique, and 'other' is the fallback entry")
        return self


# ----------------------------------------------------------------------------- components
class KeyPattern(FrozenModel):
    kind: Literal["building", "storey", "room", "axis", "component", "system"]
    pattern: str
    value: str = "{1}"

    @field_validator("pattern")
    @classmethod
    def _fold(cls, value: str) -> str:
        return _patterns([value])[0]


class Components(_Table):
    keys: list[KeyPattern]
    references: list[str]
    included_phrases: list[str]
    separate_phrases: list[str]
    by_others_phrases: list[str]
    abbreviations: list[str]

    @field_validator("references")
    @classmethod
    def _fold_references(cls, value: list[str]) -> list[str]:
        return _patterns(value)

    @field_validator("included_phrases", "separate_phrases", "by_others_phrases", "abbreviations")
    @classmethod
    def _fold_words(cls, value: list[str]) -> list[str]:
        return _stems(value)


# ----------------------------------------------------------------------------- context
class ContextTables(_Table):
    min_share: ExactDecimal = Field(gt=0, le=1)
    project_types: dict[str, list[str]]
    trades: dict[str, list[str]]

    @field_validator("project_types", "trades")
    @classmethod
    def _fold_lists(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return {name: _stems(words) for name, words in value.items()}


# ----------------------------------------------------------------------------- dependencies
Scope = Literal["component", "section", "project"]
OnMissing = Literal["question", "signal"]


class DependencyDefaults(FrozenModel):
    scope: Scope
    link_by: list[str]
    on_missing: OnMissing
    # Whole words that, at most two words before a trigger word, say it is absent ("kein
    # Grundwasser"): the position does not trigger the rule.
    negations_any: list[str] = Field(default_factory=list)
    # A reference to another document ("siehe Anlage A-01", "gemäß Bewehrungsplan"), with the
    # document's name in the group ``document``: a position that names the expected work in a
    # clause with one leaves the work to that document, which this run does not have.
    document_pattern: str | None = None

    @field_validator("negations_any")
    @classmethod
    def _fold_words(cls, value: list[str]) -> list[str]:
        return _stems(value)

    @field_validator("document_pattern")
    @classmethod
    def _document_group(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "document" not in re.compile(value).groupindex:
            raise ValueError("document_pattern needs a group named 'document'")
        return _patterns([value])[0]


class DependencyRule(FrozenModel):
    """ "If the bill has A, the same scope should also have B" (see dependencies.yaml)."""

    id: str = Field(pattern=r"^D\d{2}$")
    risk_type: str
    context: list[str] = Field(default_factory=list)
    if_any: list[str] = Field(default_factory=list)
    if_pattern: str | None = None
    and_any: list[str] = Field(default_factory=list)
    expect_any: list[str] = Field(default_factory=list)
    # The expected work as a person names it, for titles and questions: the search stems are
    # word fragments ("entsorg") and do not read as text.
    expect_label: str = Field(min_length=1)
    expect_pattern: str | None = None
    unless: list[str] = Field(default_factory=list)
    scope: Scope | None = None
    on_missing: OnMissing | None = None
    link_by: list[str] | None = None
    harm: Harm | None = None
    depth_pattern: str | None = None
    depth_use: str | None = None
    depth_over_m: ExactDecimal | None = None
    # Words that make the depth threshold irrelevant ("Boden nicht standsicher"): the position
    # triggers the rule at any depth.
    regardless_of_depth_any: list[str] = Field(default_factory=list)
    weight_pattern: str | None = None
    open_pattern: str | None = None
    open_means: str | None = None
    note: str | None = None

    @field_validator("if_any", "and_any", "expect_any", "unless", "regardless_of_depth_any")
    @classmethod
    def _fold_words(cls, value: list[str]) -> list[str]:
        return _stems(value)

    @field_validator(
        "if_pattern", "expect_pattern", "depth_pattern", "weight_pattern", "open_pattern"
    )
    @classmethod
    def _fold_patterns(cls, value: str | None) -> str | None:
        return _pattern(value)

    @model_validator(mode="after")
    def _complete(self) -> DependencyRule:
        if not self.if_any and self.if_pattern is None:
            raise ValueError(f"{self.id}: needs if_any or if_pattern")
        if not self.expect_any and self.expect_pattern is None:
            raise ValueError(f"{self.id}: needs expect_any or expect_pattern")
        if (self.depth_pattern is None) != (self.depth_over_m is None):
            raise ValueError(f"{self.id}: depth_pattern and depth_over_m go together")
        return self


class Dependencies(_Table):
    defaults: DependencyDefaults
    rules: list[DependencyRule]


# ----------------------------------------------------------------------------- attributes
class AttributeKind(FrozenModel):
    """ "Items of this kind must state these values" (see attributes.yaml)."""

    id: str = Field(pattern=r"^A\d{2}b?$")
    risk_type: str
    when_any: list[str] = Field(min_length=1)
    unless_any: list[str] = Field(default_factory=list)
    and_any: list[str] = Field(default_factory=list)
    near_word: str | None = None
    # Words of other work or of another type of the component ("Unterquerung bestehender
    # Kabel", "Antenne mit Kabel", "Kabelgraben"): a component word they qualify does not make
    # the item of this kind, and a value next to it does not count.
    other_work_any: list[str] = Field(default_factory=list)
    # Other components or work steps a nearby value may belong to ("Schacht DN 1000", "Rohre
    # nach DIN EN 12201 liefern"): a value they claim does not count for the component.
    other_parts_any: list[str] = Field(default_factory=list)
    # "near": a value counts within `near` characters of the component word. "clause": anywhere
    # in the component word's clause, tied to it by word order (a test and the standard it
    # follows).
    link: Literal["near", "clause"] = "near"
    required: dict[str, str] = Field(min_length=1)
    note: str | None = None

    @field_validator("when_any", "unless_any", "and_any", "other_work_any", "other_parts_any")
    @classmethod
    def _fold_words(cls, value: list[str]) -> list[str]:
        return _stems(value)

    @field_validator("near_word")
    @classmethod
    def _fold_near(cls, value: str | None) -> str | None:
        return _pattern(value)

    @field_validator("required")
    @classmethod
    def _fold_required(cls, value: dict[str, str]) -> dict[str, str]:
        return {name: _patterns([pattern])[0] for name, pattern in value.items()}


class AttributeDefaults(FrozenModel):
    near: int = Field(ge=10, le=400)
    # Words that send the reader to another document ("gem. Statik", "lt. Plan"): a missing
    # value is then a question about that document, not a gap in the text.
    documents_any: list[str] = Field(min_length=1)
    # Words that make a note apply to every component ("alle Bauteile").
    general_any: list[str] = Field(min_length=1)
    # Words of new work ("neues Kabel"): nearer to a component word than other work, they keep
    # it of its kind.
    new_any: list[str] = Field(min_length=1)

    @field_validator("documents_any", "general_any", "new_any")
    @classmethod
    def _fold_words(cls, value: list[str]) -> list[str]:
        return _stems(value)


class Attributes(_Table):
    defaults: AttributeDefaults
    item_kinds: list[AttributeKind]


# ----------------------------------------------------------------------------- wording
class RaiseWhen(FrozenModel):
    lump_sum: bool | None = None
    share_of_total_at_least: ExactDecimal | None = Field(default=None, gt=0, le=1)


class WordingGroup(FrozenModel):
    id: str = Field(pattern=r"^V\d{2}$")
    risk_type: str
    meaning: str
    terms: list[str] = Field(min_length=1)
    check: str
    fine_if: list[str] = Field(default_factory=list)
    fine_if_scope: Literal["near", "after", "position", "position_and_notes"] = "near"
    # Patterns that settle the term when they end right before it (a label such as "Gewicht:").
    fine_if_before: list[str] = Field(default_factory=list)
    min_list_items: int | None = Field(default=None, ge=2)
    raise_when_any: list[RaiseWhen] = Field(default_factory=list)
    question: str
    missing_sources: list[str] = Field(default_factory=list)

    @field_validator("terms")
    @classmethod
    def _fold_terms(cls, value: list[str]) -> list[str]:
        return _stems(value)

    @field_validator("fine_if", "fine_if_before")
    @classmethod
    def _fold_fine(cls, value: list[str]) -> list[str]:
        return _patterns(value)


class WordingDefaults(FrozenModel):
    window: int = Field(ge=20, le=400)


class Wording(_Table):
    defaults: WordingDefaults
    groups: list[WordingGroup]


# ----------------------------------------------------------------------------- consistency
class ConsistencyRule(FrozenModel):
    id: str = Field(pattern=r"^C\d{2}$")
    risk_type: str
    attribute: str
    pattern: str
    separator: str | None = None  # splits a listed value ("dn 800/900") into its values

    @field_validator("pattern")
    @classmethod
    def _fold(cls, value: str) -> str:
        return _patterns([value])[0]


class ReferenceRule(FrozenModel):
    """A text that names a position of this bill by its code ("siehe Pos. 01.0020"). Group 1
    of ``pattern`` is the code. ``internal`` words near it place it in this bill, ``external``
    words in another document; both are searched ``reach`` characters around it."""

    id: str = Field(pattern=r"^C\d{2}$")
    risk_type: str
    pattern: str
    internal: list[str]
    external: list[str]
    reach: int = Field(default=40, ge=0, le=200)

    @field_validator("pattern")
    @classmethod
    def _fold(cls, value: str) -> str:
        return _patterns([value])[0]

    @field_validator("internal", "external")
    @classmethod
    def _fold_words(cls, value: list[str]) -> list[str]:
        return [fold(word) for word in value]


class Consistency(_Table):
    rules: list[ConsistencyRule]
    references: list[ReferenceRule] = Field(default_factory=list)


# ----------------------------------------------------------------------------- findings map
class DetectorMapping(FrozenModel):
    risk_type: str
    method: Method | None = None
    by_rule: dict[str, str] = Field(default_factory=dict)
    by_field: dict[str, str] = Field(default_factory=dict)
    # Per rule: the question for the client of a finding that compares no values ({positions}
    # is filled in), and the documents the run lacks to decide it.
    questions: dict[str, str] = Field(default_factory=dict)
    missing: dict[str, list[str]] = Field(default_factory=dict)
    # Counts of the detector's coverage that say it read something, besides the counts ending
    # in "_checked" or "_compared" (checks that name their own counts, such as "items_read").
    checked_counts: list[str] = Field(default_factory=list)

    @field_validator("questions")
    @classmethod
    def _only_positions(cls, value: dict[str, str]) -> dict[str, str]:
        for rule_id, question in value.items():
            slots = set(re.findall(r"\{(\w+)\}", question)) - {"positions"}
            if slots or not question.strip():
                raise ValueError(f"{rule_id}: a question may only name {{positions}}")
        return value

    def types(self) -> set[str]:
        """Every risk type this mapping can give."""
        return {
            self.risk_type,
            *self.by_rule.values(),
            *self.by_field.values(),
        }


class FindingsMap(_Table):
    detectors: dict[str, DetectorMapping]
    categories: dict[str, str]
    changes_totals_categories: list[str]
    # Findings of unmapped detectors in these categories compare a position with similar ones.
    peer_comparison_categories: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- grading
class TierWhen(FrozenModel):
    """Conditions of a tier rule; every condition that is set must hold."""

    harm: Harm | None = None
    state: State | None = None
    state_in: list[State] | None = None
    evidence_not_only_keywords: bool | None = None
    certainty: Certainty | None = None
    certainty_in: list[Certainty] | None = None
    share_of_total_at_least: ExactDecimal | None = Field(default=None, gt=0, le=1)
    lump_sum: bool | None = None
    vague: bool | None = None
    money: MoneyKind | None = None
    challenge_priority: Priority | None = None
    changes_totals: bool | None = None
    found_unlinked: bool | None = None
    # Every rule behind the reminder is one of these (a reminder from these rules alone).
    only_rules_in: list[str] | None = None


class TierRule(FrozenModel):
    id: str = Field(pattern=r"^T\d{2}[a-z]?$")
    tier: Severity
    when: TierWhen
    reason: str
    # False: the floors (structural, fire-rated position) do not raise this rule's tier.
    raise_by_floors: bool = True


class FloorWhen(FrozenModel):
    position_is: Literal["structural", "fire_rated"]
    category_in: list[str] | None = None


class Floor(FrozenModel):
    when: FloorWhen
    min_tier: Severity


class SizeHint(FrozenModel):
    basis: str
    classes: dict[Literal["large", "medium"], ExactDecimal]


class PositionWords(FrozenModel):
    structural: list[str]
    # Words that contain a structural word but name no structural part ("Versorgungsträger" is
    # the utility): taken out of the text before the structural words are looked for.
    not_structural: list[str] = Field(default_factory=list)
    fire_rated_pattern: str

    @field_validator("structural", "not_structural")
    @classmethod
    def _fold_words(cls, value: list[str]) -> list[str]:
        return _stems(value)

    @field_validator("fire_rated_pattern")
    @classmethod
    def _fold_pattern(cls, value: str) -> str:
        return _patterns([value])[0]


class Combination(FrozenModel):
    min_distinct_signal_kinds: int = Field(ge=2)
    raise_by: int = Field(ge=1, le=2)
    max_positions: int = Field(ge=1)
    max_tier_keywords_only: Severity  # evidence from keywords alone never goes above it


SortField = Literal[
    "tier",
    "state",
    "weighted_exposure_eur",
    "unknown_money_size_class",
    "challenge_priority",
    "distinct_signal_kinds",
    "risk_id",
]


class MainList(FrozenModel):
    """Which reminders reach the main list; the others stay in the check record."""

    states: list[State] = Field(min_length=1)
    min_tier: Severity
    always_show_harm: list[Harm] = Field(default_factory=list)  # e.g. safety, at min_tier


class SortKey(FrozenModel):
    field: SortField
    order: Literal["asc", "desc"]


class TrackRecordRule(FrozenModel):
    min_reviews: int = Field(ge=1)
    demote_if_precision_below: ExactDecimal = Field(ge=0, le=1)


class Grading(_Table):
    thresholds_validated: bool
    tiers: list[Severity]
    total_basis: Literal["counted_net_total"]
    rules: list[TierRule] = Field(min_length=1)
    money_sources: dict[str, list[str]]
    unknown_money_size_hint: SizeHint
    floors: list[Floor]
    position_words: PositionWords
    combination: Combination
    order_weight: dict[Certainty, ExactDecimal]
    sort_key: list[SortKey] = Field(min_length=1)
    main_list: MainList
    track_record: TrackRecordRule

    @model_validator(mode="after")
    def _complete(self) -> Grading:
        if set(self.order_weight) != set(Certainty):
            raise ValueError("order_weight needs a weight for every certainty")
        if self.sort_key[-1].field != "risk_id":
            raise ValueError("the sort key must end with risk_id, so the order has no ties")
        return self


# ----------------------------------------------------------------------------- explanations
class CategoryText(FrozenModel):
    reason: str
    action: str


class PlanRule(FrozenModel):
    when: dict[Literal["state", "evidence_class", "method", "money", "harm", "category"], list[str]]
    kind: str = Field(pattern=r"^[a-z_]{1,60}$")


class PlanTexts(FrozenModel):
    summary: str
    first: list[PlanRule] = Field(min_length=1)
    also: list[PlanRule] = Field(default_factory=list)
    texts: dict[str, str]

    @model_validator(mode="after")
    def _every_kind_has_a_text(self) -> PlanTexts:
        missing = {r.kind for r in [*self.first, *self.also]} - set(self.texts)
        if missing:
            raise ValueError(f"plan kinds without a text: {sorted(missing)}")
        if self.first[-1].when:
            raise ValueError("the last 'first' rule must have no conditions (the default step)")
        return self


class Explanations(_Table):
    method_phrase: dict[Method, str]
    default_action: str
    categories: dict[str, CategoryText]
    plan: PlanTexts | None = None
    questions: dict[
        Literal[
            "dependency_not_found",
            "dependency_unlinked",
            "dependency_separate",
            "attribute_missing",
            "attribute_in_documents",
            "consistency",
            "reference",
        ],
        str,
    ]


# ----------------------------------------------------------------------------- all tables
@dataclass(frozen=True, slots=True)
class RiskTables:
    profile_id: str
    catalogue: Catalogue
    components: Components
    context: ContextTables
    dependencies: Dependencies
    attributes: Attributes
    wording: Wording
    consistency: Consistency
    findings: FindingsMap
    grading: Grading
    explanations: Explanations
    discovery: DiscoveryTable

    def risk_type(self, risk_type: str) -> RiskType:
        if risk_type == OTHER:
            return self.catalogue.other
        return self._types()[risk_type]

    def _types(self) -> dict[str, RiskType]:
        return {t.id: t for t in self.catalogue.risk_types}

    @property
    def versions(self) -> dict[str, str]:
        return {
            name: getattr(self, name).version
            for name in (
                "catalogue",
                "components",
                "context",
                "dependencies",
                "attributes",
                "wording",
                "consistency",
                "findings",
                "grading",
                "explanations",
                "discovery",
            )
        }

    def check(self) -> None:
        """Cross-references between the files: every risk type a rule names exists, every
        category of the catalogue has its texts, and dependency contexts name project
        types."""
        known = set(self._types()) | {OTHER}
        named = [
            *(r.risk_type for r in self.dependencies.rules),
            *(k.risk_type for k in self.attributes.item_kinds),
            *(g.risk_type for g in self.wording.groups),
            *(r.risk_type for r in self.consistency.rules),
            *(r.risk_type for r in self.consistency.references),
            *(t for m in self.findings.detectors.values() for t in m.types()),
            *self.findings.categories.values(),
        ]
        unknown = sorted(set(named) - known)
        if unknown:
            raise ValueError(f"unknown risk types: {unknown}")
        categories = {t.category for t in self.catalogue.risk_types} | {OTHER}
        missing = sorted(categories - set(self.explanations.categories))
        if missing:
            raise ValueError(f"categories without texts: {missing}")
        contexts = {c for r in self.dependencies.rules for c in r.context}
        strange = sorted(contexts - set(self.context.project_types))
        if strange:
            raise ValueError(f"dependency contexts that are no project type: {strange}")
        if set(Method) - set(self.explanations.method_phrase):
            raise ValueError("every method needs its phrase")


class DiscoveryBudget(FrozenModel):
    max_candidates: int = Field(ge=1, le=200)
    items_per_call: int = Field(ge=1, le=20)
    max_item_chars: int = Field(ge=100, le=5000)
    max_context_chars: int = Field(ge=0, le=10_000)
    max_prompt_chars: int = Field(ge=1000, le=60_000)
    max_output_tokens: int = Field(ge=64, le=8192)
    max_calls: int = Field(ge=1, le=50)
    call_timeout_seconds: float = Field(gt=0, le=3600)
    total_seconds: float = Field(gt=0, le=7200)
    min_call_seconds: float = Field(gt=0, le=600)


class DiscoverySplit(FrozenModel):
    known: float = Field(ge=0, le=1)
    differences: float = Field(ge=0, le=1)
    exploration: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _whole(self) -> DiscoverySplit:
        if abs(self.known + self.differences + self.exploration - 1) > 1e-9:
            raise ValueError("the three shares must add up to 1")
        return self


class DiscoverySimilarity(FrozenModel):
    block_positions: int = Field(ge=2, le=2000)
    no_comparable_below: float = Field(gt=0, lt=1)
    similar_from: float = Field(gt=0, lt=1)
    min_differing_words: int = Field(ge=1, le=20)


class DiscoveryTable(_Table):
    budget: DiscoveryBudget
    split: DiscoverySplit
    seed: int
    similarity: DiscoverySimilarity


_FILES: dict[str, type[_Table]] = {
    "catalogue": Catalogue,
    "components": Components,
    "context": ContextTables,
    "dependencies": Dependencies,
    "attributes": Attributes,
    "wording": Wording,
    "consistency": Consistency,
    "findings": FindingsMap,
    "grading": Grading,
    "explanations": Explanations,
    "discovery": DiscoveryTable,
}


def available_profiles() -> list[str]:
    """Profiles that have risk tables."""
    return sorted(p.name for p in DATA_DIR.iterdir() if (p / "catalogue.yaml").is_file())


@functools.cache
def load_tables(profile_id: str) -> RiskTables:
    """The risk tables of a profile, loaded and checked once per process.

    Raises :class:`InvalidInputError` when the profile has no risk tables."""
    if profile_id not in available_profiles():
        raise InvalidInputError(
            f"Risk grading is not available for the profile {profile_id!r}.",
            details={"profile_id": profile_id, "available": available_profiles()},
        )
    folder = DATA_DIR / profile_id
    loaded: dict[str, Any] = {}
    for name, model in _FILES.items():
        data = yaml.safe_load((folder / f"{name}.yaml").read_text(encoding="utf-8"))
        loaded[name] = model.model_validate(_with_string_versions(data))
    tables = RiskTables(profile_id=profile_id, **loaded)
    tables.check()
    return tables


def _with_string_versions(data: Any) -> Any:
    """YAML reads ``version: 0.3`` as a float; the tables keep versions as text."""
    if isinstance(data, dict) and isinstance(data.get("version"), (int, float, Decimal)):
        return {**data, "version": str(data["version"])}
    return data
