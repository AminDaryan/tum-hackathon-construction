"""Records of the risk report: what the grader returns for one validation run.

A :class:`Candidate` is what a check found, before grading. The grader merges candidates that
rest on the same evidence, gives each merged risk a tier and a rank, and returns a
:class:`RiskReport`. Evidence strength (``state``, ``evidence_class``) and priority (``tier``)
are separate fields: a safety question can be reviewed first without being called a confirmed
hazard, and unknown money is shown as unknown, never as zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from app.models.base import FrozenModel
from app.models.dataset import CellRef
from app.models.issue import EvidenceClass, Severity
from app.models.values import ExactDecimal

FORMAT_VERSION = "0.6"


class Method(StrEnum):
    """How a risk was found (the six general methods of the risk design)."""

    INVARIANT = "invariant"
    PEER_COMPARISON = "peer_comparison"
    DEPENDENCY = "dependency"
    VAGUENESS = "vagueness"
    ATTRIBUTE_CONSISTENCY = "attribute_consistency"
    GUIDED_LLM = "guided_llm"


class State(StrEnum):
    """Outcome of one check: a risk, an open question, or a coverage note."""

    RISK = "risk"  # the bill shows a problem (confirmed or suspected, see evidence_class)
    CANNOT_TELL = "cannot_tell"  # the information at hand cannot decide it: ask
    COVERED = "covered"  # what was looked for was found and tied to the position
    NOT_APPLICABLE = "not_applicable"  # the rule does not apply to this bill
    NOT_CHECKABLE = "not_checkable"  # needs data this run does not have, or no check exists


# Coverage rows keep the strongest state of the rules of one risk type.
STATE_STRENGTH: dict[State, int] = {
    State.NOT_CHECKABLE: 0,
    State.NOT_APPLICABLE: 1,
    State.COVERED: 2,
    State.CANNOT_TELL: 3,
    State.RISK: 4,
}


class Certainty(StrEnum):
    CONFIRMED = "confirmed"
    SUSPECTED = "suspected"
    SEMANTIC = "semantic"
    UNCLEAR = "unclear"


FINDING_GROUP = "finding:"  # group key prefix of stored findings (app.risk.findings)
CERTAINTY_OF: dict[EvidenceClass, Certainty] = {
    EvidenceClass.CONFIRMED_RULE_VIOLATION: Certainty.CONFIRMED,
    EvidenceClass.HUMAN_CONFIRMED_ERROR: Certainty.CONFIRMED,
    EvidenceClass.SUSPECTED_ANOMALY: Certainty.SUSPECTED,
    EvidenceClass.SEMANTIC_WARNING: Certainty.SEMANTIC,
    EvidenceClass.EXTRACTION_UNCERTAINTY: Certainty.UNCLEAR,
    EvidenceClass.NEEDS_EXTERNAL_CONTEXT: Certainty.UNCLEAR,
}
CERTAINTY_STRENGTH: dict[Certainty, int] = {
    Certainty.UNCLEAR: 0,
    Certainty.SEMANTIC: 1,
    Certainty.SUSPECTED: 2,
    Certainty.CONFIRMED: 3,
}


class Harm(StrEnum):
    SAFETY = "safety"
    CONTRACT = "contract"
    MONEY = "money"
    SCHEDULE = "schedule"
    DATA_QUALITY = "data_quality"


class Direction(StrEnum):
    COST_RISK = "cost_risk"  # the bidder may price too low
    CLAIM_POTENTIAL = "claim_potential"  # a gap the bidder may claim later
    BOTH = "both"


class Priority(StrEnum):
    """The challenge's priority of a risk type."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    ADVANCED = "advanced"


PRIORITY_RANK: dict[Priority, int] = {
    Priority.ADVANCED: 0,
    Priority.MEDIUM: 1,
    Priority.HIGH: 2,
    Priority.CRITICAL: 3,
}


# What a "not found" rests on: not found in what was searched (other documents may have it),
# left to a document that was not provided or read, or stated by the bill itself.
Absence = Literal["not_found_in_searched_scope", "in_document_not_provided", "stated_in_bill"]


class MoneyKind(StrEnum):
    EXACT = "exact"  # a difference the workbench computed from the bill
    ESTIMATE = "estimate"  # quantity x reference price of comparable positions, with a range
    UNKNOWN = "unknown"


class SizeClass(StrEnum):
    """Ordering hint for unknown money: never an amount."""

    LARGE = "large"
    MEDIUM = "medium"
    SMALL = "small"
    NONE = "none"


SIZE_RANK: dict[SizeClass, int] = {
    SizeClass.NONE: 0,
    SizeClass.SMALL: 1,
    SizeClass.MEDIUM: 2,
    SizeClass.LARGE: 3,
}


class LinkKind(StrEnum):
    """How found text relates to the position a check is about."""

    SAME_POSITION = "same_position"
    EXPLICIT_REFERENCE = "explicit_reference"
    SHARED_KEY = "shared_key"  # same building, storey, room, axis, component or system
    NOTE = "note"  # a general or section note states it
    NOT_LINKED = "not_linked"  # found, but nothing ties it to this position: a candidate only
    DIFFERENT = "different"  # names another building, storey, room, component or system
    MODEL_HINT = "model_hint"  # the local model pointed to it; the quote was verified


# ----------------------------------------------------------------------------- report parts
class PositionRef(FrozenModel):
    """A row of the bill a risk is about; ``cells`` are highlighted in the interface."""

    label: str = Field(min_length=1, max_length=200)  # item code, or "row N of <table>"
    item_code: str | None = None
    table_id: str
    row_id: str
    cells: list[CellRef] = Field(default_factory=list)


class Quote(FrozenModel):
    """Text exactly as the bill states it."""

    position: str | None = None  # the position's label; None for a note
    source: str = Field(min_length=1, max_length=300)  # "short text", "long text", "note: ..."
    text: str = Field(min_length=1, max_length=1200)


class EvidenceLink(FrozenModel):
    """Rows a finding was computed from or names, by their role (the label of the detector's
    evidence item: "Rows summed", "Not counted"). Evidence, not further problem positions."""

    label: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=40)  # the evidence item's kind
    positions: list[PositionRef] = Field(default_factory=list)  # capped, see positions_total
    positions_total: int = Field(ge=0)


class CounterEvidence(FrozenModel):
    """Text found while looking for the work or value, and what it means for this risk."""

    position: str | None = None
    source: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=1200)
    link: LinkKind
    detail: str = Field(min_length=1, max_length=600)


class ReferenceAmount(FrozenModel):
    """A comparison amount a detector computed, kept with its source (e.g. the price comparison:
    quantity times the difference to the median unit price of comparable positions). It is not
    a loss: the reminder's money stays unknown, and neither tiers nor order use it."""

    amount: ExactDecimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    basis: str = Field(min_length=1, max_length=600)  # the detector's own wording
    kind: str = Field(min_length=1, max_length=40)  # the detector's kind, e.g. reference_deviation
    reported: ExactDecimal | None = None  # e.g. the position's unit price
    recomputed: ExactDecimal | None = None  # e.g. the reference unit price
    source_issue_id: str
    detector_id: str


class Money(FrozenModel):
    """The money behind a risk, with its basis. ``share_of_total`` and ``size_class`` order the
    list; neither is a loss or a probability."""

    kind: MoneyKind
    amount: ExactDecimal | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    low: ExactDecimal | None = None
    high: ExactDecimal | None = None
    quantity: ExactDecimal | None = None
    reference_price: ExactDecimal | None = None
    comparable: str | None = None  # which positions the reference price comes from
    basis: str = Field(min_length=1, max_length=600)
    share_of_total: ExactDecimal | None = None
    size_class: SizeClass = SizeClass.NONE
    reference: ReferenceAmount | None = None  # a comparison amount, never a loss

    @model_validator(mode="after")
    def _has_its_basis(self) -> Money:
        if self.kind is MoneyKind.EXACT and (self.amount is None or self.currency is None):
            raise ValueError("an exact amount needs the amount and its currency")
        if self.kind is MoneyKind.ESTIMATE and None in (
            self.low,
            self.high,
            self.quantity,
            self.reference_price,
            self.comparable,
            self.currency,
        ):
            raise ValueError(
                "an estimate needs its range, quantity, reference price, comparable "
                "positions and currency"
            )
        if self.kind is MoneyKind.UNKNOWN and (self.amount is not None or self.low is not None):
            raise ValueError("unknown money has no amount")
        return self


class TrackRecord(FrozenModel):
    """Review decisions on findings of the same check (this run, with decisions carried
    forward from earlier runs of the dataset)."""

    reviewed: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    rejected: int = Field(ge=0)


class Factors(FrozenModel):
    harm: Harm
    certainty: Certainty
    challenge_priority: Priority
    independent_signals: int = Field(ge=1)
    track_record: TrackRecord | None = None


class Risk(FrozenModel):
    risk_id: str
    rank: int = Field(ge=1)  # the position in its list as displayed (see RiskReport.display)
    priority_rank: int | None = Field(default=None, ge=1)  # the position in the default order
    tier: Severity  # the review priority; evidence strength is in state and evidence_class
    tier_rule: str
    tier_reason: str
    title: str = Field(min_length=1, max_length=300)
    risk_type: str
    risk_name: str
    category: str
    direction: Direction
    state: State
    evidence_class: EvidenceClass
    methods: list[Method] = Field(min_length=1)
    rules: list[str] = Field(min_length=1)
    positions: list[PositionRef] = Field(default_factory=list)
    positions_total: int = Field(ge=0)  # positions concerned; ``positions`` may be capped
    quotes: list[Quote] = Field(default_factory=list)
    why_risk_here: str = Field(min_length=1)
    counter_evidence: list[CounterEvidence] = Field(default_factory=list)
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    checked: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    absence: Absence | None = None  # for a reminder about work or information not found
    money: Money
    factors: Factors
    question: str | None = None  # the clarification question to send to the client
    suggested_action: str = Field(min_length=1)
    source_issue_ids: list[str] = Field(default_factory=list)
    sort_note: str | None = None  # why the display sort placed it last (money, level unknown)


class RuleCheck(FrozenModel):
    """What one rule of a risk type did in this run: its state and the positions it looked at
    closely: those that name its words (also when they are ruled out, "kein Grundwasser"), use
    its terms or state its value in both texts, and those whose text covers them. A rule whose
    words no position names lists none (it read every position)."""

    rule_id: str
    state: State
    reason: str
    positions: list[str] = Field(default_factory=list)  # labels; capped, see positions_total
    positions_total: int = Field(default=0, ge=0)
    # What a detector says it checked, as counts ("rows_checked": 12): the checked scope, not
    # problem positions. A detector names no rows, so its ``positions`` stay empty.
    scope: dict[str, int] = Field(default_factory=dict)


class CoverageRow(FrozenModel):
    risk_type: str
    name: str
    category: str
    state: State
    reason: str
    rules: list[str] = Field(default_factory=list)
    checks: list[RuleCheck] = Field(default_factory=list)


class ModelReview(FrozenModel):
    """What the optional local-model step did. Its failures never remove other results."""

    status: Literal["not_requested", "not_configured", "unavailable", "not_needed", "completed"]
    detail: str
    groups_selected: int = Field(default=0, ge=0)
    groups_answered: int = Field(default=0, ge=0)
    hints_kept: int = Field(default=0, ge=0)
    hints_dropped: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)


DiscoveryPath = Literal["known", "differences", "exploration", "sample"]


class DiscoveryPick(FrozenModel):
    """A position chosen for the model, by which path and why, and what came of it. A reason is
    a priority hint (a rare text, a differing word), never a finding. ``no_finding``: the model
    looked and proposed nothing; ``findings_rejected``: what it proposed failed the checks;
    ``not_sent`` (budget) and ``not_answered`` (timeout, failure, invalid answer): the position
    was not looked at. Neither of the last two is a pass."""

    position: str  # label
    path: DiscoveryPath
    reason: str = Field(min_length=1, max_length=600)
    outcome: Literal[
        "finding_kept", "no_finding", "findings_rejected", "not_sent", "not_answered"
    ] = "not_sent"
    # "cut": only the first chars_sent characters (whole sentences) were sent; the rest of the
    # text was not looked at and is not covered by any outcome.
    text: Literal["full", "cut"] = "full"
    chars_sent: int | None = Field(default=None, ge=0)
    chars_total: int | None = Field(default=None, ge=0)


class DiscoveryCall(FrozenModel):
    number: int = Field(ge=1)
    positions: list[str]
    status: Literal["answered", "invalid_answer", "timeout", "failed"]
    seconds: float = Field(ge=0)
    prompt_chars: int = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    texts_cut: list[str] = Field(default_factory=list)  # positions whose text was shortened
    findings_returned: int = Field(default=0, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)  # as the server counts them, if it does
    output_tokens: int | None = Field(default=None, ge=0)
    # The server's end reason ("stop", "length"), or None when it did not report one.
    stop_reason: str | None = Field(default=None, max_length=40)


RejectStage = Literal[
    "format",  # the answer or a finding is not in the asked format
    "item",  # names an item that was not in the request
    "quote",  # the quote is not verbatim in the text actually sent
    "content",  # no concrete hypothesis or action, or an unfounded amount, standard, liability
    "context",  # a consulted text without a verified quote (the finding itself stays)
    "limit",  # more findings than the request may return
    "repeat",  # the same hypothesis on the same position, returned again
    "same_cause",  # merged into a reminder the model named as the same cause
    "same_as_unknown",  # named a reminder that is not shown for this item (finding kept apart)
    "position_gone",  # the position is no longer in the bill
]


class DiscoveryReject(FrozenModel):
    """A hypothesis (or part of one) not kept as its own reminder, and why. Nothing is dropped
    without one of these."""

    position: str | None = None
    reason: str = Field(min_length=1, max_length=300)
    stage: RejectStage = "format"
    call: int | None = Field(default=None, ge=1)
    finding_id: str | None = None
    # For a merge or repeat: the reminder or finding it joined, and that reminder's rules.
    same_as: list[str] = Field(default_factory=list)


class DiscoveryFinding(FrozenModel):
    """One hypothesis of the model that passed the checks: the position exists, the quote is
    verbatim in its text, the hypothesis and the verification are concrete, and no amount,
    share, probability or standard appears that the texts shown did not contain. Checked is the
    evidence, not the reasoning: the hypothesis is the model's and stays to be verified."""

    table_id: str
    row_id: str
    label: str
    source: Literal["short text", "long text"]
    quote: str = Field(min_length=1, max_length=1200)
    stated_facts: str = Field(default="", max_length=600)
    hypothesis: str = Field(min_length=1, max_length=600)
    affects: str = Field(default="", max_length=600)
    missing_documents: list[str] = Field(default_factory=list)
    verification: str = Field(min_length=1, max_length=600)
    context: list[CounterEvidence] = Field(default_factory=list)  # explanations it consulted
    dimension: int | None = Field(default=None, ge=1, le=4)
    call: int = Field(ge=1)
    finding_id: str = ""  # stable: position, quote and hypothesis
    same_as: str | None = None  # a shown reminder the model named as the same cause (checked)
    checked: list[str] = Field(default_factory=list)  # what the automatic checks confirmed
    review: Literal["not_reviewed"] = "not_reviewed"  # the reasoning itself is not checked
    reminder_id: str | None = None  # the reminder it became or was merged into


class Discovery(FrozenModel):
    """What the budgeted discovery by the local model did for this report, or why it did not.

    ``not_enabled``: not asked for. ``not_processed``: asked for, but nothing was sent (no
    model configured, a model not on the allow-list, no positions). ``completed``: every chosen
    position was sent and answered. ``partial``: some requests timed out, failed or were
    answered invalidly. ``over_budget``: the request or time budget stopped sending before every
    chosen position was sent. ``failed``: no request was answered. A position not looked at is
    counted as not processed, never as free of risk."""

    status: Literal[
        "not_enabled",
        "not_processed",
        "completed",
        "partial",
        "over_budget",
        "failed",
        "queued",  # a stored run that has not started (the report applies nothing yet)
        "running",
        "outdated",  # a stored run made for other inputs: shown, never applied
    ]
    detail: str
    discovery_run_id: str | None = None  # the stored run applied (or shown as outdated)
    strategy: Literal["paths", "sample"] | None = None
    model: str | None = None
    prompt_version: str | None = None
    table_version: str | None = None
    budget: dict[str, float | str] = Field(default_factory=dict)  # the values it ran with
    positions_total: int = Field(default=0, ge=0)
    selected: list[DiscoveryPick] = Field(default_factory=list)
    by_path: dict[str, int] = Field(default_factory=dict)
    not_selected: int = Field(default=0, ge=0)  # positions the model was not asked about
    processed: int = Field(default=0, ge=0)  # chosen positions whose request was answered
    partly_read: int = Field(default=0, ge=0)  # of those, positions whose text was cut
    not_processed: int = Field(default=0, ge=0)  # chosen, but not sent or not answered
    calls: list[DiscoveryCall] = Field(default_factory=list)
    seconds: float = Field(default=0, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    findings_returned: int = Field(default=0, ge=0)
    rejected: list[DiscoveryReject] = Field(default_factory=list)
    rejected_total: int = Field(default=0, ge=0)
    duplicates: list[DiscoveryReject] = Field(default_factory=list)  # merged or repeated
    kept: int = Field(default=0, ge=0)  # hypotheses that became reminders of their own
    merged: int = Field(default=0, ge=0)  # joined a reminder the model named as the same cause
    findings_total: int = Field(default=0, ge=0)  # ``findings`` lists at most 50
    findings: list[DiscoveryFinding] = Field(default_factory=list)  # facts, hypothesis, question
    reminder_ids: list[str] = Field(default_factory=list)
    scope: str = (
        "Only this bill was read: its positions, notes and the comparable or referenced "
        "positions shown with each request. No other file was searched."
    )


class DiscoveryExchange(FrozenModel):
    """One request as sent to the model and its raw answer, kept for tracing in a stored run
    and in the evaluation (never part of the report). Ids are the request's own (P1, C1, R1)."""

    call: int = Field(ge=1)
    items: dict[str, str] = Field(default_factory=dict)  # request id -> position label
    reminders: dict[str, str] = Field(default_factory=dict)  # request id -> reminder id
    context: dict[str, str] = Field(default_factory=dict)  # request id -> what the text is
    prompt: str
    answer: str | None = None  # None: no answer (timeout, failure)
    error: str | None = None


TIMEOUT_NOTE = (
    "A timeout means the client stopped waiting and closed the connection; whether the model "
    "server also stopped generating is not checked."
)


class DiscoveryRun(FrozenModel):
    """One explicitly started discovery for a validation run, stored with what came of it and
    the inputs it is bound to. Reading a report with its id applies its checked hypotheses
    without calling a model; a report whose inputs changed shows it as outdated instead.
    ``status`` is the run's own (queued, running, finished, failed); the discovery's outcome
    (completed, partial, over_budget, not_processed, ...) is in ``discovery.status``."""

    discovery_run_id: str
    run_id: str
    strategy: Literal["paths", "sample"]
    status: Literal["queued", "running", "finished", "failed"]
    inputs: dict[str, str]  # what the result is bound to: data, tables, checks, model
    fingerprint: str
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    seconds_total: float | None = Field(default=None, ge=0)  # end to end, from the start
    seconds_model: float | None = Field(default=None, ge=0)  # the model requests, summed
    timeout_note: str = TIMEOUT_NOTE
    discovery: Discovery | None = None  # the full record: lists are not capped here
    findings: list[DiscoveryFinding] = Field(default_factory=list)
    rejected: list[DiscoveryReject] = Field(default_factory=list)
    repeats: list[DiscoveryReject] = Field(default_factory=list)
    exchanges: list[DiscoveryExchange] = Field(default_factory=list)
    error: str | None = None


class DiscoveryRunSummary(FrozenModel):
    discovery_run_id: str
    strategy: Literal["paths", "sample"]
    status: Literal["queued", "running", "finished", "failed"]
    discovery_status: str | None = None
    fingerprint: str
    requested_at: datetime
    finished_at: datetime | None = None
    findings: int = Field(default=0, ge=0)


class DiscoveryRunList(FrozenModel):
    items: list[DiscoveryRunSummary]  # newest first


class SourceCoverage(FrozenModel):
    """What the reading of the source covered, as the caller states it (a later extraction
    step or a person). Not given means unknown; risk never guesses it from file names or page
    counts. Optional: every check runs without it."""

    stated_by: str = Field(min_length=1, max_length=200)
    read: list[str] = Field(default_factory=list)  # parts read, as the caller names them
    not_read: list[str] = Field(default_factory=list)  # pages or attachments skipped
    not_provided: list[str] = Field(default_factory=list)  # documents named but not supplied
    preface_read: bool | None = None  # the preliminary text (Vorbemerkungen)


class ProjectContext(FrozenModel):
    project_types: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    trades: list[str] = Field(default_factory=list)
    positions: int = Field(ge=0)
    priced: bool
    currency: str | None = None
    counted_total: ExactDecimal | None = None
    documents_searched: int = Field(default=1, ge=1)
    source: Literal["derived"] = "derived"


QuestionKind = Literal["missing_document", "not_linked", "not_found", "other"]


class OpenQuestion(FrozenModel):
    """Open questions of one cause, asked once: a document the run does not have, or work the
    bill does not show or does not tie to its component. They stay in the check record and are
    never counted as passed."""

    kind: QuestionKind
    topic: str
    source: Literal["checks", "discovery", "both"] = "checks"  # discovery: a model hypothesis
    # True: model hypotheses no person confirmed, listed after every question of the checks.
    experimental: bool = False
    rules: list[str]
    risk_types: list[str]
    positions_total: int = Field(ge=0)
    positions: list[str] = Field(default_factory=list)  # labels, capped
    question: str
    reminder_ids: list[str]
    serves: list[str] = Field(default_factory=list)  # each distinct question it answers


class Funnel(FrozenModel):
    """How this run's doubts were narrowed down (counts, never scores or probabilities)."""

    raw_doubts: int = Field(ge=0)  # every doubt a rule raised, plus every open finding
    explained_automatically: int = Field(ge=0)  # settled by the bill itself
    below_size_threshold: int = Field(ge=0)  # not raised: too small per the wording table
    open_after_search: int = Field(ge=0)
    after_merging: int = Field(ge=0)  # reminders after merging one cause seen several times
    main_list: int = Field(ge=0)
    kept_in_record: int = Field(ge=0)  # open questions and low-impact reminders, not shown
    open_question_groups: int = Field(ge=0)
    checks_missing_information: list[str] = Field(default_factory=list)


SortBy = Literal["priority", "price_impact", "confidence"]
SortOrder = Literal["desc", "asc"]
DISPLAY_POLICY = "display-1"


class DisplayOrder(FrozenModel):
    """How ``risks`` and ``record`` are ordered for display, each list on its own. Sorting only
    reorders a finished report: no reminder, count, tier, state, money, evidence or id changes,
    no reminder moves between the lists, and no model is called."""

    sort_by: SortBy = "priority"
    sort_order: SortOrder = "desc"
    policy_version: str = DISPLAY_POLICY
    basis: str = (
        "priority: the default order of grading.yaml (tier, state, weighted money, size class, "
        "challenge priority, signal kinds, risk_id); asc is its exact reverse"
    )
    ties: str = "equal main keys keep the default order (priority_rank), then risk_id"
    always_last: str = ""
    price_basis: str = (
        "an exact amount by its absolute value (the difference, never the item's total price); "
        "an estimate by the larger absolute end of its range (the range and its basis stay "
        "shown); no evidence weight; a comparison amount (money.reference) is never a loss and "
        "is not used"
    )
    incomparable_rule: str = (
        "only amounts in the bill's currency are compared, with exact decimals; another or a "
        "missing currency is not converted and goes after the compared amounts, with its amount "
        "and currency kept; unknown money goes last (a known 0 is an amount, not unknown)"
    )
    confidence_levels: list[str] = Field(
        default_factory=lambda: ["confirmed", "suspected", "semantic", "unclear"]
    )
    confidence_basis: str = (
        "the evidence level (factors.certainty), shown as 'evidence certainty': a product "
        "grouping, not a probability or an accuracy; a model's own confidence is never used; "
        "an unknown level is never raised, it goes last"
    )
    open_questions: str = (
        "open_questions keep their grouping and their order (first appearance in the record's "
        "default order) whatever the sort; each names its reminders in reminder_ids"
    )


class RiskReport(FrozenModel):
    """The main reminders of one validation run, the check record behind them, the grouped open
    questions, the coverage of every risk type of the catalogue, and how the doubts were
    narrowed down."""

    format_version: str = FORMAT_VERSION
    run_id: str
    profile_id: str
    tables_version: dict[str, str]
    context: ProjectContext
    counts: dict[str, int]
    risks: list[Risk]  # the main list: concrete evidence, noteworthy impact, a next action
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    record: list[Risk] = Field(default_factory=list)  # every other open reminder, ranked
    funnel: Funnel
    coverage: list[CoverageRow]
    model_review: ModelReview
    discovery: Discovery = Field(
        default_factory=lambda: Discovery(
            status="not_enabled",
            detail="Not asked for: no position was sent to a model for discovery.",
        )
    )
    sources: SourceCoverage | None = None  # None: which parts of the source were read is unknown
    display: DisplayOrder = Field(default_factory=DisplayOrder)
    notes: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- candidates
@dataclass(frozen=True, slots=True)
class Candidate:
    """What one check found, before merging and grading.

    ``evidence_keys`` identify the evidence (cells, or a position and risk type): candidates
    that share one are the same finding seen twice, not two independent signals.
    """

    rule_id: str
    risk_type: str
    method: Method
    state: State
    certainty: Certainty
    title: str
    positions: tuple[PositionRef, ...]
    quotes: tuple[Quote, ...] = ()
    slots: Mapping[str, str] = field(default_factory=dict)
    question: str | None = None
    checked: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    counter_evidence: tuple[CounterEvidence, ...] = ()
    evidence_links: tuple[EvidenceLink, ...] = ()
    money: Money | None = None
    harm: Harm | None = None
    keywords_only: bool = True
    lump_sum: bool = False
    vague: bool = False
    found_unlinked: bool = False
    absence: Absence | None = None
    changes_totals: bool = False
    position_texts: tuple[str, ...] = ()  # folded texts of the positions (floors)
    explanation: str | None = None  # why it is worth checking here
    action: str | None = None  # the review action; None: the category's default
    source_issue_ids: tuple[str, ...] = ()
    evidence_keys: frozenset[str] = frozenset()
    stable_key: str = ""  # stable across runs: fingerprints, or table and item codes
    track_record: TrackRecord | None = None
    evidence_class: EvidenceClass | None = None  # None: follows from the certainty
    group: str = ""  # candidates of one rule and scope are shown as one reminder
