"""What Claude named when a reviewer sent it the bill to review (``llm.bill_review``).

The check calls no model. A reviewer starts the review for one bill
(:mod:`app.services.bill_reviews`, off without an Anthropic key on the server); the answer is
stored, and every run reads it through ``context.bill_review``. Without a stored review, or
when the request failed, the check is skipped and says why.

Listed is what was measured (:mod:`app.evaluation.reading_list`): the claims the model rates as
certain. A claim it rates lower is counted, not listed. A claim holds for the position as the
model read it: after the bill was corrected, a claim on a changed position is left out, and the
others stay until the review is started again.

Every finding is a ``semantic_warning``: the model read the bill and suspects something; it
proves nothing, so a reviewer decides. The explanation is the model's own reason, the quote
what it cites from the position. No amount is stated: the model's numbers are not checked.
"""

from __future__ import annotations

from typing import ClassVar

from app.agents.bill_review import position_digest, read_bill
from app.models.bill_review import BillReviewClaim
from app.models.dataset import Row, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    IssueCategory,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)

CERTAIN = "high"
RULE_OTHER = "other"  # a claim without an issue type of the catalogue
POSITIONS_CHECKED = "positions_checked"
POSITIONS_READ_ON_EARLIER_REVISION = "positions_read_on_earlier_revision"
PASSES_FAILED = "passes_failed"
CLAIMS_LESS_CERTAIN = "claims_less_certain"
CLAIMS_REPEATED = "claims_repeated"
CLAIMS_ON_CHANGED_POSITIONS = "claims_on_changed_positions"
# The cell a claim points at: the number an issue type is about, else the description.
_ANCHOR_FIELDS = {
    "016": ("quantity",),
    "018": ("quantity", "unit_price"),
    "023": ("quantity",),
    "080": ("unit_price",),
    "081": ("unit_price",),
    "082": ("unit_price",),
    "083": ("unit_price",),
    "084": ("unit_price",),
    "085": ("unit_price",),
}
_TEXT_FIELDS = ("description", "long_description")


def rule_id_of(issue_type: str | None) -> str:
    """The rule of a claim: the issue type it names ("r081" for R081), else "other"."""
    return f"r{issue_type}" if issue_type else RULE_OTHER


class BillReviewDetector(Detector[DetectorConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="llm.bill_review",
        name="Claude bill review",
        version="1.0.0",
        category=DetectorCategory.SEMANTIC,
        description=(
            "Lists what Claude named when a reviewer sent it this bill to review: the claims "
            "it rates as certain, each on the position it names, with its reason and its "
            "quote. The check itself calls no model; it reads the stored answer."
        ),
        optional_fields=(
            "item_code",
            "description",
            "long_description",
            "quantity",
            "unit",
            "unit_price",
            "line_total",
        ),
        supported_data_types=(DataType.TEXT, DataType.NUMBER),
        applicability=(
            "Bills a reviewer sent to Claude for review. The server needs an Anthropic key "
            "for that; without one nothing is sent and the check is skipped."
        ),
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING,),
        issue_categories=(IssueCategory.SEMANTIC,),
        limitations=(
            "A language model's suspicion, never a proof: it can name a fault that is none "
            "and miss one that is there.",
            "The same bill can get other claims when it is sent again.",
            "Only positions under a section heading (Titel) are read.",
            "After a correction, claims on unchanged positions stay although the model has "
            "not read the changed bill.",
        ),
        references=(
            "docs/evaluation/boq-practice-p1-model-review.md: the review and its claims, as "
            "measured on the practice bills",
        ),
    )

    def applicability(self, context: ValidationContext, config: DetectorConfig) -> Applicability:
        review = context.bill_review
        if review is None:
            return Applicability.no("No Claude review was started for this bill.")
        if review.status == "failed":
            return Applicability.no(review.detail)
        return Applicability.yes(
            f"A Claude review of revision {review.dataset_revision} of the bill is stored."
        )

    def validate(self, context: ValidationContext, config: DetectorConfig) -> DetectorResult:
        result = DetectorResult()
        review = context.bill_review
        if review is None:
            return result
        result.notes.append(review.detail)
        if review.failed_passes:
            result.count(PASSES_FAILED, len(review.failed_passes))
        if review.dataset_revision == context.dataset.revision:
            result.count(POSITIONS_CHECKED, review.positions)
        else:  # not "checked": the model has not read this revision
            result.count(POSITIONS_READ_ON_EARLIER_REVISION, review.positions)
            result.notes.append(
                f"The model read revision {review.dataset_revision} of the bill; this is "
                f"revision {context.dataset.revision}. Claims on positions changed since are "
                "left out. Start the review again to have the changed bill read."
            )
        positions = {(p.table_id, p.row_id): p for p in read_bill(context.dataset, "").positions}
        tables = {t.table_id: t for t in context.tables()}
        listed: set[tuple[str, str, str]] = set()
        for claim in review.claims:
            context.checkpoint()
            position = positions.get((claim.table_id, claim.row_id))
            if position is None or position_digest(position) != claim.position_digest:
                result.count(CLAIMS_ON_CHANGED_POSITIONS)
                continue
            if claim.certainty != CERTAIN:
                result.count(CLAIMS_LESS_CERTAIN)
                continue
            rule_id = rule_id_of(claim.issue_type)
            if (claim.table_id, claim.row_id, rule_id) in listed:
                result.count(CLAIMS_REPEATED)  # two passes name the same issue on a position
                continue
            listed.add((claim.table_id, claim.row_id, rule_id))
            table = tables[claim.table_id]
            row = table.row(claim.row_id)
            result.add(self._issue(context, table, row, claim, rule_id, review.model))
        return result

    def _issue(
        self,
        context: ValidationContext,
        table: Table,
        row: Row,
        claim: BillReviewClaim,
        rule_id: str,
        model: str,
    ) -> ValidationIssue:
        fields = (*_ANCHOR_FIELDS.get(claim.issue_type or "", ()), *_TEXT_FIELDS)
        anchor = next((f for f in fields if context.cell(table, row, f) is not None), None)
        cells = [context.cell_ref(table, row, anchor)] if anchor is not None else []
        name = claim.issue_name or "an issue outside the catalogue"
        related = ", ".join(claim.related_oz)
        return context.issues.create(
            self.spec,
            rule_id=rule_id,
            category=IssueCategory.SEMANTIC,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=f"Suspected by Claude: {name}"[:200],
            explanation=(
                f"Claude read the bill and says of {claim.oz}: {claim.why} "
                + (f"It points to {related} as well. " if related else "")
                + "This is the suspicion of a language model, not a confirmed error: it can "
                "be wrong."
            ),
            table=table,
            row=row,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.NOTE,
                    label=(
                        "Quoted by the model from the position"
                        if claim.grounded
                        else "Quoted by the model (not found in the position's text or numbers)"
                    ),
                    detail=claim.quote or "(no quote given)",
                    cells=cells,
                    data={
                        "model": model,
                        "pass": claim.focus,
                        "issue_type": claim.issue_type,
                        "certainty": claim.certainty,
                        "quote_found": claim.grounded,
                    },
                )
            ],
            suggested_action=(
                "Read the position and decide: confirm the finding if the model is right, "
                "mark it as a false positive if it is not."
            ),
        )
