"""Wording that may leave scope, quantity or responsibility open (V01-V08).

A term is a clue, never an error. Every use of a group's terms in a position is judged; the
position is reported on the first use that nothing settles. A use is settled when the text that
settles it is found where the group says to look (``fine_if`` near the term, after it in its
clause, in the position, or in the position and its notes; ``fine_if_before`` right before it)
or when the position lists enough parts (``min_list_items``).
Groups with ``raise_when_any`` report only lump sums or positions worth a set share of the
counted total.
A group that needs a document this run does not have (``missing_sources``) asks for it
(``cannot_tell``); the others are semantic warnings.
"""

from __future__ import annotations

import re

from app.risk.bill import Bill, Position
from app.risk.checks.base import CheckResult, Outcome, evidence_key, position_quote
from app.risk.explain import action, fill, reason
from app.risk.models import STATE_STRENGTH, Candidate, Certainty, Method, ProjectContext, State
from app.risk.tables import RiskTables, WordingGroup
from app.risk.text import around, clause_bounds, find, occurrences, original_text

_LIST_SEPARATORS = re.compile(r"[\n;,•]|\s-\s")
_WHERE = {
    "near": "next to the term",
    "after": "after the term, in its clause",
    "position": "in the position",
    "position_and_notes": "in the position or its notes",
}


def check(bill: Bill, tables: RiskTables, project: ProjectContext) -> CheckResult:
    del project
    result = CheckResult()
    for group in tables.wording.groups:
        found: list[Candidate] = []
        seen = settled = small = 0
        looked: list[str] = []
        for position in bill.positions:
            terms = _terms(group, position)
            if not terms:
                continue
            seen += 1
            looked.append(position.label)
            # Every use of a term is judged: a settled first one says nothing about the others.
            term = next((t for t in terms if not _settled(group, position, t, bill, tables)), None)
            if term is None:
                settled += 1
                continue
            if group.raise_when_any and not _large(group, position, bill):
                small += 1
                continue
            found.append(_candidate(group, position, term, bill, tables))
        state = max((c.state for c in found), key=STATE_STRENGTH.__getitem__, default=State.COVERED)
        if not seen:
            state = State.NOT_APPLICABLE
        result.candidates.extend(found)
        result.outcomes.append(
            Outcome(
                group.risk_type,
                group.id,
                state,
                f"{seen} positions use a term; {settled} settled by the text, {small} below the "
                f"size threshold, {len(found)} open",
                triggered=seen,
                explained=settled,
                filtered=small,
                positions=tuple(looked),
            )
        )
    return result


def _terms(group: WordingGroup, position: Position) -> list[tuple[int, int, str]]:
    """Every use of the group's terms in the position, in reading order."""
    found = [(start, term) for term in group.terms for start in occurrences(position.folded, term)]
    return [(start, start + len(term), term) for start, term in sorted(found)]


def _settled(
    group: WordingGroup,
    position: Position,
    term: tuple[int, int, str],
    bill: Bill,
    tables: RiskTables,
) -> bool:
    window = tables.wording.defaults.window
    if group.fine_if_scope == "near":
        text = around(position.folded, term[0], term[1], window)
    elif group.fine_if_scope == "after":
        right = clause_bounds(position.folded, *term[:2], tables.components.abbreviations)[1]
        text = position.folded[term[1] : min(right, term[1] + window)]
    elif group.fine_if_scope == "position":
        text = position.folded
    else:
        text = " ".join([position.folded, *(n.folded for n in bill.notes_for(position))])
    if any(find(pattern, text) is not None for pattern in group.fine_if):
        return True
    before = position.folded[max(0, term[0] - window) : term[0]]
    if any(find(pattern, before) is not None for pattern in group.fine_if_before):
        return True
    if group.min_list_items is not None:
        parts = [p for p in _LIST_SEPARATORS.split(position.long_text) if p.strip()]
        return len(parts) >= group.min_list_items
    return False


def _large(group: WordingGroup, position: Position, bill: Bill) -> bool:
    share = None
    if (
        position.line_total is not None
        and bill.counted_total
        and position.currency == bill.currency
    ):
        share = abs(position.line_total) / bill.counted_total
    for when in group.raise_when_any:
        if when.lump_sum and position.lump_sum:
            return True
        threshold = when.share_of_total_at_least
        if threshold is not None and share is not None and share >= threshold:
            return True
    return False


def _candidate(
    group: WordingGroup,
    position: Position,
    term: tuple[int, int, str],
    bill: Bill,
    tables: RiskTables,
) -> Candidate:
    risk = tables.risk_type(group.risk_type)
    words = original_text(position.original, term[0], term[1], term[2])
    slots = {"term": words, "position": "{positions}", "quote": f"'{words}'"}
    if group.missing_sources:
        state, certainty = State.CANNOT_TELL, Certainty.UNCLEAR
    else:
        state, certainty = State.RISK, Certainty.SEMANTIC
    scope_id = bill.scope_id(position, "section")
    where = _WHERE[group.fine_if_scope]
    return Candidate(
        rule_id=group.id,
        risk_type=group.risk_type,
        method=Method.VAGUENESS,
        state=state,
        certainty=certainty,
        title=f"{risk.name}: '{words}' ({group.meaning})"[:300],
        positions=(position.ref("description", "long_description"),),
        quotes=(position_quote(position, term[0], term[1]),),
        slots=slots,
        question=fill(group.question, slots),
        checked=(f"text that settles '{words}' {where}: {group.check}",),
        missing_information=tuple(group.missing_sources),
        harm=risk.harm,
        keywords_only=True,
        lump_sum=position.lump_sum,
        vague=True,
        position_texts=(position.folded,),
        explanation=reason(
            tables,
            category=risk.category,
            method=Method.VAGUENESS,
            state=state,
            certainty=certainty,
            slots=slots,
            fallback="Found by {method_phrase}: {positions} say '{term}'; "
            + f"{group.meaning}, and nothing that settles it was found {where}.",
        ),
        action=action(tables, risk.category, slots),
        evidence_keys=frozenset({evidence_key(group.id, position)}),
        stable_key=f"{group.id}|{position.table_id}|{position.item_code or position.row_id}",
        group=f"{group.id}|{scope_id}|{state.value}",
    )
