"""The central :class:`ValidationIssue` model and its review workflow.

Evidence classes separate *how* a finding is known from *how bad* it is (``severity``):

* ``confirmed_rule_violation``: a deterministic rule failed on verified input data.
* ``suspected_anomaly``: a statistical/ML signal; an unusual observation, not a proven error.
* ``semantic_warning``: a possible textual/semantic inconsistency.
* ``extraction_uncertainty``: the source could not be interpreted reliably.
* ``needs_external_context``: cannot be settled from this document alone.
* ``human_confirmed_error``: only ever derived from a reviewer's decision, never set by detectors.

Issues are immutable records. A review decision produces a new version of the issue (same id)
plus an audit event; the source dataset is never changed by a finding.

Each finding also has a *finding category* (``finding_category``: error, omission,
inconsistency, ambiguity, risk, change order opportunity, or none for findings about reading
the file and for those of a detector the category tables do not know). It is computed from
the detector and the rule (:mod:`app.models.finding_category`), never read back from storage
(loading drops a stored value); neither the evidence class nor a review decision changes it.
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, computed_field, field_validator, model_validator

from app.core.errors import ReviewTransitionError
from app.models.base import FrozenModel
from app.models.dataset import CellRef
from app.models.finding_category import FindingCategory, finding_category_of
from app.models.values import ExactDecimal


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class EvidenceClass(StrEnum):
    CONFIRMED_RULE_VIOLATION = "confirmed_rule_violation"
    SUSPECTED_ANOMALY = "suspected_anomaly"
    SEMANTIC_WARNING = "semantic_warning"
    EXTRACTION_UNCERTAINTY = "extraction_uncertainty"
    NEEDS_EXTERNAL_CONTEXT = "needs_external_context"
    HUMAN_CONFIRMED_ERROR = "human_confirmed_error"


DETECTOR_EVIDENCE_CLASSES: frozenset[EvidenceClass] = frozenset(
    set(EvidenceClass) - {EvidenceClass.HUMAN_CONFIRMED_ERROR}
)


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED_ERROR = "confirmed_error"
    FALSE_POSITIVE = "false_positive"
    CORRECTED = "corrected"
    NEEDS_MORE_INFORMATION = "needs_more_information"
    DISMISSED = "dismissed"


ALLOWED_REVIEW_TRANSITIONS: dict[ReviewStatus, frozenset[ReviewStatus]] = {
    ReviewStatus.PENDING_REVIEW: frozenset(
        {
            ReviewStatus.CONFIRMED_ERROR,
            ReviewStatus.FALSE_POSITIVE,
            ReviewStatus.NEEDS_MORE_INFORMATION,
            ReviewStatus.DISMISSED,
        }
    ),
    ReviewStatus.NEEDS_MORE_INFORMATION: frozenset(
        {
            ReviewStatus.PENDING_REVIEW,
            ReviewStatus.CONFIRMED_ERROR,
            ReviewStatus.FALSE_POSITIVE,
            ReviewStatus.DISMISSED,
        }
    ),
    # CORRECTED is reachable only through the correction workflow, which creates a new
    # dataset revision; it is never set by a plain review decision.
    ReviewStatus.CONFIRMED_ERROR: frozenset({ReviewStatus.PENDING_REVIEW, ReviewStatus.CORRECTED}),
    ReviewStatus.FALSE_POSITIVE: frozenset({ReviewStatus.PENDING_REVIEW}),
    ReviewStatus.DISMISSED: frozenset({ReviewStatus.PENDING_REVIEW}),
    ReviewStatus.CORRECTED: frozenset(),
}

REVIEW_DECISION_TARGETS: frozenset[ReviewStatus] = frozenset(
    set(ReviewStatus) - {ReviewStatus.CORRECTED}
)


def check_review_transition(current: ReviewStatus, target: ReviewStatus) -> None:
    """Raise :class:`ReviewTransitionError` unless ``current -> target`` is allowed."""
    if target not in ALLOWED_REVIEW_TRANSITIONS[current]:
        raise ReviewTransitionError(
            f"Cannot change review status from {current.value!r} to {target.value!r}.",
            details={
                "current": current.value,
                "target": target.value,
                "allowed": sorted(s.value for s in ALLOWED_REVIEW_TRANSITIONS[current]),
            },
        )


class IssueCategory:
    """Well-known issue categories. Categories are plain strings so new detectors can add their
    own (lower_snake_case) without changing this module."""

    MISSING_VALUE = "missing_value"
    DATA_TYPE = "data_type"
    NUMERIC_VALUE = "numeric_value"
    ARITHMETIC = "arithmetic"
    SUBTOTAL = "subtotal"
    GRAND_TOTAL = "grand_total"
    CURRENCY = "currency"
    DUPLICATE = "duplicate"
    REFERENCE = "reference"
    FORMULA_ERROR = "formula_error"
    UNIT = "unit"
    CONSTRAINT = "constraint"
    EXTRACTION = "extraction"
    STATISTICAL_OUTLIER = "statistical_outlier"
    SEMANTIC = "semantic"


CATEGORY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


class EvidenceKind(StrEnum):
    CALCULATION = "calculation"  # a recomputation, e.g. "12.5 × 40.00 = 500.00"
    VALUE = "value"  # an observed cell value
    RULE = "rule"  # the rule or constraint that was applied
    COMPARISON = "comparison"  # values compared against each other
    REFERENCE = "reference"  # related rows/cells
    NOTE = "note"  # context, caveats, downgrade explanations


JsonScalar = str | int | float | bool | None


def _json_scalars(data: Any) -> Any:
    """Decimals become exact strings (never floats); floats must be finite."""
    if not isinstance(data, dict):
        return data
    converted: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError(f"evidence data {key!r} is not finite")
            value = format(value, "f")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"evidence data {key!r} is not finite")
        converted[key] = value
    return converted


class CalculationOperand(FrozenModel):
    label: str
    value: ExactDecimal
    cell: CellRef | None = None


class Calculation(FrozenModel):
    """A recomputation written out so reviewers and exporters can show it verbatim.

    ``operands`` may be capped for long sums; ``terms`` always holds the full count.
    """

    operation: Literal["product", "sum", "percentage", "difference", "comparison"]
    operands: list[CalculationOperand] = Field(default_factory=list)
    operands_truncated: bool = False
    terms: int = Field(default=0, ge=0)
    exact_result: ExactDecimal
    rounding: str | None = None  # e.g. "2 decimal places, half up"; None = exact result used
    rounded_result: ExactDecimal | None = None
    reported: ExactDecimal | None = None
    difference: ExactDecimal | None = None  # reported - expected
    allowed_difference: ExactDecimal | None = None


class EvidenceItem(FrozenModel):
    kind: EvidenceKind
    label: str
    detail: str
    cells: list[CellRef] = Field(default_factory=list)
    data: dict[str, JsonScalar] = Field(default_factory=dict)  # decimals become strings
    calculation: Calculation | None = None

    @field_validator("data", mode="before")
    @classmethod
    def _no_float_decimals(cls, value: Any) -> Any:
        return _json_scalars(value)


class FinancialImpact(FrozenModel):
    """Signed monetary difference, only when it is actually calculable in an explicit
    currency (a marker on the cells, a header currency or a currency column). Without an
    explicit currency there is no impact: amounts in unknown currencies cannot be summed.

    ``amount = reported - recomputed``: positive means the document states more than the
    recomputed value. ``kind = "discrepancy"`` says only that the figures disagree, not which
    figure is wrong (a wrong unit price next to a correct total looks the same).
    ``kind = "reference_deviation"`` is what is at stake if a row were priced like the rows it
    is compared with: ``reported`` is its unit price, ``recomputed`` the reference unit price,
    and ``amount`` = quantity × (reported − recomputed), so it scales with the quantity.
    """

    amount: ExactDecimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    basis: str
    kind: Literal["discrepancy", "potential_double_count", "reference_deviation"] = "discrepancy"
    reported: ExactDecimal | None = None
    recomputed: ExactDecimal | None = None


class AnomalyScore(FrozenModel):
    """Raw detector score. Never a probability of error unless ``calibrated`` is True, which
    requires a ``calibration_reference`` (an evaluation report the detector spec cites)."""

    value: float = Field(allow_inf_nan=False)
    method: str
    interpretation: str
    calibrated: bool = False
    calibration_reference: str | None = None
    threshold: float | None = None

    @model_validator(mode="after")
    def _calibration_documented(self) -> AnomalyScore:
        if self.calibrated and not self.calibration_reference:
            raise ValueError("a calibrated anomaly score needs a calibration_reference")
        return self


RULE_ID_PATTERN = r"^[a-z][a-z0-9_.]{0,63}$"


class ValidationIssue(FrozenModel):
    """A finding. Create issues only through ``IssueFactory`` (it applies the evidence policy);
    change them only through :meth:`FrozenModel.evolve` (it re-validates)."""

    issue_id: str
    # Stable across runs and re-normalizations: hash of detector, category, rule and *source
    # coordinates* (never of random ids). Used to carry review decisions forward.
    fingerprint: str
    # Hash of the observed/expected values and input cells: a review is carried forward only
    # when fingerprint *and* digest match (same place, same evidence).
    evidence_digest: str | None = None
    validation_run_id: str
    document_id: str
    dataset_id: str
    dataset_revision: int = Field(ge=1)
    table_id: str | None = None
    row_id: str | None = None
    affected_cells: list[CellRef] = Field(default_factory=list)  # highlighted cells
    input_cells: list[CellRef] = Field(default_factory=list)  # cells the finding was computed from
    detector_id: str
    detector_version: str
    rule_id: str = Field(default="default", pattern=RULE_ID_PATTERN)
    issue_category: str = Field(pattern=CATEGORY_PATTERN)
    severity: Severity
    evidence_class: EvidenceClass  # as assigned by the detector (never human_confirmed_error)
    title: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1)
    observed_value: str | None = None
    expected_value: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    suggested_action: str | None = None
    estimated_financial_impact: FinancialImpact | None = None
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    anomaly_score: AnomalyScore | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    reviewer_comment: str | None = Field(default=None, max_length=4000)
    reviewed_at: datetime | None = None
    # Optimistic concurrency: every review decision increments the version; an update that
    # names a stale version is rejected (a decision made on an outdated screen).
    version: int = Field(default=1, ge=1)
    created_at: datetime

    @field_validator("evidence_class")
    @classmethod
    def _detectors_cannot_confirm(cls, value: EvidenceClass) -> EvidenceClass:
        if value is EvidenceClass.HUMAN_CONFIRMED_ERROR:
            raise ValueError(
                "human_confirmed_error is derived from a review decision; "
                "set review_status=confirmed_error instead"
            )
        return value

    @model_validator(mode="after")
    def _scores_are_not_confirmations(self) -> ValidationIssue:
        if (
            self.anomaly_score is not None
            and self.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
        ):
            raise ValueError("an anomaly score cannot back a confirmed rule violation")
        return self

    def with_review(
        self, status: ReviewStatus, comment: str | None, *, at: datetime
    ) -> ValidationIssue:
        """The next version of this issue after a review decision (the transition is checked
        first; ``corrected`` is reserved for the correction workflow)."""
        if status is ReviewStatus.CORRECTED:
            raise ReviewTransitionError(
                "'corrected' is set by the correction workflow, not by a review decision.",
                details={"current": self.review_status.value, "target": status.value},
            )
        check_review_transition(self.review_status, status)
        return self.evolve(
            review_status=status,
            reviewer_comment=comment,
            reviewed_at=at,
            version=self.version + 1,
        )

    def with_correction(self, comment: str | None, *, at: datetime) -> ValidationIssue:
        """The next version of this issue after a correction was applied."""
        check_review_transition(self.review_status, ReviewStatus.CORRECTED)
        return self.evolve(
            review_status=ReviewStatus.CORRECTED,
            reviewer_comment=self.reviewer_comment if comment is None else comment,
            reviewed_at=at,
            version=self.version + 1,
        )

    @computed_field  # type: ignore[prop-decorator]  # mypy cannot type a decorated property
    @property
    def effective_evidence_class(self) -> EvidenceClass:
        """Evidence class shown to reviewers: human confirmation overrides detector evidence."""
        if self.review_status in (ReviewStatus.CONFIRMED_ERROR, ReviewStatus.CORRECTED):
            return EvidenceClass.HUMAN_CONFIRMED_ERROR
        return self.evidence_class

    @computed_field  # type: ignore[prop-decorator]  # mypy cannot type a decorated property
    @property
    def finding_category(self) -> FindingCategory | None:
        """What the finding means for the person checking the bill (one of six categories), or
        None for a finding about reading the file or of a detector the category tables do not
        know. Computed from the detector and the rule: a finding the evidence policy downgraded
        to ``extraction_uncertainty`` keeps its category, and a review decision does not change
        it."""
        return finding_category_of(detector_id=self.detector_id, rule_id=self.rule_id)
