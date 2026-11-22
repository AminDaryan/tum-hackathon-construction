"""The short text and the long text of one position state different values (C01-C03), and a
text names a position of this bill that the bill does not have (C04).

C01-C03 are reported only when the short text states exactly one value and the long text states
values of the same kind, none of them equal to it. The long text may name a connecting part with
another value, so this is a suspected issue, never a confirmed one.

C04 compares each position code a text names ("nach interner LV-Position 99.9999", "siehe Pos.
01.0020") with the codes of the positions read, by code segments (01.0020 equals 1.20). A code
that heads positions (a title) or is the position's own resolves. An unresolved code is a
confirmed broken reference when the text places it in this bill (on the bill as read), and a
question otherwise (it may be in another lot); a reference near words of another document is
not judged.
"""

from __future__ import annotations

import re

from app.core.codes import code_segments
from app.risk.bill import Bill, Position
from app.risk.checks.base import MAX_HITS, CheckResult, Outcome, evidence_key, position_quote
from app.risk.explain import action, count_of, fill, reason
from app.risk.models import (
    STATE_STRENGTH,
    Candidate,
    Certainty,
    Method,
    ProjectContext,
    Quote,
    State,
)
from app.risk.tables import ConsistencyRule, ReferenceRule, RiskTables
from app.risk.text import find_all, fold, quote


def check(bill: Bill, tables: RiskTables, project: ProjectContext) -> CheckResult:
    del project
    result = CheckResult()
    for rule in tables.consistency.rules:
        found: list[Candidate] = []
        compared = 0
        looked: list[str] = []
        for position in bill.positions:
            short = _values(rule, position.folded_short)
            if len(short) != 1 or not position.long_text:
                continue
            long_folded = fold(position.long_text)
            long = _values(rule, long_folded)
            if not long:
                continue
            compared += 1
            looked.append(position.label)
            if set(short) & set(long):
                continue
            found.append(_candidate(rule, position, short, long, tables))
        state = State.RISK if found else (State.COVERED if compared else State.NOT_APPLICABLE)
        result.candidates.extend(found)
        result.outcomes.append(
            Outcome(
                rule.risk_type,
                rule.id,
                state,
                f"{count_of(compared, 'position')} {'states' if compared == 1 else 'state'} it in "
                f"both texts; {len(found)} {'differs' if len(found) == 1 else 'differ'}",
                triggered=compared,
                explained=compared - len(found),
                positions=tuple(looked),
            )
        )
    for reference in tables.consistency.references:
        result.extend(_references(reference, bill, tables))
    return result


def _references(rule: ReferenceRule, bill: Bill, tables: RiskTables) -> CheckResult:
    known = [s for p in bill.positions if (s := code_segments(p.item_code)) is not None]
    result = CheckResult()
    looked: list[str] = []
    resolved = elsewhere = 0
    for position in bill.positions:
        text, own = fold(position.original), code_segments(position.item_code)
        for start, end, match in find_all(rule.pattern, text)[:MAX_HITS]:
            code = code_segments(match.group(1))
            if code is None or code == own:
                continue
            looked.append(position.label)
            near = text[max(0, start - rule.reach) : end + rule.reach]
            if any(re.search(rf"\b{re.escape(word)}", near) for word in rule.external):
                elsewhere += 1
            elif any(k[: len(code)] == code for k in known):
                resolved += 1
            else:
                inside = any(re.search(rf"\b{re.escape(word)}", near) for word in rule.internal)
                result.candidates.append(
                    _reference(rule, position, match.group(1), (start, end), inside, tables)
                )
    found = result.candidates
    state = (
        max((c.state for c in found), key=STATE_STRENGTH.__getitem__)
        if found
        else (State.COVERED if looked else State.NOT_APPLICABLE)
    )
    result.outcomes.append(
        Outcome(
            rule.risk_type,
            rule.id,
            state,
            f"{len(looked)} position references read; {resolved} found in the bill, {elsewhere} "
            f"name another document (not judged), {len(found)} not found",
            triggered=len(looked),
            explained=resolved,
            positions=tuple(dict.fromkeys(looked)),
        )
    )
    return result


def _reference(
    rule: ReferenceRule,
    position: Position,
    code: str,
    span: tuple[int, int],
    inside: bool,
    tables: RiskTables,
) -> Candidate:
    risk = tables.risk_type(rule.risk_type)
    field = "description" if span[0] < len(position.folded_short) else "long_description"
    cell = position.cells.get(field)
    # The cell key the reference detector uses for the same text: one finding, one signal.
    key = (
        f"cell:{cell.table_id}/{cell.row_id}/{cell.column_id}"
        if cell is not None
        else evidence_key(rule.id, position)
    )
    # Placed in this bill and absent from it: confirmed on the bill as read, as the reference
    # detector confirms an unresolved reference column. Unplaced: it may be in another lot.
    certainty = Certainty.CONFIRMED if inside else Certainty.UNCLEAR
    state = State.RISK if inside else State.CANNOT_TELL
    slots = {"value_a": code}
    return Candidate(
        rule_id=rule.id,
        risk_type=rule.risk_type,
        method=Method.INVARIANT,
        state=state,
        certainty=certainty,
        title=f"{risk.name}: reference to position {code}, which this bill does not have"[:300],
        positions=(position.ref(field),),
        quotes=(position_quote(position, *span),),
        slots=slots,
        question=fill(tables.explanations.questions["reference"], slots),
        checked=("the position codes the texts name, against the codes of the positions read",),
        harm=risk.harm,
        keywords_only=False,
        position_texts=(position.folded,),
        explanation=reason(
            tables,
            category=risk.category,
            method=Method.INVARIANT,
            state=state,
            certainty=certainty,
            slots=slots,
            fallback="Found by {method_phrase}: {positions} names position {value_a}; no "
            "position of the bill as read has that code.",
        ),
        action=action(tables, risk.category, slots),
        evidence_keys=frozenset({key}),
        stable_key=f"{rule.id}|{position.table_id}|{position.item_code or position.row_id}|{code}",
    )


def _values(rule: ConsistencyRule, folded: str) -> dict[str, tuple[int, int]]:
    """Each value (whitespace removed) and where it first occurs."""
    values: dict[str, tuple[int, int]] = {}
    for start, end, match in find_all(rule.pattern, folded):
        value = re.sub(r"\s+", "", match.group(1) if match.groups() else match.group(0))
        for one in value.split(rule.separator) if rule.separator else [value]:
            values.setdefault(one, (start, end))
    return values


def _candidate(
    rule: ConsistencyRule,
    position: Position,
    short: dict[str, tuple[int, int]],
    long: dict[str, tuple[int, int]],
    tables: RiskTables,
) -> Candidate:
    risk = tables.risk_type(rule.risk_type)
    (value_a, span_a), (value_b, span_b) = next(iter(short.items())), next(iter(long.items()))
    slots = {
        "attribute": rule.attribute.replace("_", " "),
        "value_a": value_a,
        "value_b": ", ".join(long),
        "position_a": "the short text of {positions}",
        "position_b": "its long text",
        # position_a names the position already; naming it again here said it twice.
        "component": f"the {rule.attribute.replace('_', ' ')}",
    }
    return Candidate(
        rule_id=rule.id,
        risk_type=rule.risk_type,
        method=Method.ATTRIBUTE_CONSISTENCY,
        state=State.RISK,
        certainty=Certainty.SUSPECTED,
        title=f"{risk.name}: short text {value_a}, long text {value_b}"[:300],
        positions=(position.ref("description", "long_description"),),
        quotes=(
            position_quote(position, *span_a),
            Quote(
                position=position.label, source="long text", text=quote(position.long_text, *span_b)
            ),
        ),
        slots=slots,
        question=fill(tables.explanations.questions["consistency"], slots),
        checked=("the short text and the long text of the position",),
        harm=risk.harm,
        keywords_only=False,
        position_texts=(position.folded,),
        explanation=reason(
            tables,
            category=risk.category,
            method=Method.ATTRIBUTE_CONSISTENCY,
            state=State.RISK,
            certainty=Certainty.SUSPECTED,
            slots=slots,
            fallback="Found by {method_phrase}: the short text of {positions} states {value_a}, "
            "the long text {value_b}. The long text may describe a connecting part.",
        ),
        action=action(tables, risk.category, slots),
        evidence_keys=frozenset({evidence_key(rule.id, position)}),
        stable_key=f"{rule.id}|{position.table_id}|{position.item_code or position.row_id}",
    )
