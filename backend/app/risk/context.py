"""What kind of project the bill is, read from its own words (never assumed).

A project type counts when at least ``min_share`` of the positions name one of its words in
their text or section titles. Trades come from section titles only. Dependency rules that
apply to some project types only (``context: [building]``) are skipped for other bills.
"""

from __future__ import annotations

from decimal import Decimal

from app.risk.bill import Bill, Position
from app.risk.models import ProjectContext
from app.risk.tables import RiskTables
from app.risk.text import fold


def derive_context(bill: Bill, tables: RiskTables) -> ProjectContext:
    titles = {s.section_id: fold(s.title) for s in bill.sections.values()}

    def text(position: Position) -> str:
        return " ".join([position.folded, *(titles.get(s, "") for s in position.sections)])

    texts = [text(p) for p in bill.positions]
    project_types: list[str] = []
    evidence: dict[str, list[str]] = {}
    for kind, words in tables.context.project_types.items():
        hits = [t for t in texts if any(word in t for word in words)]
        if texts and Decimal(len(hits)) / len(texts) >= tables.context.min_share:
            project_types.append(kind)
            evidence[kind] = sorted({w for t in hits for w in words if w in t})[:6]
    all_titles = " ".join(titles.values())
    trades = [
        t for t, words in tables.context.trades.items() if any(w in all_titles for w in words)
    ]
    return ProjectContext(
        project_types=project_types,
        evidence=evidence,
        trades=trades,
        positions=len(bill.positions),
        priced=bill.priced,
        currency=bill.currency,
        counted_total=bill.counted_total,
        documents_searched=bill.documents,
    )
