"""Asking the local language model to match bill positions to the products of the price
reference (``statistical.open_price_reference``), and the stored answers.

Only a validation run that asks for it (``match_materials``) calls the model, before its checks
run; every other run, and every read of a run, its findings or its risks, uses the stored
answers without calling a model. Only priced rows the keywords could not match are sent
(:func:`~app.validation.statistical.open_price_reference.needs_model`), one row per request,
to the configured local server (``llm``; only this machine unless ``allow_remote``), within a
budget: at most :data:`MAX_ROWS` requests and :data:`MAX_SECONDS` in all, each request with the
configured timeout. An earlier answer for the same model and prompt is reused when
``llm.reuse_cached``. When the server cannot be reached, or :data:`MAX_FAILURES` requests in a
row fail, nothing more is sent. Every row sent or not ends as ``answered``, ``request_failed``
or ``not_sent``, never as matched: what an answer is worth is decided by the check.

Stored as one JSON file per dataset under ``<data_dir>/material_matches``
(:mod:`app.services.dataset_files`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.agents.models import ALLOWED_MODELS
from app.agents.ollama import CALL_FAILURES
from app.models.dataset import Dataset
from app.models.material_answers import JobStatus, MaterialAnswer, MaterialAnswers
from app.risk.model_review import Generator, OllamaGenerator
from app.services import dataset_files
from app.services.workbench import Workbench
from app.validation.contracts.context import build_validation_context
from app.validation.statistical.material_match import PROMPT_VERSION, answer_key
from app.validation.statistical.open_price_reference import model_prompt, needs_model
from app.validation.support.items import item_frame

logger = logging.getLogger(__name__)

MAX_ROWS = 300
MAX_SECONDS = 1800.0
MAX_FAILURES = 3
MAX_RAW = 8000
SAVE_EVERY = 10
FOLDER = "material_matches"


def stored(wb: Workbench, dataset_id: str) -> MaterialAnswers | None:
    """The stored answers of a dataset, ``None`` when there are none. Never calls a model."""
    text = dataset_files.read(wb, FOLDER, dataset_id)
    return MaterialAnswers.model_validate_json(text) if text is not None else None


def ask(
    wb: Workbench,
    dataset: Dataset,
    *,
    generator: Generator | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> MaterialAnswers:
    """Ask the model about the dataset's rows that need it, store and return every answer."""
    settings = wb.settings.llm
    previous = stored(wb, dataset.dataset_id)
    if generator is None and (settings.provider == "none" or settings.model is None):
        kept = previous.answers if previous else {}
        return MaterialAnswers(
            dataset_id=dataset.dataset_id,
            model=previous.model if previous else None,
            model_licence=previous.model_licence if previous else None,
            prompt_version=PROMPT_VERSION,
            status="not_configured",
            detail="No local model is configured, so nothing was sent now"
            + (
                f"; {len(kept)} answers stored by an earlier request are used."
                if kept
                else ": rows the keywords could not match were not processed by a model."
            ),
            answers=kept,
        )
    model = settings.model or "unnamed-test-model"
    generate = generator or OllamaGenerator(settings)
    context = build_validation_context(
        dataset=dataset,
        profile=wb.profiles.get(dataset.profile_id),
        run_id="material-match",
        limits=wb.settings.validation,
        ids=wb.ids,
        clock=wb.clock,
    )
    rows = [r for r in item_frame(context).records if needs_model(r)]
    same = previous is not None and previous.model == model
    known = previous.answers if previous is not None and same else {}
    answers: dict[str, MaterialAnswer] = {}
    entry = ALLOWED_MODELS.get(model)

    def stored_as(status: JobStatus, detail: str) -> MaterialAnswers:
        return MaterialAnswers(
            dataset_id=dataset.dataset_id,
            model=model,
            model_licence=entry.licence if entry else None,
            prompt_version=PROMPT_VERSION,
            status=status,
            detail=detail,
            answers={**known, **answers},
        )

    sent = reused = failed = in_a_row = 0
    stop: str | None = None
    began = monotonic()
    for record in rows:
        text = model_prompt(record)
        key = answer_key(model, text)
        old = known.get(key)
        if settings.reuse_cached and old is not None and old.status == "answered":
            answers[key] = old
            reused += 1
            continue
        where = _where(record.table_id, record.row_id, record.item_code)
        if stop is None and sent >= MAX_ROWS:
            stop = f"budget of {MAX_ROWS} requests used"
        if stop is None and monotonic() - began > MAX_SECONDS:
            stop = f"time budget of {MAX_SECONDS:.0f} s used"
        if stop is not None:
            answers[key] = where.evolve(status="not_sent", error=stop)
            continue
        start = monotonic()
        sent += 1
        try:
            raw = generate(text)
        except CALL_FAILURES as exc:
            failed += 1
            in_a_row += 1
            answers[key] = where.evolve(
                status="request_failed",
                error=type(exc).__name__,
                duration_ms=(monotonic() - start) * 1000,
            )
            if isinstance(exc, ConnectionError):
                stop = "the model server could not be reached"
            elif in_a_row >= MAX_FAILURES:
                stop = f"{MAX_FAILURES} requests in a row failed"
            continue
        in_a_row = 0
        answers[key] = where.evolve(
            status="answered", raw=raw[:MAX_RAW], duration_ms=(monotonic() - start) * 1000
        )
        if sent % SAVE_EVERY == 0:  # a long run that is stopped keeps what it was told
            _save(wb, stored_as("partial", f"In progress: {sent} of {len(rows)} rows sent."))
    answered = sum(a.status == "answered" for a in answers.values())
    not_sent = sum(a.status == "not_sent" for a in answers.values())
    status: JobStatus = (
        "completed" if answered == len(answers) else "partial" if answered else "unavailable"
    )
    result = stored_as(
        status,
        f"{len(rows)} priced rows the keywords could not match: {sent} sent to the model, "
        f"{reused} earlier answers reused, {answered} answered, {failed} requests failed, "
        f"{not_sent} not sent" + (f" ({stop})" if stop else "") + ". An answer is a "
        "suggestion; the check verifies each one.",
    )
    _save(wb, result)
    logger.info(
        "Material matching on dataset %s: %d rows, %d sent, %d reused, %d answered, %d failed, "
        "%d not sent, %.0f s",
        dataset.dataset_id,
        len(rows),
        sent,
        reused,
        answered,
        failed,
        not_sent,
        monotonic() - began,
        extra={"dataset_id": dataset.dataset_id},
    )
    return result


def _where(table_id: str, row_id: str, item_code: str | None) -> MaterialAnswer:
    return MaterialAnswer(table_id=table_id, row_id=row_id, item_code=item_code, status="not_sent")


def _save(wb: Workbench, answers: MaterialAnswers) -> None:
    dataset_files.write(wb, FOLDER, answers.dataset_id, answers.model_dump_json())
