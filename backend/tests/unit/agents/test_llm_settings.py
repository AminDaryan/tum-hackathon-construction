"""LLM settings (``TWB_LLM__...``) and the model allow-list, both checked at start-up: a base
URL on another host needs ``allow_remote``, and a configured model must be allowed."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.models import (
    ALLOWED_MODELS,
    WEIGHT_LICENCES,
    AllowedModel,
    ModelNotAllowedError,
    check_configured_model,
)
from app.core.config import LLMSettings, Settings
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services.workbench import build_workbench

EXAMPLE = AllowedModel(
    name="example-model:7b", licence="Apache-2.0", source="https://example.org/models/example"
)


def test_defaults() -> None:
    llm = Settings().llm
    assert llm == LLMSettings()
    assert (llm.provider, llm.base_url, llm.model) == ("none", "http://127.0.0.1:11434", None)
    assert (llm.connect_timeout_seconds, llm.request_timeout_seconds) == (3.0, 180.0)
    assert (llm.context_tokens, llm.max_output_tokens) == (8192, 1024)
    assert llm.allow_remote is False and llm.reuse_cached is True


def test_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWB_LLM__PROVIDER", "ollama")
    monkeypatch.setenv("TWB_LLM__MODEL", "example-model:7b")
    monkeypatch.setenv("TWB_LLM__BASE_URL", "http://localhost:11500")
    monkeypatch.setenv("TWB_LLM__CONNECT_TIMEOUT_SECONDS", "1.5")
    llm = Settings().llm
    assert (llm.provider, llm.model, llm.base_url) == (
        "ollama",
        "example-model:7b",
        "http://localhost:11500",
    )
    assert llm.connect_timeout_seconds == 1.5


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://LOCALHOST:11434/",
        "http://[::1]:11434",
        "https://localhost/ollama",
        "http://127.0.0.1",
    ],
)
def test_this_machine_is_allowed(url: str) -> None:
    assert LLMSettings(base_url=url).base_url == url


@pytest.mark.parametrize(
    "url",
    ["http://ollama:11434", "http://192.168.1.20:11434", "https://llm.example.org", "http://[::2]"],
)
def test_other_hosts_need_allow_remote(url: str) -> None:
    with pytest.raises(ValidationError, match="names a host other than this machine"):
        LLMSettings(base_url=url)
    assert LLMSettings(base_url=url, allow_remote=True).base_url == url


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("ftp://127.0.0.1/", "must be an http:// or https:// URL"),
        ("127.0.0.1:11434", "must be an http:// or https:// URL"),
        ("http://:11434", "must be an http:// or https:// URL"),
        ("http://user:secret@127.0.0.1:11434", "must not contain a user name or password"),
        ("http://127.0.0.1:11434/?key=1", "must not contain a query or a fragment"),
        ("http://127.0.0.1:11434/#x", "must not contain a query or a fragment"),
        ("http://127.0.0.1:port", "is not a valid URL"),
        ("http://127.0.0.1:99999", "is not a valid URL"),
    ],
)
def test_malformed_urls(url: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        LLMSettings(base_url=url, allow_remote=True)


def test_errors_do_not_repeat_the_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWB_LLM__BASE_URL", "http://user:hunter2@127.0.0.1:11434")
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    assert "hunter2" not in str(excinfo.value)
    assert "must not contain a user name or password" in str(excinfo.value)


def test_limits() -> None:
    with pytest.raises(ValidationError, match=r"smaller than llm\.context_tokens"):
        LLMSettings(context_tokens=2048, max_output_tokens=2048)
    with pytest.raises(ValidationError):
        LLMSettings(connect_timeout_seconds=0)
    with pytest.raises(ValidationError):
        LLMSettings(model="bad name with spaces")
    with pytest.raises(ValidationError):
        LLMSettings(provider="openai")  # type: ignore[arg-type]  # an unsupported provider, on purpose
    with pytest.raises(ValidationError):
        LLMSettings(api_key="x")  # type: ignore[call-arg]  # an unknown setting, on purpose


class TestAllowList:
    def test_it_lists_the_checked_model_and_is_read_only(self) -> None:
        assert sorted(ALLOWED_MODELS) == ["qwen2.5:7b-instruct"]
        assert ALLOWED_MODELS["qwen2.5:7b-instruct"].licence == "Apache-2.0"
        with pytest.raises(TypeError):
            ALLOWED_MODELS["x"] = EXAMPLE  # type: ignore[index]  # read-only: the test checks that
        assert all(name == entry.name for name, entry in ALLOWED_MODELS.items())

    def test_weights_need_apache_or_mit(self) -> None:
        assert frozenset({"Apache-2.0", "MIT"}) == WEIGHT_LICENCES
        for licence in ("CC-BY-NC-4.0", "GPL-3.0-only", "Llama-3.1-Community", "apache-2.0", ""):
            with pytest.raises(ValueError, match=r"under Apache-2\.0 or MIT, not"):
                AllowedModel(name="other:1b", licence=licence, source="x")
        assert AllowedModel(name="other:1b", licence="MIT", source="x").licence == "MIT"

    def test_no_model_configured(self) -> None:
        assert check_configured_model(LLMSettings()) is None
        assert check_configured_model(LLMSettings(provider="ollama")) is None

    def test_a_model_that_is_not_allowed_is_refused(self) -> None:
        settings = LLMSettings(provider="ollama", model="example-model:7b")
        with pytest.raises(ModelNotAllowedError) as excinfo:
            check_configured_model(settings)
        assert excinfo.value.code == "model_not_allowed"
        assert excinfo.value.message == (
            "The configured language model 'example-model:7b' is not on the allow-list of "
            "models the workbench may use (allowed: qwen2.5:7b-instruct). Unset "
            "TWB_LLM__MODEL or choose an allowed model."
        )
        other = {"other:1b": AllowedModel(name="other:1b", licence="MIT", source="x")}
        with pytest.raises(ModelNotAllowedError, match=r"\(allowed: other:1b\)"):
            check_configured_model(settings, other)

    def test_an_allowed_model(self) -> None:
        settings = LLMSettings(provider="ollama", model="example-model:7b")
        assert check_configured_model(settings, {EXAMPLE.name: EXAMPLE}) is EXAMPLE

    def test_the_workbench_refuses_to_start(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            environment="test",
            llm=LLMSettings(provider="ollama", model="example-model:7b"),
        )
        uow = InMemoryUnitOfWorkFactory(InMemoryDatabase())
        with pytest.raises(ModelNotAllowedError):
            build_workbench(settings, uow=uow)
        workbench = build_workbench(settings, uow=uow, allowed_models={EXAMPLE.name: EXAMPLE})
        workbench.close()
