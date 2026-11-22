"""Scope dependencies: "if the bill has A, the same scope should also have B" (D01-D30).

For each position that triggers a rule, the check looks for B in this order and stops at the
first answer:

1. the position itself: an exception it states (``unless``), or B named without "paid
   separately" (B included, or done by others);
2. the general notes and the notes of its sections: B with "included in the unit prices" or
   "by others";
3. positions anywhere in the bill that are *linked* to it (explicit reference, or a shared
   component, system, room or axis key; see :func:`app.risk.bill.link`): covered;
4. positions in the rule's search scope that name B but are not linked: candidates only, the
   result is ``cannot_tell`` ("found, but nothing ties it to this component").

Nothing found is never called an omission: VOB/A lets work that is part of the contract duties
go without its own item, and only this bill was searched. With ``on_missing: question`` the
result is ``cannot_tell`` with a clarification question; ``on_missing: signal`` makes it a
semantic warning. Trigger words count in a position's short text (what the position is);
rules that also need ``and_any`` words, a depth or a weight are specific enough to read the
long text as well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.risk.bill import Bill, Position, link
from app.risk.checks.base import CheckResult, Outcome, evidence_key, hits, position_quote, says
from app.risk.explain import action, count_of, fill, labels, reason
from app.risk.models import (
    STATE_STRENGTH,
    Absence,
    Candidate,
    Certainty,
    CounterEvidence,
    LinkKind,
    Method,
    ProjectContext,
    Quote,
    State,
)
from app.risk.tables import DependencyRule, RiskTables
from app.risk.text import clause, clause_bounds, find, find_all, original_span, quote

Kind = Literal["covered", "unlinked", "separate", "open", "missing", "document"]
# What a result says about the absence of the expected work: not found in what was searched,
# left to a document that was not provided, or stated by the bill itself.
_ABSENCE: dict[str, Absence | None] = {
    "covered": None,
    "unlinked": "not_found_in_searched_scope",
    "missing": "not_found_in_searched_scope",
    "document": "in_document_not_provided",
    "separate": "stated_in_bill",
    "open": "stated_in_bill",
}
MAX_EVIDENCE = 4  # counter-evidence kept per position


@dataclass(slots=True)
class _Result:
    position: Position
    kind: Kind
    trigger: Quote
    evidence: list[CounterEvidence] = field(default_factory=list)
    by: Position | None = None  # the other position whose text covers it
    document: str | None = None  # the document the position leaves the work to


def check(bill: Bill, tables: RiskTables, project: ProjectContext) -> CheckResult:
    result = CheckResult()
    for rule in tables.dependencies.rules:
        result.extend(_rule(rule, bill, tables, project))
    return result


def _rule(
    rule: DependencyRule, bill: Bill, tables: RiskTables, project: ProjectContext
) -> CheckResult:
    if rule.context and not set(rule.context) & set(project.project_types):
        # Project types are clues read from the bill's words. None read is "unknown", not
        # "another kind of project": the rule cannot be applied, which is not a pass.
        found = ", ".join(project.project_types)
        state = State.NOT_APPLICABLE if found else State.NOT_CHECKABLE
        return CheckResult(
            outcomes=[
                Outcome(
                    rule.risk_type,
                    rule.id,
                    state,
                    f"applies to {', '.join(rule.context)} projects; project types read from the "
                    f"bill: {found or 'none (the type is unknown)'}",
                )
            ]
        )
    negations = tables.dependencies.defaults.negations_any
    # The positions the rule looks at closely: those that name its trigger (also when they are
    # ruled out, "kein Grundwasser"), and below the positions that cover them.
    named = [
        p for p in bill.positions if hits(_trigger_text(rule, p), rule.if_any, rule.if_pattern)
    ]
    triggers = [
        (p, span) for p in bill.positions if (span := _trigger(rule, p, negations)) is not None
    ]
    expected = {p.key: hits(p.folded, rule.expect_any, rule.expect_pattern) for p in bill.positions}
    # A position that names the expected work but leaves it to another document applies the
    # rule whatever its trigger words: it asks for the document instead of passing as "no
    # trigger" ("Bewehrung siehe Anlage A-01").
    seen = {p.key for p, _ in triggers}
    deferred = [
        (p, span)
        for p in bill.positions
        if p.key not in seen and (span := _deferred(p, expected[p.key], tables)) is not None
    ]
    triggers += deferred
    named += [p for p, _ in deferred]
    if not triggers:
        return CheckResult(
            outcomes=[
                Outcome(
                    rule.risk_type,
                    rule.id,
                    State.NOT_APPLICABLE,
                    "no position triggers it",
                    positions=tuple(p.label for p in named),
                )
            ]
        )
    results = [_resolve(rule, p, span, bill, tables, expected) for p, span in triggers]
    scope = rule.scope or tables.dependencies.defaults.scope
    candidates = [_candidate(rule, scope, r, bill, tables) for r in results if r.kind != "covered"]
    covered = len(results) - len(candidates)
    state = max(
        (c.state for c in candidates), key=STATE_STRENGTH.__getitem__, default=State.COVERED
    )
    return CheckResult(
        candidates=candidates,
        outcomes=[
            Outcome(
                rule.risk_type,
                rule.id,
                state,
                f"{count_of(len(results), 'position')} "
                f"{'triggers' if len(results) == 1 else 'trigger'} it; "
                f"{covered} covered, {len(candidates)} open",
                triggered=len(results),
                explained=covered,
                positions=tuple(
                    dict.fromkeys(p.label for p in [*named, *(r.by for r in results if r.by)])
                ),
            )
        ],
    )


def _trigger(
    rule: DependencyRule, position: Position, negations: list[str]
) -> tuple[int, int] | None:
    text = _trigger_text(rule, position)
    found = [
        span
        for span in hits(text, rule.if_any, rule.if_pattern)
        if not _negated(text, span[0], negations)
    ]
    if not found:
        return None
    if rule.and_any and not any(stem in position.folded for stem in rule.and_any):
        return None
    if (
        rule.depth_pattern is not None
        and rule.depth_over_m is not None
        and not says(position.folded, rule.regardless_of_depth_any)
    ):
        depth = _largest_number(rule.depth_pattern, position.folded)
        if depth is None or depth <= rule.depth_over_m:
            return None
    if rule.weight_pattern is not None and find(rule.weight_pattern, position.folded) is None:
        return None
    # The short text starts the folded text, so its positions are positions in the whole text.
    return found[0]


def _deferred(
    position: Position, spans: list[tuple[int, int]], tables: RiskTables
) -> tuple[int, int] | None:
    """The first expected word whose clause refers to another document, or ``None``."""
    if _document(position, spans, tables) is None:
        return None
    return spans[0] if spans else None


def _document(
    position: Position, spans: list[tuple[int, int]], tables: RiskTables
) -> tuple[str, tuple[int, int]] | None:
    """(the document's name as written, the span of the reference) for the first expected word
    whose clause leaves the work to an identified document (its name has a number), else
    ``None``. A position whose text starts with the expected word is that work, specified by
    the document; an unnumbered "gemäß Plan" is asked about by the wording check."""
    pattern = tables.dependencies.defaults.document_pattern
    if pattern is None:
        return None
    for start, end in spans:
        if start == 0:
            continue
        left, right = clause_bounds(position.folded, start, end, tables.components.abbreviations)
        found = find(pattern, position.folded[left:right])
        if found is None:
            continue
        match = found[2]
        if left + found[0] <= start < left + found[1]:
            continue  # the word is part of the document's name ("Bewehrungsplan")
        begin = left + found[0] + match.start("document") - match.start()
        finish = left + found[0] + match.end("document") - match.start()
        name = original_span(position.original, begin, finish).rstrip(".,;: ")
        if any(c.isdigit() for c in name):
            return name, (left + found[0], left + found[1])
    return None


def _trigger_text(rule: DependencyRule, position: Position) -> str:
    """The short text, or the whole text for a rule that also reads words or numbers there."""
    wide = bool(rule.and_any or rule.depth_pattern or rule.weight_pattern)
    return position.folded if wide else position.folded_short


def _negated(folded: str, start: int, negations: list[str]) -> bool:
    """A negation word at most two words before the trigger word ("kein Grundwasser", "ohne
    drückendes Grundwasser"): the bill says the trigger is absent."""
    if not negations:
        return False
    words = "|".join(re.escape(n) for n in negations)
    return (
        re.search(rf"\b(?:{words})\s+(?:[\w-]+\s+){{0,2}}$", folded[max(0, start - 80) : start])
        is not None
    )


def _largest_number(pattern: str, folded: str) -> Decimal | None:
    numbers: list[Decimal] = []
    for _, _, match in find_all(pattern, folded):
        for group in match.groups():
            if group:
                try:
                    numbers.append(Decimal(group.replace(",", ".")))
                except InvalidOperation:  # pragma: no cover - the pattern groups digits only
                    continue
    return max(numbers, default=None)


def _resolve(
    rule: DependencyRule,
    position: Position,
    span: tuple[int, int],
    bill: Bill,
    tables: RiskTables,
    expected: dict[str, list[tuple[int, int]]],
) -> _Result:
    words = tables.components
    trigger = position_quote(position, *span)
    # 1. The position itself.
    for phrase in rule.unless:
        start = position.folded.find(phrase)
        if start >= 0:
            return _Result(position, "covered", trigger)
    document = _document(position, expected[position.key], tables)
    if document is not None:
        # The position names the work but leaves it to a document this run does not have.
        name, (start, end) = document
        return _Result(
            position,
            "document",
            trigger,
            [
                CounterEvidence(
                    position=position.label,
                    source="position text",
                    text=quote(position.original, start, end),
                    link=LinkKind.SAME_POSITION,
                    detail=f"the position leaves this to {name}, which was not provided; its "
                    "content was not read",
                )
            ],
            document=name,
        )
    separate: list[CounterEvidence] = []
    for start, end in expected[position.key]:
        text = clause(position.folded, start, end, words.abbreviations)
        if says(text, words.separate_phrases):
            separate.append(
                CounterEvidence(
                    position=position.label,
                    source="position text",
                    text=quote(position.original, start, end),
                    link=LinkKind.SAME_POSITION,
                    detail="the position names the work but says it is paid separately or excluded",
                )
            )
            continue
        if rule.open_pattern is not None and find(rule.open_pattern, text) is not None:
            continue  # named, but its clause says it is not decided yet ("AVV noch festzulegen")
        return _Result(position, "covered", trigger)
    if rule.open_pattern is not None:
        found = find(rule.open_pattern, position.folded)
        if found is not None:
            return _Result(
                position,
                "open",
                trigger,
                [
                    CounterEvidence(
                        position=position.label,
                        source="position text",
                        text=quote(position.original, found[0], found[1]),
                        link=LinkKind.SAME_POSITION,
                        detail=rule.open_means or "the bill says it is not decided yet",
                    )
                ],
            )
    # 2. General notes and section notes.
    neutral: list[CounterEvidence] = []
    for note in bill.notes_for(position):
        for start, end in hits(note.folded, rule.expect_any, rule.expect_pattern):
            text = clause(note.folded, start, end, words.abbreviations)
            shown = quote(note.text, start, end)
            if says(text, words.separate_phrases):
                separate.append(
                    CounterEvidence(
                        source=note.source,
                        text=shown,
                        link=LinkKind.NOTE,
                        detail="the note says this work is paid separately",
                    )
                )
            elif says(text, words.included_phrases) or says(text, words.by_others_phrases):
                return _Result(position, "covered", trigger)
            else:
                neutral.append(
                    CounterEvidence(
                        source=note.source,
                        text=shown,
                        link=LinkKind.NOT_LINKED,
                        detail="the note names the work but does not say it is included",
                    )
                )
            break  # one clause per note is enough to decide
    # 3. Linked positions anywhere; unlinked ones in the search scope are candidates only.
    scope = rule.scope or tables.dependencies.defaults.scope
    in_scope = {p.key for p in bill.in_scope(bill.scope_id(position, scope))}
    unlinked: list[CounterEvidence] = []
    for other in bill.positions:
        found_at = expected[other.key]
        if other.key == position.key or not found_at:
            continue
        kind, why = link(position, other, position.folded[span[0] : span[1]])
        if kind is LinkKind.DIFFERENT or (
            kind is LinkKind.NOT_LINKED and other.key not in in_scope
        ):
            continue
        evidence = CounterEvidence(
            position=other.label,
            source="position text",
            text=quote(other.original, *found_at[0]),
            link=kind,
            detail=why,
        )
        if kind in (LinkKind.EXPLICIT_REFERENCE, LinkKind.SHARED_KEY):
            return _Result(position, "covered", trigger, by=other)
        unlinked.append(evidence)
    if unlinked or neutral:
        return _Result(position, "unlinked", trigger, (unlinked + neutral)[:MAX_EVIDENCE])
    if separate:
        return _Result(position, "separate", trigger, separate[:MAX_EVIDENCE])
    return _Result(position, "missing", trigger)


def _candidate(
    rule: DependencyRule, scope: str, result: _Result, bill: Bill, tables: RiskTables
) -> Candidate:
    risk = tables.risk_type(rule.risk_type)
    on_missing = rule.on_missing or tables.dependencies.defaults.on_missing
    position = result.position
    scope_id = bill.scope_id(position, scope)
    expected = rule.expect_label
    candidates = labels([e.position or e.source for e in result.evidence])
    questions = tables.explanations.questions
    slots = {
        "expected": expected,
        "trigger_items": "{positions}",
        "candidates": candidates,
        "searched": f"the position, its notes and {bill.scope_title(scope_id)}",
    }
    state, certainty = State.CANNOT_TELL, Certainty.UNCLEAR
    # The bill itself says the value is not decided yet: a stated gap, as a missing value is.
    if result.kind == "open" or (result.kind == "missing" and on_missing == "signal"):
        state, certainty = State.RISK, Certainty.SEMANTIC
    if result.kind == "unlinked":
        question = questions["dependency_unlinked"]
        title = f"{risk.name}: {expected} found, but not tied to this component"
        why = (
            "Found by {method_phrase}: {positions} need {expected}. It appears in {candidates}, "
            "but nothing (same component, system, room, axis or a reference) ties it to them."
        )
    elif result.kind == "separate":
        question = questions["dependency_separate"]
        title = f"{risk.name}: {expected} paid separately, no position found"
        why = (
            "Found by {method_phrase}: the bill says {expected} is paid separately, but no "
            "position for it is tied to {positions}."
        )
    elif result.kind == "document":
        name = result.document or "the document it names"
        slots["document"] = name
        question = (
            "Please provide " + name + ": {positions} leave " + expected + " to it, and it was "
            "not part of the documents read."
        )
        title = f"{risk.name}: {expected} left to {name}, which was not provided"
        why = (
            "Found by {method_phrase}: {positions} leave " + expected + " to " + name + ", which "
            "was not provided; what it says was not read or guessed."
        )
    elif result.kind == "open":
        question = (
            "The bill leaves this open for {positions}. Which " + expected + " applies, and how "
            "is it to be priced until it is decided?"
        )
        title = f"{risk.name}: left open in the bill"
        why = "Found by {method_phrase}: {positions} say the value is not decided yet."
    else:
        question = questions["dependency_not_found"]
        title = f"{risk.name}: no position for {expected} found"
        why = (
            "Found by {method_phrase}: {positions} need {expected}, and no linked position or "
            "note for it was found (searched {searched}). The work may still be included in "
            "other positions without its own item."
        )
    checked = [
        "the position text (exceptions and inclusions)",
        f"{len(bill.notes_for(position))} general and section notes",
        "positions anywhere in the bill that name the same component, system, room or axis, "
        "or refer to the position",
        f"other positions of {bill.scope_title(scope_id)}",
    ]
    missing = [slots["document"]] if result.kind == "document" else []
    if scope == "project":
        missing.append("documents of other trades or lots (only this bill was searched)")
    return Candidate(
        rule_id=rule.id,
        risk_type=rule.risk_type,
        method=Method.DEPENDENCY,
        state=state,
        certainty=certainty,
        title=title[:300],
        positions=(position.ref("description"),),
        quotes=(result.trigger,),
        slots=slots,
        question=fill(question, slots),
        checked=tuple(checked),
        missing_information=tuple(missing),
        counter_evidence=tuple(result.evidence),
        harm=rule.harm or risk.harm,
        keywords_only=result.kind != "separate",
        lump_sum=position.lump_sum,
        found_unlinked=result.kind == "unlinked",
        absence=_ABSENCE[result.kind],
        position_texts=(position.folded,),
        explanation=reason(
            tables,
            category=risk.category,
            method=Method.DEPENDENCY,
            state=state,
            certainty=certainty,
            slots=slots,
            fallback=why,
        )
        + (f" {rule.note}" if rule.note else ""),
        action=action(tables, risk.category, slots),
        evidence_keys=frozenset({evidence_key(rule.id, position)}),
        stable_key=f"{rule.id}|{position.table_id}|{position.item_code or position.row_id}",
        group=f"{rule.id}|{scope_id}|{result.kind}",
    )
