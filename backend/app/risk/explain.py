"""Reason, question and action texts from the explanation table.

A template's ``{slots}`` are filled from values the checks found in the bill. A template whose
slots cannot all be filled is not used: the check's own sentence (reason) or the table's
default action is used instead, so no text ever shows an empty or invented slot. ``{positions}``
is filled last, when the grader knows which positions one reminder lists.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.risk.models import Certainty, Method, State
from app.risk.tables import PlanRule, RiskTables

_SLOT = re.compile(r"\{([a-z_]+)\}")
LATE_SLOTS = frozenset({"positions"})


def fill(template: str, slots: Mapping[str, str]) -> str:
    """``template`` with every slot that ``slots`` names replaced; other slots stay as they are."""
    return _SLOT.sub(lambda m: slots.get(m.group(1), m.group(0)), template)


def open_slots(text: str) -> set[str]:
    return set(_SLOT.findall(text)) - LATE_SLOTS


def verb(state: State, certainty: Certainty) -> str:
    if state is State.CANNOT_TELL:
        return "could not be decided"
    return "is" if certainty is Certainty.CONFIRMED else "may be"


def reason(
    tables: RiskTables,
    *,
    category: str,
    method: Method,
    state: State,
    certainty: Certainty,
    slots: Mapping[str, str],
    fallback: str,
) -> str:
    """The category's reason template when the check found every slot, else ``fallback``."""
    all_slots = {
        "method_phrase": tables.explanations.method_phrase[method],
        "verb": verb(state, certainty),
        **slots,
    }
    text = tables.explanations.categories.get(category)
    if text is not None:
        filled = fill(text.reason, all_slots)
        if not open_slots(filled):
            return filled
    return fill(fallback, all_slots)


def action(tables: RiskTables, category: str, slots: Mapping[str, str]) -> str:
    """The category's action when every slot is known, else the default action (ask, wait,
    record the assumption; never change the bid on its own)."""
    text = tables.explanations.categories.get(category)
    if text is not None:
        filled = fill(text.action, slots)
        if not open_slots(filled):
            return filled
    return tables.explanations.default_action


def count_of(number: int, singular: str, plural: str | None = None) -> str:
    """'1 position', '3 positions'."""
    return f"{number} {singular if number == 1 else plural or singular + 's'}"


def labels(names: Sequence[str], limit: int = 5) -> str:
    """'A', 'A and B', 'A, B and C', 'A, B, C, D, E and 3 more'."""
    if len(names) <= 1:
        return "".join(names)
    shown = list(names[:limit])
    rest = len(names) - len(shown)
    if rest:
        return f"{', '.join(shown)} and {rest} more"
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


@dataclass(frozen=True, slots=True)
class Fact:
    """A fact given with a reminder from outside the bill, with where it was read."""

    fact_id: str
    source_id: str
    text: str


@dataclass(frozen=True, slots=True)
class Step:
    kind: str
    text: str
    positions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    """The summary and next steps for a given reminder, from the ``plan`` texts of the
    explanation table. ``used_facts`` are cited whole and verbatim; the templates name no
    standard, amount or probability, so ``standard_references`` is always empty."""

    summary: str
    used_facts: tuple[Fact, ...]
    steps: tuple[Step, ...]
    mode: str = "template"
    standard_references: tuple[str, ...] = ()


def plan_for(
    tables: RiskTables,
    *,
    state: str,
    evidence_class: str,
    method: str,
    money: str,
    facts: Sequence[Fact],
    positions: Sequence[str],
    harm: str | None = None,
    category: str | None = None,
) -> Plan:
    """The template plan for a reminder whose state, evidence class, method and money kind are
    given (never changed here). Text in the facts is data: it is quoted, never followed.
    ``harm`` and ``category`` (the risk type's) choose steps only when given."""
    texts = tables.explanations.plan
    if texts is None:
        raise ValueError("the explanation table of this profile has no plan texts")
    facts_given = {
        "state": state,
        "evidence_class": evidence_class,
        "method": method,
        "money": money,
        "harm": harm or "",
        "category": category or "",
    }
    first = next(r for r in texts.first if _holds(r, facts_given))
    kinds = [first.kind, *(r.kind for r in texts.also if _holds(r, facts_given))]
    named = labels(list(positions)) or "the position"
    slots = {"positions": named, "fact": facts[0].text if facts else "(no fact given)"}
    phrase = (
        tables.explanations.method_phrase.get(Method(method)) if method in set(Method) else None
    )
    summary = fill(texts.summary, {**slots, "method_phrase": phrase or method})
    steps = tuple(
        Step(kind, fill(texts.texts[kind], slots), tuple(positions))
        for kind in dict.fromkeys(kinds)
    )
    return Plan(summary=summary, used_facts=tuple(facts), steps=steps)


def _holds(rule: PlanRule, given: Mapping[str, str]) -> bool:
    return all(given.get(field, "") in allowed for field, allowed in rule.when.items())
