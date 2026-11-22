"""Claude through Anthropic's official Python SDK.

The SDK (``anthropic``, the optional ``llm`` extra) is imported only when a generator is made,
so the app starts and its tests run without it. Two callers: the bill review a reviewer starts
for one bill (:mod:`app.services.bill_reviews`) and the evaluation tool
(:mod:`app.evaluation.llm_review`). Nothing else in the app sends a bill to Anthropic.
"""

from __future__ import annotations

import importlib
import importlib.util
import threading
from collections import Counter
from typing import Any


def installed() -> bool:
    """Whether the optional SDK can be imported (nothing is imported to find out)."""
    return importlib.util.find_spec("anthropic") is not None


def json_text(text: str) -> str:
    """The JSON object of an answer that may wrap it in a code fence or a sentence."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text.strip()


# Anthropic's list prices in USD per million tokens: input, output, cache read, cache write
# (5 minutes). Used only to report what a run cost.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
}


class ClaudeGenerator:
    """A prompt in, the model's answer out. Without ``api_key`` the SDK reads the environment
    variable ``ANTHROPIC_API_KEY`` (the evaluation tool); the app passes its own key.

    Every request streams (``messages.stream`` and ``get_final_message``), thinks adaptively at
    the given effort, and sends the prompt in text blocks: the shared context layer first,
    marked for the prompt cache, then the part and the question. Rate limits and server errors
    are retried by the SDK (``max_retries``). On Claude Opus 5.5 and Sonnet 5.5 a declined
    request is re-run server-side on Anthropic's recommended fallback model
    (``fallbacks: "default"``). Safe to call from several threads; ``last_usage`` is the calling
    thread's last request (all input tokens, output tokens), :meth:`usage` the totals of every
    request."""

    FALLBACK = ("claude-opus-5-5", "claude-sonnet-5-5")
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(
        self,
        *,
        model: str,
        max_output_tokens: int,
        timeout: float,
        effort: str,
        max_retries: int = 6,
        api_key: str | None = None,
        client: Any = None,
        sdk: Any = None,
    ) -> None:
        if sdk is None:  # the optional dependency, imported only when a generator is made
            sdk = importlib.import_module("anthropic")
        self._sdk = sdk
        self._client = client or sdk.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )
        self.model = model
        self._max_tokens = max_output_tokens
        self._effort = effort
        self._local = threading.local()
        self._lock = threading.Lock()
        self._totals: Counter[str] = Counter()

    @property
    def last_usage(self) -> tuple[int | None, int | None]:
        usage: tuple[int | None, int | None] = getattr(self._local, "usage", (None, None))
        return usage

    def usage(self) -> dict[str, Any]:
        """Tokens of every request so far and what they cost at :data:`PRICES`."""
        with self._lock:
            totals = dict(self._totals)
        price = PRICES.get(self.model)
        cost = None
        if price is not None:
            cost = (
                totals.get("input", 0) * price[0]
                + totals.get("output", 0) * price[1]
                + totals.get("cache_read", 0) * price[2]
                + totals.get("cache_write", 0) * price[3]
            ) / 1e6
        return {"model": self.model, **totals, "cost_usd": cost}

    def _content(self, prompt: str) -> list[dict[str, Any]]:
        """The context layer and the part each as a cached block (the same part is asked once
        per pass and, with the whole bill, once per judge batch), then the question."""
        head, marker, tail = prompt.partition("\n\n<part>")
        if not marker:
            return [{"type": "text", "text": prompt}]
        part, end, question = tail.partition("</part>")
        cached = {"type": "ephemeral"}
        if not end:
            return [
                {"type": "text", "text": head, "cache_control": cached},
                {"type": "text", "text": "<part>" + tail},
            ]
        return [
            {"type": "text", "text": head, "cache_control": cached},
            {"type": "text", "text": "<part>" + part + "</part>", "cache_control": cached},
            {"type": "text", "text": question},
        ]

    def _send(self, params: dict[str, Any]) -> Any:
        sdk = self._sdk
        try:
            if self.model in self.FALLBACK:
                stream = self._client.beta.messages.stream(
                    **params, betas=[self.FALLBACK_BETA], fallbacks="default"
                )
            else:
                stream = self._client.messages.stream(**params)
            with stream as answer:
                return answer.get_final_message()
        except sdk.AuthenticationError as exc:
            raise RuntimeError("status 401 (authentication_error)") from exc
        except sdk.PermissionDeniedError as exc:
            raise RuntimeError("status 403 (permission_error)") from exc
        except sdk.BadRequestError as exc:
            if "credit balance" in str(exc).lower():
                raise RuntimeError("status 400 (credit_balance_exhausted)") from exc
            raise RuntimeError(f"status 400 ({str(exc)[:200]})") from exc
        except sdk.RateLimitError as exc:
            raise RuntimeError("status 429 (rate limited after the SDK's retries)") from exc
        except sdk.APIStatusError as exc:
            raise RuntimeError(f"status {exc.status_code} ({str(exc)[:200]})") from exc
        except sdk.APIConnectionError as exc:
            raise RuntimeError(f"connection failed ({str(exc)[:200]})") from exc

    def __call__(self, prompt: str) -> str:
        self._local.usage = (None, None)
        message = self._send(
            {
                "model": self.model,
                "max_tokens": self._max_tokens,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": self._effort},
                "messages": [{"role": "user", "content": self._content(prompt)}],
            }
        )
        usage = message.usage
        fresh = getattr(usage, "input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
        written = getattr(usage, "cache_creation_input_tokens", 0) or 0
        output = getattr(usage, "output_tokens", 0) or 0
        self._local.usage = (fresh + read + written, output)
        with self._lock:
            self._totals.update(
                requests=1, input=fresh, cache_read=read, cache_write=written, output=output
            )
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise RuntimeError(f"declined ({getattr(details, 'category', None) or 'refusal'})")
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        if message.stop_reason == "max_tokens":
            # a cut-off answer is reported, never parsed in part
            raise RuntimeError("the output limit was reached, the answer is cut off (raise it)")
        if not text.strip():
            raise RuntimeError("no answer text")
        return json_text(text)
