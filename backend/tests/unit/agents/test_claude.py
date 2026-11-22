"""The Claude generator (:mod:`app.agents.claude`) with a stand-in for Anthropic's SDK: no
request leaves the machine."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.claude import ClaudeGenerator
from app.evaluation.llm_review import STOP_CODES


class _FakeSdk:
    """Stands in for the ``anthropic`` package: its error classes and a client whose streams
    return a prepared message."""

    class APIStatusError(Exception):
        status_code = 500

    class AuthenticationError(APIStatusError):
        pass

    class PermissionDeniedError(APIStatusError):
        pass

    class BadRequestError(APIStatusError):
        pass

    class RateLimitError(APIStatusError):
        pass

    class APIConnectionError(Exception):
        pass


class _FakeStream:
    def __init__(self, message: object) -> None:
        self._message = message

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get_final_message(self) -> object:
        if isinstance(self._message, Exception):
            raise self._message
        return self._message


def _claude_answer(text: str, stop: str = "end_turn") -> object:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop,
        stop_details=SimpleNamespace(category="cyber") if stop == "refusal" else None,
        usage=SimpleNamespace(
            input_tokens=100,
            cache_read_input_tokens=900,
            cache_creation_input_tokens=0,
            output_tokens=50,
        ),
    )


def test_the_anthropic_generator_streams_caches_the_context_and_counts_the_cost() -> None:
    sent: list[tuple[str, dict[str, object]]] = []
    answers = iter(
        [
            _claude_answer('Here it is:\n```json\n{"issues": []}\n```'),
            _claude_answer('{"verdicts": []}'),
            _claude_answer("", stop="refusal"),
        ]
    )

    def stream(kind: str) -> object:
        def make(**params: object) -> _FakeStream:
            sent.append((kind, params))
            return _FakeStream(next(answers))

        return make

    client = SimpleNamespace(
        messages=SimpleNamespace(stream=stream("plain")),
        beta=SimpleNamespace(messages=SimpleNamespace(stream=stream("beta"))),
    )
    haiku = ClaudeGenerator(
        model="claude-haiku-5-5",
        max_output_tokens=32000,
        timeout=60,
        effort="medium",
        client=client,
        sdk=_FakeSdk,
    )
    assert haiku("CONTEXT\n\n<part>\nPART\n</part>\n\nYOUR TASK") == '{"issues": []}'
    kind, params = sent[0]
    assert kind == "plain"  # Haiku has no server-side fallback
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "medium"}
    assert "temperature" not in params
    content = params["messages"][0]["content"]  # type: ignore[index]
    assert content == [
        {"type": "text", "text": "CONTEXT", "cache_control": {"type": "ephemeral"}},
        {
            "type": "text",
            "text": "<part>\nPART\n</part>",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "\n\nYOUR TASK"},
    ]
    assert haiku.last_usage == (1000, 50)
    opus = ClaudeGenerator(
        model="claude-opus-5-5",
        max_output_tokens=32000,
        timeout=60,
        effort="medium",
        client=client,
        sdk=_FakeSdk,
    )
    assert opus("no part here") == '{"verdicts": []}'
    kind, params = sent[1]
    assert kind == "beta" and params["fallbacks"] == "default"
    assert params["betas"] == ["server-side-fallback-2026-07-01"]
    with pytest.raises(RuntimeError, match=r"declined \(cyber\)"):
        opus("x")
    usage = opus.usage()
    assert (usage["requests"], usage["input"], usage["cache_read"], usage["output"]) == (
        2,
        200,
        1800,
        100,
    )
    assert usage["cost_usd"] == pytest.approx((200 * 4.0 + 100 * 20.0 + 1800 * 0.2) / 1e6)


def test_the_anthropic_generator_names_an_empty_credit_balance_so_the_run_stops() -> None:
    refused = _FakeSdk.BadRequestError("Your credit balance is too low to access the API.")
    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **_: _FakeStream(refused)))
    haiku = ClaudeGenerator(
        model="claude-haiku-5-5",
        max_output_tokens=100,
        timeout=60,
        effort="low",
        client=client,
        sdk=_FakeSdk,
    )
    with pytest.raises(RuntimeError) as error:
        haiku("x")
    assert any(code in str(error.value) for code in STOP_CODES)


def test_the_generator_gives_the_sdk_the_app_s_key_and_limits() -> None:
    made: list[dict[str, object]] = []

    class Sdk(_FakeSdk):
        @staticmethod
        def Anthropic(**settings: object) -> object:
            made.append(settings)
            return SimpleNamespace()

    ClaudeGenerator(
        model="claude-haiku-5-5",
        max_output_tokens=100,
        timeout=600,
        effort="medium",
        max_retries=2,
        api_key="test-key-not-real",
        sdk=Sdk,
    )
    assert made == [{"api_key": "test-key-not-real", "timeout": 600, "max_retries": 2}]
