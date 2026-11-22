"""The coverage table: for every risk type of the catalogue, what this run could say about it.

The catalogue (135 types) is a taxonomy. A type without a check is listed as ``not_checkable``
with that reason, so the report never implies that every type was examined.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.risk.checks.base import Outcome
from app.risk.models import STATE_STRENGTH, CoverageRow, RuleCheck, State
from app.risk.tables import RiskTables

MAX_REASONS = 6
MAX_CHECKED_POSITIONS = 50


def coverage(outcomes: Sequence[Outcome], tables: RiskTables) -> list[CoverageRow]:
    by_type: dict[str, list[Outcome]] = {}
    for outcome in outcomes:
        by_type.setdefault(outcome.risk_type, []).append(outcome)
    catalogue = tables.catalogue
    types = [*catalogue.risk_types, *([catalogue.other] if catalogue.other.id in by_type else [])]
    rows: list[CoverageRow] = []
    for risk_type in types:
        found = by_type.get(risk_type.id, [])
        if not found:
            rows.append(
                CoverageRow(
                    risk_type=risk_type.id,
                    name=risk_type.name,
                    category=risk_type.category,
                    state=State.NOT_CHECKABLE,
                    reason="No check for this risk type in this version (taxonomy entry only).",
                )
            )
            continue
        reasons = "; ".join(f"{o.rule_id}: {o.reason}" for o in found[:MAX_REASONS])
        if len(found) > MAX_REASONS:
            reasons += f"; and {len(found) - MAX_REASONS} more rules"
        rows.append(
            CoverageRow(
                risk_type=risk_type.id,
                name=risk_type.name,
                category=risk_type.category,
                state=max((o.state for o in found), key=STATE_STRENGTH.__getitem__),
                reason=reasons,
                rules=list(dict.fromkeys(o.rule_id for o in found)),
                checks=[
                    RuleCheck(
                        rule_id=o.rule_id,
                        state=o.state,
                        reason=o.reason,
                        positions=list(o.positions[:MAX_CHECKED_POSITIONS]),
                        positions_total=len(o.positions),
                        scope=dict(o.scope),
                    )
                    for o in found
                ],
            )
        )
    return rows
