"""What every check returns, and the matching helpers the checks share."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.risk.bill import Bill, Position
from app.risk.models import Candidate, ProjectContext, Quote, State
from app.risk.tables import RiskTables
from app.risk.text import find_all, occurrences, quote

MAX_HITS = 5  # matches looked at per text and rule


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one rule found in the whole bill, for the coverage table."""

    risk_type: str
    rule_id: str
    state: State
    reason: str
    triggered: int = 0  # doubts the rule raised (positions, or position and value)
    explained: int = 0  # settled by the bill itself: the position, notes, references, links
    filtered: int = 0  # below the table's size threshold: not raised
    positions: tuple[str, ...] = ()  # labels of the positions the rule looked at
    scope: Mapping[str, int] = field(default_factory=dict)  # a detector's counts; names no row


@dataclass(slots=True)
class CheckResult:
    candidates: list[Candidate] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)

    def extend(self, other: CheckResult) -> None:
        self.candidates.extend(other.candidates)
        self.outcomes.extend(other.outcomes)


class Check(Protocol):
    """A check reads the bill and returns candidates and one outcome per rule. Add a new check
    to :data:`app.risk.checks.CHECKS`; nothing else needs to change."""

    def __call__(self, bill: Bill, tables: RiskTables, project: ProjectContext) -> CheckResult: ...


def hits(folded: str, stems: Sequence[str], pattern: str | None = None) -> list[tuple[int, int]]:
    """Where word stems or a configured pattern occur in folded text, in text order."""
    found: list[tuple[int, int]] = []
    for stem in stems:
        for start in occurrences(folded, stem):
            found.append((start, start + len(stem)))
            if len(found) >= MAX_HITS * 4:
                break
    if pattern is not None:
        found.extend((start, end) for start, end, _ in find_all(pattern, folded))
    return sorted(set(found))[: MAX_HITS * 4]


def says(clause_text: str, phrases: Sequence[str]) -> str | None:
    """The first phrase that ``clause_text`` contains."""
    return next((p for p in phrases if p in clause_text), None)


def position_quote(position: Position, start: int, end: int) -> Quote:
    return Quote(
        position=position.label, source="position text", text=quote(position.original, start, end)
    )


def evidence_key(rule_id: str, position: Position) -> str:
    return f"{rule_id}@{position.key}"
