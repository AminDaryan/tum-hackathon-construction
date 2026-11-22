"""Sending a bill to Claude for review (:mod:`app.agents.bill_review`), and the stored answer.

Off unless the server has an Anthropic key (``Settings.bill_review``) and the optional
``anthropic`` package. Only a validation run that asks for it (``bill_review``) calls the model,
before its checks run: a reviewer starts it for one bill. Every other run, and every read of a
run or its findings, uses the stored answer without calling a model; the check
``llm.bill_review`` lists its claims.

What is sent is the design measured with the evaluation tool
(:mod:`app.evaluation.llm_review`): the whole bill as one part, once per pass of
:data:`REVIEW_PASSES` (the three requests at the same time), with the findings of the app's own
checks under the positions they name. The text of the bill leaves the machine; the file name,
the project and the people working on it do not. A pass that fails (no connection, a refused
key, a declined or cut-off answer) is named in the stored review and the others are kept; with
none answered the review is ``failed``. A new request replaces the stored review.

Stored as one JSON file per dataset under ``<data_dir>/bill_reviews``
(:mod:`app.services.dataset_files`).
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from app.agents import claude
from app.agents.bill_review import (
    PASSES,
    PROMPT_VERSION,
    Generator,
    PartResult,
    facts_by_row_id,
    load_issue_types,
    position_digest,
    read_bill,
    review_bill,
    whole_part,
)
from app.agents.claude import ClaudeGenerator
from app.models.bill_review import BillReview, BillReviewClaim, BillReviewStatus
from app.models.dataset import Dataset
from app.models.issue import ValidationIssue
from app.services import dataset_files, decivio_bot
from app.services.workbench import Workbench

logger = logging.getLogger(__name__)

# The measured settings: claims of this model at this effort were scored on the practice bills.
MODEL = "claude-haiku-5-5"
EFFORT = "medium"
MAX_OUTPUT_TOKENS = 128_000
REVIEW_PASSES = ("numbers", "basis", "text")
REQUEST_TIMEOUT_SECONDS = 600.0
MAX_RETRIES = 2  # a reviewer is waiting: fewer than the evaluation tool's six
BILL_NAME = "bill of quantities"  # the file name stays here
FOLDER = "bill_reviews"


def available(wb: Workbench) -> bool:
    """Whether a reviewer can start a review on this server: a key is set and the SDK is
    installed. Nothing is sent to find out."""
    return _key(wb) is not None and claude.installed()


def stored(wb: Workbench, dataset_id: str) -> BillReview | None:
    """The stored review of a dataset, ``None`` when there is none. Never calls a model."""
    text = dataset_files.read(wb, FOLDER, dataset_id)
    return BillReview.model_validate_json(text) if text is not None else None


def ask(
    wb: Workbench,
    dataset: Dataset,
    issues: Iterable[ValidationIssue],
    *,
    generator: Generator | None = None,
) -> BillReview:
    """Send the bill to the model, once per pass, then store and return what it answered.
    ``issues`` are the findings of the app's checks on this revision of the bill: they stand in
    the prompt as given, so the model does not repeat them."""
    bill = read_bill(dataset, BILL_NAME)
    part = whole_part(bill)

    def stored_as(
        status: BillReviewStatus,
        detail: str,
        claims: Iterable[BillReviewClaim] = (),
        failed_passes: Iterable[str] = (),
    ) -> BillReview:
        review = BillReview(
            dataset_id=dataset.dataset_id,
            dataset_revision=dataset.revision,
            model=MODEL,
            prompt_version=PROMPT_VERSION,
            status=status,
            detail=detail,
            positions=len(part.positions),
            failed_passes=list(failed_passes),
            claims=list(claims),
        )
        dataset_files.write(wb, FOLDER, review.dataset_id, review.model_dump_json())
        return review

    if not part.positions:
        return stored_as(
            "failed",
            "Nothing was sent: the bill has no positions under a section heading (Titel), and "
            "the review reads a bill section by section.",
        )
    generate = generator or ClaudeGenerator(
        model=MODEL,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        timeout=REQUEST_TIMEOUT_SECONDS,
        effort=EFFORT,
        max_retries=MAX_RETRIES,
        api_key=_key(wb),
    )
    facts = facts_by_row_id(bill, ((_rows(issue), issue.title) for issue in issues))

    def one(name: str) -> PartResult:
        review = review_bill(
            bill,
            generate,
            issue_types=load_issue_types(PASSES[name]),
            facts=facts,
            focus=name,
            one_part=True,
        )
        return review.parts[0]

    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(REVIEW_PASSES)) as pool:
        answers = list(pool.map(one, REVIEW_PASSES))

    # The model names a position by its number (OZ): a number two positions share names neither.
    by_oz = {p.oz: p for p in part.positions}
    shared = {oz for oz, count in Counter(p.oz for p in part.positions).items() if count > 1}
    claims: list[BillReviewClaim] = []
    unplaced = sum(len(answer.rejected) for answer in answers)
    for answer in answers:
        for issue in answer.issues:
            if issue.oz in shared:
                unplaced += 1
                continue
            position = by_oz[issue.oz]
            claims.append(
                BillReviewClaim(
                    table_id=position.table_id,
                    row_id=position.row_id,
                    oz=issue.oz,
                    position_digest=position_digest(position),
                    focus=answer.focus,
                    issue_type=issue.issue_type,
                    issue_name=issue.issue_name,
                    certainty=issue.certainty,
                    quote=issue.quote,
                    grounded=issue.grounded,
                    why=issue.why,
                    related_oz=list(issue.related_oz),
                )
            )
    errors = {
        answer.focus: answer.error.removeprefix("RuntimeError: ")
        for answer in answers
        if answer.error is not None
    }
    # One cause (a refused key, no connection) is named once, not once per pass.
    why = (
        next(iter(errors.values()))
        if len(set(errors.values())) == 1 and len(errors) == len(answers)
        else "; ".join(f"{name}: {error}" for name, error in errors.items())
    )
    answered = len(answers) - len(errors)
    unread = len(bill.positions) - len(part.positions)
    logger.info(
        "Bill review of dataset %s revision %s: %d of %d passes answered, %d claims, %.0f s",
        dataset.dataset_id,
        dataset.revision,
        answered,
        len(answers),
        len(claims),
        time.monotonic() - began,
        extra={"dataset_id": dataset.dataset_id},
    )
    if not answered:
        return stored_as("failed", f"No pass answered: {why}.", failed_passes=errors)
    detail = (
        f"{answered} of {len(answers)} passes answered on {len(part.positions)} positions: "
        f"{len(claims)} claims."
        + (f" {unplaced} answers named no single position and were dropped." if unplaced else "")
        + (f" {unread} positions under no section heading were not read." if unread else "")
        + (f" Failed: {why}." if errors else "")
    )
    return stored_as("partial" if errors else "completed", detail, claims, errors)


def _rows(issue: ValidationIssue) -> list[tuple[str, str]]:
    """The rows a finding names: those of its highlighted cells, and its own."""
    rows = [(cell.table_id, cell.row_id) for cell in issue.affected_cells]
    if issue.table_id is not None and issue.row_id is not None:
        rows.append((issue.table_id, issue.row_id))
    return rows


def _key(wb: Workbench) -> str | None:
    """The bill review's own key, else the review assistant's (DECIVIO_BOT_ANTHROPIC_API_KEY)."""
    secret = wb.settings.bill_review.anthropic_api_key
    own = (secret.get_secret_value().strip() or None) if secret is not None else None
    return own or decivio_bot.api_key()
