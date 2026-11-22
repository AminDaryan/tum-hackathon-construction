"""Merge, tier and order the candidates into the reminders of the risk report.

1. Merge: candidates that share evidence (a cell, or one rule on one position) or that name the
   same risk type for the same single position are one issue seen more than once. Evidence of a
   candidate about several positions counts as shared only with candidates about exactly those
   positions: a finding that lists the cells of 31 items is not the same issue as a misspelling
   in one of them, and chaining them through that cell made one risk of many. Their money
   is the largest exact amount, never a sum. Signals are counted after merging: candidates
   that share evidence are one signal, however many methods found it.
2. Group: merged issues of one rule and scope (the same ``group`` keys) become one reminder that
   lists their positions.
3. Tier (the review priority, kept apart from the evidence strength): the first rule of
   ``grading.yaml`` that matches, then the floors (structural or fire-rated positions), then the
   combination raise (independent signals of different kinds on a few positions; safety
   keywords alone never go above high), then the track record (a check whose findings reviewers
   mostly rejected is lowered one tier).
4. Order by the sort keys of ``grading.yaml``. The weighted exposure (money x order weight) only
   orders the list; it is never shown as an amount or a probability.

Steps 3 and 4 can also be called on their own, on facts given from elsewhere (``tier_of``,
``sort_values``, ``order``); ``grade`` uses the same functions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

from app.models.dataset import CellRef
from app.models.issue import SEVERITY_RANK, EvidenceClass, Severity
from app.risk.bill import Bill
from app.risk.explain import fill, labels
from app.risk.models import (
    CERTAINTY_STRENGTH,
    FINDING_GROUP,
    PRIORITY_RANK,
    SIZE_RANK,
    STATE_STRENGTH,
    Candidate,
    Certainty,
    CounterEvidence,
    EvidenceLink,
    Factors,
    Harm,
    Method,
    Money,
    MoneyKind,
    PositionRef,
    Priority,
    Quote,
    Risk,
    SizeClass,
    State,
    TrackRecord,
)
from app.risk.tables import OTHER, RiskTables, TierRule, TierWhen
from app.risk.text import clip, find

MAX_POSITIONS = 10
MAX_QUOTES = 6
MAX_COUNTER = 8
_TIERS = sorted(SEVERITY_RANK, key=SEVERITY_RANK.__getitem__)  # info ... critical
_EVIDENCE = {
    Certainty.CONFIRMED: EvidenceClass.CONFIRMED_RULE_VIOLATION,
    Certainty.SUSPECTED: EvidenceClass.SUSPECTED_ANOMALY,
    Certainty.SEMANTIC: EvidenceClass.SEMANTIC_WARNING,
    Certainty.UNCLEAR: EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
}
Issue = list[Candidate]  # candidates merged as one issue
_Shown = TypeVar("_Shown", Quote, CounterEvidence)
_Item = TypeVar("_Item")


@dataclass(frozen=True, slots=True)
class Facts:
    """What the tier rules of ``grading.yaml`` look at, for one reminder."""

    harm: Harm
    state: State
    certainty: Certainty
    keywords_only: bool
    share: Decimal | None
    lump_sum: bool
    vague: bool
    money: MoneyKind
    priority: str
    changes_totals: bool
    found_unlinked: bool
    rules: tuple[str, ...]


def grade(candidates: Sequence[Candidate], bill: Bill, tables: RiskTables) -> list[Risk]:
    open_ = [c for c in candidates if c.state in (State.RISK, State.CANNOT_TELL)]
    built = [_risk(reminder, bill, tables) for reminder in _group(_merge(open_))]
    ranked = order(built, tables)
    return [risk.model_copy(update={"rank": rank}) for rank, risk in enumerate(ranked, start=1)]


def order(
    items: Sequence[tuple[_Item, Mapping[str, Decimal | str]]], tables: RiskTables
) -> list[_Item]:
    """``items`` (each with its :func:`sort_values`) in the order of ``grading.yaml``'s sort keys:
    compared left to right, a later key only breaks ties of the earlier ones."""
    ordered = list(items)
    for sort_key in reversed(tables.grading.sort_key):
        ordered.sort(key=lambda item: item[1][sort_key.field], reverse=sort_key.order == "desc")
    return [item for item, _ in ordered]


def sort_values(
    *,
    tier: Severity,
    state: State,
    certainty: Certainty,
    money: Money,
    currency: str | None,
    priority: Priority,
    kinds: int,
    risk_id: str,
    tables: RiskTables,
) -> dict[str, Decimal | str]:
    """The values :func:`order` compares; see :func:`weighted_exposure`."""
    return {
        "tier": Decimal(SEVERITY_RANK[tier]),
        "state": Decimal(STATE_STRENGTH[state]),
        "weighted_exposure_eur": weighted_exposure(money, certainty, currency, tables),
        "unknown_money_size_class": Decimal(SIZE_RANK[money.size_class]),
        "challenge_priority": Decimal(PRIORITY_RANK[priority]),
        "distinct_signal_kinds": Decimal(kinds),
        "risk_id": risk_id,
    }


def weighted_exposure(
    money: Money, certainty: Certainty, currency: str | None, tables: RiskTables
) -> Decimal:
    """An exact amount, or the upper end of an estimate, in ``currency``, times the certainty's
    order weight; 0 for unknown money or another currency. It only orders lists: it is never
    shown as an amount or a probability."""
    if money.currency is None or money.currency != currency:
        return Decimal(0)
    exposure = (money.amount if money.kind is MoneyKind.EXACT else money.high) or Decimal(0)
    return exposure * tables.grading.order_weight[certainty]


def size_class(share: Decimal, tables: RiskTables) -> SizeClass:
    """The size class of a share of the counted total: an ordering hint, never an amount."""
    classes = tables.grading.unknown_money_size_hint.classes
    if share >= classes["large"]:
        return SizeClass.LARGE
    return SizeClass.MEDIUM if share >= classes["medium"] else SizeClass.SMALL


def tier_of(
    facts: Facts,
    *,
    category: str,
    tables: RiskTables,
    texts: Sequence[str] = (),
    positions: int = 1,
    signals: int = 1,
    kinds: int = 1,
    track_record: TrackRecord | None = None,
) -> tuple[TierRule, Severity, list[str]]:
    """The review priority of one reminder: the first tier rule that matches its facts, then the
    floors (``texts``: its positions' folded texts), the combination raise and the track record.
    Returns the rule, the tier and the reasons."""
    rule = _first_rule(tables.grading.rules, facts)
    tier, reasons = _adjust(
        rule, facts, texts, positions, category, signals, kinds, track_record, tables
    )
    return rule, tier, reasons


def reminder_id(risk_type: str, stable_keys: Iterable[str]) -> str:
    """A reminder's id: the same for the same risk type and members, across runs."""
    joined = "|".join([risk_type, *sorted(stable_keys)])
    return "risk_" + hashlib.sha256(joined.encode()).hexdigest()[:16]


def share_of_total(amount: Decimal, currency: str | None, bill: Bill) -> Decimal | None:
    """An amount as a share of the bill's counted total, when both are in one currency."""
    if bill.counted_total and bill.currency == currency:
        return amount / abs(bill.counted_total)
    return None


# ----------------------------------------------------------------------------- merge and group
def _merge(candidates: Sequence[Candidate]) -> list[Issue]:
    parent = list(range(len(candidates)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for index, candidate in enumerate(candidates):
        keys = _keys(candidate)
        for key in sorted(keys):
            if key in owner:
                parent[root(index)] = root(owner[key])
            else:
                owner[key] = index
    issues: dict[int, Issue] = {}
    for index, candidate in enumerate(candidates):
        issues.setdefault(root(index), []).append(candidate)
    return list(issues.values())


def _keys(candidate: Candidate, *, method: bool = False) -> set[str]:
    """Its evidence keys plus, on one position, the cause there: one position and risk type is
    one finding, whichever check found it. "other" names no cause, so there the rule stands for
    it. Not for model hypotheses: two of them on one long text may have different causes (same
    causes were dropped before grading). With ``method`` the cause key also names the kind of
    check: the same kind of check on the same cause reads the same words (one signal), checks
    of different kinds stay independent signals."""
    keys = set(candidate.evidence_keys)
    if len(candidate.positions) > 1:  # shares evidence only with a finding on exactly these rows
        scope = "|".join(sorted(f"{p.table_id}/{p.row_id}" for p in candidate.positions))
        keys = {f"{key}#{scope}" for key in keys}
    if len(candidate.positions) == 1 and candidate.method is not Method.GUIDED_LLM:
        ref = candidate.positions[0]
        cause = candidate.rule_id if candidate.risk_type == OTHER else candidate.risk_type
        kind = f"|{candidate.method.value}" if method else ""
        keys.add(f"type:{cause}@{ref.table_id}/{ref.row_id}{kind}")
    return keys


def _group(issues: list[Issue]) -> list[list[Issue]]:
    reminders: dict[object, list[Issue]] = {}
    for number, issue in enumerate(issues):
        groups = frozenset(c.group for c in issue)
        key: object = number if "" in groups else groups
        reminders.setdefault(key, []).append(issue)
    return list(reminders.values())


def _strength(candidate: Candidate) -> tuple[int, int, int]:
    return (
        STATE_STRENGTH[candidate.state],
        CERTAINTY_STRENGTH[candidate.certainty],
        0 if candidate.keywords_only else 1,
    )


def _signals(issues: list[Issue]) -> tuple[int, int]:
    """(independent signals, distinct kinds of them) of the most-supported issue: candidates
    that share an evidence key, or the same cause on one position found by the same kind of
    check, are one signal (two checks reading the same words are not two confirmations)."""
    best = (1, 1)
    for issue in issues:
        components: list[tuple[set[str], set[str]]] = []  # (evidence keys, methods)
        for candidate in issue:
            keys, methods = _keys(candidate, method=True), {candidate.method.value}
            for other in [c for c in components if c[0] & keys]:
                components.remove(other)
                keys |= other[0]
                methods |= other[1]
            components.append((keys, methods))
        kinds = len({sorted(methods)[0] for _, methods in components})
        best = max(best, (len(components), kinds))
    return best


# ----------------------------------------------------------------------------- one reminder
def _risk(
    issues: list[Issue], bill: Bill, tables: RiskTables
) -> tuple[Risk, dict[str, Decimal | str]]:
    members = [c for issue in issues for c in issue]
    primary = max(members, key=_strength)
    risk_type = tables.risk_type(primary.risk_type)
    positions = _positions(c.positions for c in members)
    late = {"positions": labels([p.label for p in positions]) or "the bill"}
    money = _money(issues, positions, bill, tables)
    signals, kinds = _signals(issues)
    rules = list(dict.fromkeys(c.rule_id for c in sorted(members, key=_strength, reverse=True)))
    # The question of the strongest member that asks one (the primary's, when it asks one): a
    # finding merged with a wording rule's reminder may ask nothing, the wording rule does.
    question = next(
        (c.question for c in sorted(members, key=_strength, reverse=True) if c.question), None
    )
    # The rules are in ``rules`` and their count in ``factors.independent_signals``; the
    # explanation stays one plain statement about the bill.
    why = fill(primary.explanation or primary.title, late)
    title = primary.title
    if len(issues) > 1 and len(positions) > 1 and primary.group.startswith(FINDING_GROUP):
        # A finding's title and explanation name its own row: say that the others share them.
        more = len(positions) - 1
        title = clip(f"{title} (and {more} more with the same finding)", 300)
        why += f" The same check reports the same on {len(positions)} positions: one reminder."
    harm = primary.harm or risk_type.harm
    facts = Facts(
        harm=harm,
        state=primary.state,
        certainty=primary.certainty,
        keywords_only=all(c.keywords_only for c in members),
        share=money.share_of_total,
        lump_sum=any(c.lump_sum for c in members),
        vague=any(c.vague for c in members),
        money=money.kind,
        priority=risk_type.priority.value,
        changes_totals=any(c.changes_totals for c in members),
        found_unlinked=primary.found_unlinked,
        rules=tuple(rules),
    )
    rule, tier, reasons = tier_of(
        facts,
        category=risk_type.category,
        tables=tables,
        texts=[t for c in members for t in c.position_texts],
        positions=len(positions),
        signals=signals,
        kinds=kinds,
        track_record=primary.track_record,
    )
    risk_id = reminder_id(primary.risk_type, (c.stable_key for c in members))
    risk = Risk(
        risk_id=risk_id,
        rank=1,
        tier=tier,
        tier_rule=rule.id,
        tier_reason=" ".join(reasons),
        title=title,
        risk_type=risk_type.id,
        risk_name=risk_type.name,
        category=risk_type.category,
        direction=risk_type.direction,
        state=primary.state,
        evidence_class=primary.evidence_class or _EVIDENCE[primary.certainty],
        methods=list(dict.fromkeys(c.method for c in sorted(members, key=_strength, reverse=True))),
        rules=rules,
        positions=positions[:MAX_POSITIONS],
        positions_total=len(positions),
        quotes=_unique((q for c in members for q in c.quotes), MAX_QUOTES),
        why_risk_here=why,
        counter_evidence=_unique((e for c in members for e in c.counter_evidence), MAX_COUNTER),
        checked=list(dict.fromkeys(x for c in members for x in c.checked)),
        missing_information=list(dict.fromkeys(x for c in members for x in c.missing_information)),
        money=money,
        factors=Factors(
            harm=harm,
            certainty=primary.certainty,
            challenge_priority=risk_type.priority,
            independent_signals=signals,
            track_record=primary.track_record,
        ),
        question=fill(question, late) if question else None,
        suggested_action=fill(primary.action or tables.explanations.default_action, late),
        source_issue_ids=list(dict.fromkeys(i for c in members for i in c.source_issue_ids)),
        evidence_links=_links(members),
        absence=next((c.absence for c in members if c.absence is not None), None),
    )
    return risk, sort_values(
        tier=tier,
        state=primary.state,
        certainty=primary.certainty,
        money=money,
        currency=bill.currency,
        priority=risk_type.priority,
        kinds=kinds,
        risk_id=risk_id,
        tables=tables,
    )


def _links(members: Sequence[Candidate]) -> list[EvidenceLink]:
    """The evidence links of the members, each (label and rows) once."""
    links: dict[tuple[str, tuple[tuple[str, str], ...]], EvidenceLink] = {}
    for link in (link for c in members for link in c.evidence_links):
        links.setdefault((link.label, tuple((p.table_id, p.row_id) for p in link.positions)), link)
    return list(links.values())


def _positions(groups: Iterable[Iterable[PositionRef]]) -> list[PositionRef]:
    found: dict[tuple[str, str], PositionRef] = {}
    cells: dict[tuple[str, str], dict[tuple[str, str, str], CellRef]] = {}
    for refs in groups:
        for ref in refs:
            key = (ref.table_id, ref.row_id)
            found.setdefault(key, ref)
            cells.setdefault(key, {}).update({c.key: c for c in ref.cells})
    return [
        ref.model_copy(update={"cells": list(cells[key].values())}) for key, ref in found.items()
    ]


def _unique(items: Iterable[_Shown], limit: int) -> list[_Shown]:
    seen: dict[tuple[str | None, str], _Shown] = {}
    for item in items:
        seen.setdefault((item.position, item.text), item)
    return list(seen.values())[:limit]


# ----------------------------------------------------------------------------- money
def _money(
    issues: list[Issue], positions: list[PositionRef], bill: Bill, tables: RiskTables
) -> Money:
    per_issue = [_issue_money(issue) for issue in issues]
    known = [m for m in per_issue if m is not None]
    if len(issues) == 1 and known:
        return known[0]
    if known and len(known) == len(issues) and all(m.kind is MoneyKind.EXACT for m in known):
        currencies = {m.currency for m in known}
        if len(currencies) == 1:
            amount = sum((m.amount or Decimal(0) for m in known), Decimal(0))
            currency = next(iter(currencies))
            share = share_of_total(amount, currency, bill)
            return Money(
                kind=MoneyKind.EXACT,
                amount=amount,
                currency=currency,
                basis=f"Sum of the computed differences of {len(known)} positions.",
                share_of_total=share,
            )
    unknown = _unknown(issues, positions, bill, tables)
    # A detector's comparison amount stays visible as a reference (never as the loss).
    reference = next(
        (c.money.reference for issue in issues for c in issue if c.money and c.money.reference),
        None,
    )
    return unknown.model_copy(update={"reference": reference}) if reference else unknown


def _issue_money(issue: Issue) -> Money | None:
    """The largest exact amount of an issue (never a sum: it is one issue seen more than once),
    else its largest estimate, else ``None``."""
    exact = [c.money for c in issue if c.money is not None and c.money.kind is MoneyKind.EXACT]
    if exact:
        return max(exact, key=lambda m: m.amount or Decimal(0))
    estimates = [
        c.money for c in issue if c.money is not None and c.money.kind is MoneyKind.ESTIMATE
    ]
    if estimates:
        return max(estimates, key=lambda m: m.high or Decimal(0))
    return None


def _unknown(
    issues: list[Issue], positions: list[PositionRef], bill: Bill, tables: RiskTables
) -> Money:
    bases = [
        c.money.basis
        for issue in issues
        for c in issue
        if c.money is not None and c.money.kind is MoneyKind.UNKNOWN
    ]
    basis = bases[0] if bases else "No amount can be derived from the bill for this risk."
    by_key = {(p.table_id, p.row_id): p for p in bill.positions}
    totals = [
        abs(p.line_total)
        for ref in positions
        if (p := by_key.get((ref.table_id, ref.row_id))) is not None
        and p.line_total is not None
        and p.currency == bill.currency
    ]
    size = SizeClass.NONE
    if totals and bill.counted_total:
        size = size_class(sum(totals, Decimal(0)) / abs(bill.counted_total), tables)
        basis += (
            f" Size class '{size.value}' orders the list only: it is the share of the counted "
            "total that the positions concerned make up, not an amount at stake."
        )
    return Money(kind=MoneyKind.UNKNOWN, basis=basis[:600], size_class=size)


# ----------------------------------------------------------------------------- tiers
def _first_rule(rules: Sequence[TierRule], facts: Facts) -> TierRule:
    for rule in rules:
        if _matches(rule.when, facts):
            return rule
    return TierRule(id="T99", tier=Severity.MEDIUM, when=TierWhen(), reason="No tier rule matched.")


def _matches(when: TierWhen, f: Facts) -> bool:
    return all(
        (
            when.harm is None or when.harm is f.harm,
            when.state is None or when.state is f.state,
            when.state_in is None or f.state in when.state_in,
            when.evidence_not_only_keywords is None
            or when.evidence_not_only_keywords is not f.keywords_only,
            when.certainty is None or when.certainty is f.certainty,
            when.certainty_in is None or f.certainty in when.certainty_in,
            when.share_of_total_at_least is None
            or (f.share is not None and f.share >= when.share_of_total_at_least),
            when.lump_sum is None or when.lump_sum is f.lump_sum,
            when.vague is None or when.vague is f.vague,
            when.money is None or when.money is f.money,
            when.challenge_priority is None or when.challenge_priority.value == f.priority,
            when.changes_totals is None or when.changes_totals is f.changes_totals,
            when.found_unlinked is None or when.found_unlinked is f.found_unlinked,
            when.only_rules_in is None or set(f.rules) <= set(when.only_rules_in),
        )
    )


def _without(text: str, words: Sequence[str]) -> str:
    for word in words:
        text = text.replace(word, " ")
    return text


def _adjust(
    rule: TierRule,
    facts: Facts,
    texts: Sequence[str],
    positions: int,
    category: str,
    signals: int,
    kinds: int,
    record: TrackRecord | None,
    tables: RiskTables,
) -> tuple[Severity, list[str]]:
    grading = tables.grading
    rank = SEVERITY_RANK[rule.tier]
    reasons = [rule.reason]
    if rule.when.share_of_total_at_least is not None and not grading.thresholds_validated:
        reasons.append("The 1 % and 5 % size limits are first guesses, not measured.")
    words = grading.position_words
    for floor in grading.floors if rule.raise_by_floors else ():
        if floor.when.category_in is not None and category not in floor.when.category_in:
            continue
        if floor.when.position_is == "structural":
            hit = any(
                w in _without(t, words.not_structural) for t in texts for w in words.structural
            )
        else:
            hit = any(find(words.fire_rated_pattern, t) is not None for t in texts)
        if hit and rank < SEVERITY_RANK[floor.min_tier]:
            rank = SEVERITY_RANK[floor.min_tier]
            reasons.append(
                f"Raised to {floor.min_tier.value}: a "
                f"{floor.when.position_is.replace('_', '-')} position."
            )
    combination = grading.combination
    if (
        kinds >= combination.min_distinct_signal_kinds
        and positions <= combination.max_positions
        and facts.state is not State.CANNOT_TELL
    ):
        cap = combination.max_tier_keywords_only if facts.keywords_only else Severity.CRITICAL
        raised = min(rank + combination.raise_by, SEVERITY_RANK[cap])
        if raised > rank:
            rank = raised
            reasons.append(f"Raised: {signals} independent signals of {kinds} kinds.")
    if (
        record is not None
        and record.reviewed >= grading.track_record.min_reviews
        and Decimal(record.confirmed) / record.reviewed
        < grading.track_record.demote_if_precision_below
        and rank > SEVERITY_RANK[Severity.LOW]
    ):
        rank -= 1
        reasons.append(
            f"Lowered one tier: reviewers confirmed {record.confirmed} of {record.reviewed} "
            "earlier findings of this check."
        )
    return _TIERS[rank], reasons
