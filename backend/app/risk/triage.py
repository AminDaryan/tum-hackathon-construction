"""Keep the review burden small: which reminders reach the main list, which stay in the record.

The main list holds reminders with concrete evidence, a noteworthy impact and a next action
(``main_list`` of ``grading.yaml``: state ``risk``, tier medium or above), plus every safety
doubt at that tier whatever its state. Every other reminder stays in the check record with its
own state, ranked; an open question (``cannot_tell``) is not a to-do of its own: open questions
are grouped by the document they need, or by their rule and cause, and asked once. Nothing in
the record is marked as passed. Reminders made only of unconfirmed model
hypotheses are experimental supplements: never in the main list, always after the tasks of
the checks (``is_supplement``).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.issue import SEVERITY_RANK
from app.risk.checks.base import Outcome
from app.risk.explain import count_of, labels
from app.risk.models import (
    CoverageRow,
    Funnel,
    LinkKind,
    Method,
    OpenQuestion,
    QuestionKind,
    Risk,
    State,
)
from app.risk.tables import RiskTables

MAX_LABELS = 10


def triage(
    risks: Sequence[Risk], tables: RiskTables
) -> tuple[list[Risk], list[Risk], list[OpenQuestion]]:
    """(main list, check record, grouped open questions); both lists ranked from 1."""
    rule = tables.grading.main_list
    floor = SEVERITY_RANK[rule.min_tier]
    main: list[Risk] = []
    record: list[Risk] = []
    supplements = [r for r in risks if is_supplement(r)]
    for risk in risks:
        if is_supplement(risk):
            continue
        noteworthy = SEVERITY_RANK[risk.tier] >= floor
        visible = risk.state in rule.states or risk.factors.harm in rule.always_show_harm
        (main if noteworthy and visible else record).append(risk)
    return (
        _ranked(main),
        _ranked([*record, *supplements]),
        _questions([r for r in record if r.state is State.CANNOT_TELL])
        + _questions([r for r in supplements if r.state is State.CANNOT_TELL], experimental=True),
    )


def is_supplement(risk: Risk) -> bool:
    """A reminder made only of model hypotheses that no person has confirmed: an experimental
    supplement to verify. It never enters the main list, it comes after every reminder and
    question of the checks (in every display order), and it joins no question of theirs: adding
    it changes no order, tier, evidence or money of the base tasks."""
    return set(risk.methods) == {Method.GUIDED_LLM}


def funnel(
    outcomes: Sequence[Outcome],
    findings: int,
    merged: int,
    main: Sequence[Risk],
    record: Sequence[Risk],
    questions: Sequence[OpenQuestion],
    rows: Sequence[CoverageRow],
) -> Funnel:
    triggered = sum(o.triggered for o in outcomes) + findings
    explained = sum(o.explained for o in outcomes)
    small = sum(o.filtered for o in outcomes)
    missing = [
        f"{q.topic}: {count_of(len(q.reminder_ids), 'open question')} on "
        f"{count_of(q.positions_total, 'position')} "
        f"({', '.join(q.rules[:8])})"
        for q in questions
        if q.kind == "missing_document"
    ]
    # A coverage row with rules has a check that found no usable data; one without has no check.
    idle = [row.risk_type for row in rows if row.state is State.NOT_CHECKABLE and row.rules]
    if idle:
        missing.append(
            f"{count_of(len(idle), 'risk type')} "
            f"{'has' if len(idle) == 1 else 'have'} a check that could not run on this data "
            f"({labels(idle, 12)})"
        )
    unchecked = sum(1 for row in rows if not row.rules)
    missing.append(
        f"{count_of(unchecked, 'risk type')} of the catalogue "
        f"{'has' if unchecked == 1 else 'have'} no check in this version (taxonomy entry only)"
    )
    return Funnel(
        raw_doubts=triggered,
        explained_automatically=explained,
        below_size_threshold=small,
        open_after_search=triggered - explained - small,
        after_merging=merged,
        main_list=len(main),
        kept_in_record=len(record),
        open_question_groups=len(questions),
        checks_missing_information=missing,
    )


def _ranked(risks: list[Risk]) -> list[Risk]:
    return [
        r.model_copy(update={"rank": rank, "priority_rank": rank})
        for rank, r in enumerate(risks, start=1)
    ]


def _questions(open_: list[Risk], *, experimental: bool = False) -> list[OpenQuestion]:
    groups: dict[tuple[QuestionKind, str, str], list[Risk]] = {}
    for risk in open_:
        # A model hypothesis is its own question unless it shares a missing document.
        alone = risk.risk_id if Method.GUIDED_LLM in risk.methods else ""
        key: tuple[QuestionKind, str, str]
        if risk.missing_information:
            key = ("missing_document", risk.missing_information[0], "")
        elif any(e.link is LinkKind.NOT_LINKED for e in risk.counter_evidence):
            key = ("not_linked", risk.rules[0], "")
        elif Method.DEPENDENCY in risk.methods:
            key = ("not_found", risk.rules[0], "")
        else:
            key = ("other", risk.rules[0], alone)
        groups.setdefault(key, []).append(risk)
    questions = []
    for (kind, topic, _), members in groups.items():
        found = list(dict.fromkeys(p.label for m in members for p in m.positions))
        total = sum(m.positions_total for m in members)
        rules = list(dict.fromkeys(rule for m in members for rule in m.rules))
        first = members[0]
        if kind == "missing_document":
            question = (
                f"Please provide {topic}. It is needed to decide "
                f"{count_of(len(members), 'open question')} on {count_of(total, 'position')} "
                f"({labels(found, 5)})."
            )
            title = topic
        else:
            question = first.question or first.suggested_action
            if len(members) > 1:
                question += (
                    f" The same question is open for {count_of(len(members) - 1, 'more group')}."
                )
            title = (
                f"{topic} {first.risk_name}: "
                + {
                    "not_linked": "work found elsewhere, but not tied to the component",
                    "not_found": "no position found; it may be included without its own item",
                    "other": first.title,
                }[kind]
            )
        model = sum(Method.GUIDED_LLM in m.methods for m in members)
        questions.append(
            OpenQuestion(
                kind=kind,
                topic=title,
                source="checks" if not model else "discovery" if model == len(members) else "both",
                experimental=experimental,
                rules=rules,
                risk_types=list(dict.fromkeys(m.risk_type for m in members)),
                positions_total=total,
                positions=found[:MAX_LABELS],
                question=question,
                reminder_ids=[m.risk_id for m in members],
                # One request for a document can serve different questions: each stays listed.
                serves=list(dict.fromkeys(m.question or m.suggested_action for m in members)),
            )
        )
    return questions
