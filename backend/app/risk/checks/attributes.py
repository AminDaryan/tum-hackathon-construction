"""Values a kind of item must state (A01-A1x): concrete class, steel grade, pipe size, ...

A position is of a kind when its short text names one of the kind's words, and, for a kind
with ``other_work_any``, when one of its component words belongs to this work: "Unterquerung
bestehender Kabel" or "Antenne mit Kabel" names a cable but lays no new power cable.

A required value counts only for the component itself. It attaches to the nearest marker
before it (a component word, or a word of ``other_parts_any`` such as "Schacht"), else to the
nearest after it, within ``near`` characters; it counts when that marker is a component word of
this kind. With ``link: clause`` (a test and its standard) the value may lie anywhere in the
component word's clause, and the clause's word order decides: the first marker after it before
the next comma ("nach DIN EN 1610 prüfen", "Rohre nach DIN EN 12201 liefern"), else the
nearest before it. Else the value counts when a general or section note states it (with the
component word, with the position's own item code, or with a word such as "alle" that makes it
apply to every component), or when a position the item explicitly refers to states it. A
missing value is a semantic warning (the text does not say it), or ``cannot_tell`` when the
position sends the reader to a drawing, the structural calculation or another document that
this run does not have.
"""

from __future__ import annotations

import re
from typing import Literal

from app.risk.bill import Bill, Position
from app.risk.checks.base import CheckResult, Outcome, evidence_key, hits, position_quote, says
from app.risk.explain import action, count_of, fill, reason
from app.risk.models import (
    STATE_STRENGTH,
    Candidate,
    Certainty,
    Method,
    ProjectContext,
    State,
)
from app.risk.tables import AttributeKind, RiskTables
from app.risk.text import clause, clause_bounds, clip, find_all, fold

_PHRASE_END = re.compile(r"[,;]")
Marker = tuple[int, int, bool]  # start, end, and whether it is a component word of the kind


def check(bill: Bill, tables: RiskTables, project: ProjectContext) -> CheckResult:
    del project  # every bill states these values
    result = CheckResult()
    for kind in tables.attributes.item_kinds:
        # Positions that name the kind's words, also when they are ruled out ("Rohrgraben").
        named = tuple(
            p.label for p in bill.positions if any(w in p.folded_short for w in kind.when_any)
        )
        positions = [p for p in bill.positions if _is_kind(kind, p, tables)]
        if not positions:
            result.outcomes.append(
                Outcome(
                    kind.risk_type,
                    kind.id,
                    State.NOT_APPLICABLE,
                    "no position of this kind",
                    positions=named,
                )
            )
            continue
        found = [
            c
            for p in positions
            for name, pattern in kind.required.items()
            if (c := _value(kind, name, pattern, p, bill, tables)) is not None
        ]
        state = max((c.state for c in found), key=STATE_STRENGTH.__getitem__, default=State.COVERED)
        result.candidates.extend(found)
        result.outcomes.append(
            Outcome(
                kind.risk_type,
                kind.id,
                state,
                f"{count_of(len(positions), 'position')} of this kind; "
                f"{count_of(len(found), 'missing value')}"
                + (f". {kind.note}" if kind.note else ""),
                triggered=len(positions) * len(kind.required),
                explained=len(positions) * len(kind.required) - len(found),
                positions=named,
            )
        )
    return result


def _is_kind(kind: AttributeKind, position: Position, tables: RiskTables) -> bool:
    return (
        any(word in position.folded_short for word in kind.when_any)
        and (not kind.and_any or any(word in position.folded for word in kind.and_any))
        and not any(word in position.folded for word in kind.unless_any)
        and (
            not kind.other_work_any
            or any(own for *_, own in _components(kind, position.folded, tables))
        )
    )


def _components(kind: AttributeKind, folded: str, tables: RiskTables) -> list[Marker]:
    """The component words of the kind, each with whether it belongs to this work."""
    if kind.near_word is not None:
        found = hits(folded, (), kind.near_word)
    else:
        found = hits(folded, kind.when_any)
    return [(start, end, not _other_work(kind, folded, start, end, tables)) for start, end in found]


def _other_work(kind: AttributeKind, folded: str, start: int, end: int, tables: RiskTables) -> bool:
    """A word of other work in the component word itself ("Kabelgraben", "Antennenkabel"), or
    nearest before it in its clause within ``near`` characters, with no word of new work after
    it ("Unterquerung bestehender Kabel", but "..., neues Kabel")."""
    if not kind.other_work_any:
        return False
    left, right = start, end
    while left > 0 and folded[left - 1].isalnum():
        left -= 1
    while right < len(folded) and folded[right].isalnum():
        right += 1
    if says(folded[left:right], kind.other_work_any):
        return True
    defaults = tables.attributes.defaults
    clause_left = clause_bounds(folded, start, end, tables.components.abbreviations)[0]
    before = folded[max(clause_left, left - defaults.near) : left]
    other = max(before.rfind(word) for word in kind.other_work_any)
    new = max(before.rfind(word) for word in defaults.new_any)
    return other > new


def _stated(kind: AttributeKind, pattern: str, folded: str, tables: RiskTables) -> bool:
    """Whether a value of ``pattern`` in ``folded`` belongs to a component word of the kind."""
    markers = _components(kind, folded, tables)
    if not any(own for *_, own in markers):
        return False
    markers += [(start, end, False) for start, end in hits(folded, kind.other_parts_any)]
    for start, end, _ in find_all(pattern, folded):
        if kind.link == "clause":
            marker = _in_clause(folded, start, end, markers, tables)
        else:
            marker = _nearest(start, end, markers, tables.attributes.defaults.near)
        if marker is not None and marker[2]:
            return True
    return False


def _nearest(start: int, end: int, markers: list[Marker], near: int) -> Marker | None:
    """The marker a value at [start, end) attaches to: one it overlaps, else the nearest before
    it, else the nearest after it, within ``near`` characters."""
    inside = [m for m in markers if m[0] < end and start < m[1]]
    before = [m for m in markers if m[1] <= start and start - m[1] <= near]
    after = [m for m in markers if m[0] >= end and m[0] - end <= near]
    if inside:
        return max(inside, key=lambda m: m[2])
    if before:
        return max(before, key=lambda m: m[1])
    return min(after, key=lambda m: m[0]) if after else None


def _in_clause(
    folded: str, start: int, end: int, markers: list[Marker], tables: RiskTables
) -> Marker | None:
    """The marker a value attaches to by the word order of its clause: German puts the verb
    last, so the first marker after the value before the next comma decides ("nach DIN EN 1610
    auf Dichtheit prüfen"); without one, the nearest before it in the clause ("Druckprüfung der
    Leitung nach DIN EN 805")."""
    left, right = clause_bounds(folded, start, end, tables.components.abbreviations)
    stop = _PHRASE_END.search(folded, end, right)
    phrase_end = stop.start() if stop else right
    after = [m for m in markers if end <= m[0] < phrase_end]
    before = [m for m in markers if m[0] >= left and m[1] <= start]
    if after:
        return min(after, key=lambda m: m[0])
    return max(before, key=lambda m: m[1]) if before else None


def _names(text: str, code: str | None) -> bool:
    """Whether ``text`` names the position by its own item code ("Für Position 01.0010 gilt
    Expositionsklasse XC2"), not a longer code that starts with it."""
    return (
        bool(code)
        and re.search(rf"(?<![\w.]){re.escape(fold(code or ''))}(?!\w|\.\d)", text) is not None
    )


def _value(
    kind: AttributeKind, name: str, pattern: str, position: Position, bill: Bill, tables: RiskTables
) -> Candidate | None:
    """``None`` when the value is stated; else the candidate that asks for it."""
    defaults = tables.attributes.defaults
    words = tables.components
    if _stated(kind, pattern, position.folded, tables):
        return None
    for note in bill.notes_for(position):
        for start, end, _ in find_all(pattern, note.folded):
            text = clause(note.folded, start, end, words.abbreviations)
            if (
                any(w in text for w in kind.when_any)
                or says(text, defaults.general_any)
                or _names(text, position.item_code)
            ):
                return None
    for reference in position.references:
        other = bill.by_code(reference)
        if other is not None and _stated(kind, pattern, other.folded, tables):
            return None
    risk = tables.risk_type(kind.risk_type)
    attribute = name.replace("_", " ")
    documents = says(position.folded, defaults.documents_any)
    anchor = sorted(_components(kind, position.folded, tables), key=lambda m: not m[2])
    quote = position_quote(
        position, *(anchor[0][:2] if anchor else (0, len(position.folded_short)))
    )
    slots = {
        "attribute": attribute,
        "position": "{positions}",
        "quote": f"'{clip(position.short_text, 120)}'",
        "missing": f"the {attribute}",
    }
    key: Literal["attribute_in_documents", "attribute_missing"]
    missing: tuple[str, ...]
    if documents:
        state, certainty, key = State.CANNOT_TELL, Certainty.UNCLEAR, "attribute_in_documents"
        missing = (f"the drawing or document the position refers to ('{documents}')",)
    else:
        state, certainty, key = State.RISK, Certainty.SEMANTIC, "attribute_missing"
        missing = ()
    scope_id = bill.scope_id(position, "section")
    return Candidate(
        rule_id=kind.id,
        risk_type=kind.risk_type,
        method=Method.ATTRIBUTE_CONSISTENCY,
        state=state,
        certainty=certainty,
        title=f"{risk.name}: {attribute} not stated"[:300],
        positions=(position.ref("description", "long_description"),),
        quotes=(quote,),
        slots=slots,
        question=fill(tables.explanations.questions[key], slots),
        checked=(
            (
                "the clause of the component word"
                if kind.link == "clause"
                else f"the position text within {defaults.near} characters of the component word"
            ),
            f"{len(bill.notes_for(position))} general and section notes",
            f"{len(position.references)} positions the item refers to",
        ),
        missing_information=missing,
        absence="in_document_not_provided" if documents else "not_found_in_searched_scope",
        harm=risk.harm,
        keywords_only=True,
        position_texts=(position.folded,),
        explanation=reason(
            tables,
            category=risk.category,
            method=Method.ATTRIBUTE_CONSISTENCY,
            state=state,
            certainty=certainty,
            slots=slots,
            fallback="Found by {method_phrase}: {positions} do not state the {attribute}"
            + (" and refer to another document for it." if documents else "."),
        ),
        action=action(tables, risk.category, slots),
        evidence_keys=frozenset({evidence_key(f"{kind.id}:{name}", position)}),
        stable_key=f"{kind.id}:{name}|{position.table_id}|{position.item_code or position.row_id}",
        group=f"{kind.id}:{name}|{scope_id}|{state.value}",
    )
