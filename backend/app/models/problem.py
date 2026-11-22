"""Problems: the findings of one run that concern the same mistake, shown as one thing to check.

A wrong unit price can break its line total, the subtotal of its Titel and the grand total, and
stand out against similar positions: four findings, one problem. A problem lists its findings
(``issue_ids``), the one shown first (``primary_issue_id``), why they belong together
(``links``), which of the seven anomaly types it is, and the money at stake when that can be
computed exactly in an explicit currency.

Problems are computed from a run's stored findings whenever they are shown, never stored, so
they always agree with the findings and the review decisions on them; an explanation refers to
one by its ``problem_id``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from app.models.base import FrozenModel
from app.models.values import ExactDecimal

PROBLEM_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


class AnomalyType(StrEnum):
    """The seven kinds of mistake in a bill of quantities the workbench looks for."""

    PRICE = "price"  # a position much more expensive than comparable ones
    QUANTITY = "quantity"  # an implausibly high quantity for the work
    UNIT = "unit"  # a wrong unit for the position
    SEMANTIC = "semantic"  # the text does not fit its Titel or category
    STRUCTURAL = "structural"  # missing mandatory fields or an inconsistent hierarchy
    LOGICAL = "logical"  # totals that do not match quantity × unit price
    DUPLICATE = "duplicate"  # duplicate or nearly identical positions


class ProblemLinkKind(StrEnum):
    SAME_CELL = "same_cell"  # both findings highlight the same cell
    SAME_ROW = "same_row"  # both findings concern the same row
    CARRIED_DIFFERENCE = "carried_difference"  # a difference carried into a total above it
    SAME_GROUP = "same_group"  # findings on one group of compared positions


class ProblemLink(FrozenModel):
    """Why two findings of a problem belong together; ``detail`` says it in words."""

    kind: ProblemLinkKind
    from_issue_id: str = Field(min_length=1)
    to_issue_id: str = Field(min_length=1)
    detail: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _two_findings(self) -> ProblemLink:
        if self.from_issue_id == self.to_issue_id:
            raise ValueError("a link joins two different findings")
        return self


class Problem(FrozenModel):
    problem_id: str = Field(pattern=PROBLEM_ID_PATTERN)
    issue_ids: list[str] = Field(min_length=1)
    primary_issue_id: str
    links: list[ProblemLink] = Field(default_factory=list)
    anomaly_type: AnomalyType
    # Exact, in ``currency``; both None when the amount cannot be computed in an explicit
    # currency (amounts in unknown currencies are never added up).
    money_at_stake: ExactDecimal | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    title: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _consistent(self) -> Problem:
        if len(set(self.issue_ids)) != len(self.issue_ids):
            raise ValueError("a problem lists each finding once")
        if self.primary_issue_id not in self.issue_ids:
            raise ValueError("the primary finding must be one of the problem's findings")
        members = set(self.issue_ids)
        for link in self.links:
            if link.from_issue_id not in members or link.to_issue_id not in members:
                raise ValueError("a link may only join findings of the problem")
        if (self.money_at_stake is None) != (self.currency is None):
            raise ValueError("money at stake needs its currency, and a currency needs an amount")
        return self
