"""An optional, bounded second look by the local language model at a few open questions.

Only reminders the rules could not decide (``cannot_tell``) are sent, at most
:data:`MAX_GROUPS`, each with the texts the checks found. The model must answer in JSON and
cite positions of the bill. An answer is kept only when every cited position exists and its
quote occurs word for word in a cited position or in a note; it is then shown as a hint
(counter-evidence with link ``model_hint``) and never changes the state, tier or money of a
reminder. The model writes no free text into the report, so it cannot add numbers, standards
or past cases. A timeout, an unreachable server or an invalid answer leaves every other result
as it was and is counted in :class:`~app.risk.models.ModelReview`.

It runs only when a caller asks for it explicitly (``requested``); reading a report over HTTP
never does (the old ``?model_review=true`` is refused). It is not discovery: it looks again at
reminders the rules already raised, while discovery proposes hypotheses of its own.
"""

from __future__ import annotations

import http.client
import json
from collections.abc import Callable

from app.agents.ollama import CALL_FAILURES, MAX_RESPONSE_BYTES, OllamaClient, ServerError
from app.core.config import LLMSettings
from app.risk.bill import Bill
from app.risk.models import CounterEvidence, LinkKind, Method, ModelReview, Risk, State
from app.risk.text import clip

MAX_GROUPS = 5
MAX_PROMPT_TEXT = 1500  # characters per text shown to the model
MIN_QUOTE = 12
ANSWERS = ("covered", "not_covered", "unclear")
Generator = Callable[[str], str]


class OllamaGenerator(OllamaClient):
    """``POST /api/generate`` of a local Ollama server, JSON output, temperature 0."""

    def __init__(self, settings: LLMSettings) -> None:
        super().__init__(settings.base_url, timeout_seconds=settings.request_timeout_seconds)
        self._model = settings.model or ""
        self.last_usage: tuple[int | None, int | None] = (None, None)  # prompt, output tokens
        self.last_stop: str | None = None
        self._options = {
            "temperature": 0,
            "num_predict": settings.max_output_tokens,
            "num_ctx": settings.context_tokens,
        }

    def __call__(self, prompt: str) -> str:
        self.last_stop = None
        body = json.dumps(
            {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": self._options,
            }
        ).encode()
        connection: http.client.HTTPConnection
        if self._https:
            connection = http.client.HTTPSConnection(self._host, self._port, timeout=self._timeout)
        else:
            connection = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            connection.request(
                "POST",
                self._prefix + "/api/generate",
                body=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response = connection.getresponse()
            data = response.read(MAX_RESPONSE_BYTES + 1)
        finally:
            connection.close()
        if response.status != 200 or len(data) > MAX_RESPONSE_BYTES:
            raise ServerError(f"status {response.status}")
        parsed = json.loads(data)
        text = parsed.get("response") if isinstance(parsed, dict) else None
        if not isinstance(text, str):
            raise ServerError("no response text")
        self.last_usage = (parsed.get("prompt_eval_count"), parsed.get("eval_count"))
        stop = parsed.get("done_reason")
        self.last_stop = stop if isinstance(stop, str) else None
        return text


def review(
    risks: list[Risk],
    bill: Bill,
    settings: LLMSettings,
    *,
    requested: bool,
    generator: Generator | None = None,
) -> tuple[list[Risk], ModelReview]:
    if not requested:
        return risks, ModelReview(
            status="not_requested",
            detail="Not requested: no model looked at the open reminders of this report. "
            "Reading a report never calls a model; this review runs only when a caller of the "
            "service asks for it explicitly.",
        )
    if generator is None:
        if settings.provider == "none" or settings.model is None:
            return risks, ModelReview(
                status="not_configured",
                detail="No local model is configured; every result comes from the rule checks.",
            )
        generator = OllamaGenerator(settings)
    # The model's own hypotheses (discovery) are not sent back to it for a second look.
    selected = [
        r for r in risks if r.state is State.CANNOT_TELL and Method.GUIDED_LLM not in r.methods
    ][:MAX_GROUPS]
    if not selected:
        return risks, ModelReview(status="not_needed", detail="No open question to look at.")
    answered = kept = dropped = failures = 0
    updated: dict[str, Risk] = {}
    for number, risk in enumerate(selected):
        try:
            raw = generator(_prompt(risk, bill))
        except CALL_FAILURES:
            failures += 1
            if answered == 0 and number == 0:
                failures = len(selected)  # the server is not reachable: do not wait for each
                break
            continue
        answered += 1
        hint = _verified(raw, bill)
        if hint is None:
            dropped += 1
            continue
        kept += 1
        updated[risk.risk_id] = risk.model_copy(
            update={"counter_evidence": [*risk.counter_evidence, hint]}
        )
    detail = (
        f"Asked about {len(selected)} open questions: {answered} answered, {kept} hints kept "
        f"(quotes verified in the bill), {dropped} dropped as invalid, {failures} failed. Hints "
        "never change a result."
        if answered
        else "The local model did not answer (unreachable, timed out or failed); every other "
        "result is unchanged."
    )
    return [updated.get(r.risk_id, r) for r in risks], ModelReview(
        status="completed" if answered else "unavailable",
        detail=detail,
        groups_selected=len(selected),
        groups_answered=answered,
        hints_kept=kept,
        hints_dropped=dropped,
        failures=failures,
    )


def _prompt(risk: Risk, bill: Bill) -> str:
    by_row = {(p.table_id, p.row_id): p for p in bill.positions}
    texts = []
    for ref in risk.positions[:3]:
        position = by_row.get((ref.table_id, ref.row_id))
        if position is not None:
            texts.append(f"[{position.label}] {clip(position.original, MAX_PROMPT_TEXT)}")
    for evidence in risk.counter_evidence[:4]:
        texts.append(f"[{evidence.position or 'note'}] {clip(evidence.text, MAX_PROMPT_TEXT)}")
    return (
        "You check a German bill of quantities. Question: "
        f"{risk.question or risk.title}\n\nTexts from the bill (label in brackets):\n"
        + "\n".join(texts)
        + '\n\nAnswer only with JSON: {"answer": "covered" | "not_covered" | "unclear", '
        '"cited_positions": [labels from the brackets, or "note"], "quote": "words copied '
        'exactly from one cited text"}. Use only these texts; add no numbers, standards or '
        "past cases."
    )


def _verified(raw: str, bill: Bill) -> CounterEvidence | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    answer, cited, quoted = data.get("answer"), data.get("cited_positions"), data.get("quote")
    if answer not in ANSWERS or not isinstance(quoted, str) or not isinstance(cited, list):
        return None
    if not cited or len(cited) > 5 or not all(isinstance(c, str) for c in cited):
        return None
    by_label = {p.label: p for p in bill.positions}
    sources: list[str] = []
    for label in cited:
        if label == "note":
            sources.extend(n.text for n in bill.notes)
        elif label in by_label:
            sources.append(by_label[label].original)
        else:
            return None  # an invented position
    words = " ".join(quoted.split())
    if len(words) < MIN_QUOTE or not any(words in " ".join(s.split()) for s in sources):
        return None
    first = cited[0]
    return CounterEvidence(
        position=None if first == "note" else first,
        source="local model hint (quote checked against the bill)",
        text=clip(words, 1000),
        link=LinkKind.MODEL_HINT,
        detail=f"The local model reads this as '{answer}'. A hint only: check it yourself; it "
        "does not change the result.",
    )
