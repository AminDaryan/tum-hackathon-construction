"""The language model's status for ``GET /health``: probed against a local stand-in for an
Ollama server, at most once every 30 seconds, with the connect timeout; no network at all
when no provider is configured."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.models import AllowedModel
from app.agents.ollama import (
    MAX_RESPONSE_BYTES,
    NO_MODEL,
    NOT_CONFIGURED,
    NOT_INSTALLED,
    NOT_REACHABLE,
    PROBE_INTERVAL_SECONDS,
    UNEXPECTED_RESPONSE,
    LLMHealth,
    LLMStatus,
    installed,
)
from app.core.clock import FixedClock
from app.core.config import LLMSettings, Settings
from app.core.ids import SequentialIdFactory
from app.main import create_app
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services.workbench import build_workbench
from app.storage.file_store import LocalFileStore
from tests.unit.agents.fake_ollama import DIGEST, MODEL, FakeOllama, closed_port_url, fake_ollama


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _health(base_url: str, model: str | None = MODEL, **settings: object) -> LLMHealth:
    values = {"provider": "ollama", "base_url": base_url, "model": model, **settings}
    return LLMHealth(LLMSettings.model_validate(values), monotonic=Clock())


@pytest.fixture
def server() -> Iterator[FakeOllama]:
    with fake_ollama() as fake:
        yield fake


def test_no_provider_means_no_network(server: FakeOllama) -> None:
    health = LLMHealth(LLMSettings(base_url=server.base_url, model=MODEL))
    assert health.status() == LLMStatus(
        provider="none", model=None, ready=False, reason=NOT_CONFIGURED
    )
    assert server.paths == []


def test_no_model_means_no_network(server: FakeOllama) -> None:
    status = _health(server.base_url, model=None).status()
    assert (status.ready, status.reason, status.model) == (False, NO_MODEL, None)
    assert server.paths == []


def test_ready(server: FakeOllama) -> None:
    status = _health(server.base_url).status()
    assert status == LLMStatus(
        provider="ollama",
        model=MODEL,
        ready=True,
        reason=None,
        server_version="0.9.0",
        model_digest=DIGEST,
    )
    assert server.paths == ["/api/version", "/api/tags"]


def test_model_not_installed(server: FakeOllama) -> None:
    server.models = [{"name": "other:1b", "model": "other:1b", "digest": DIGEST}]
    status = _health(server.base_url).status()
    assert (status.ready, status.reason, status.server_version) == (False, NOT_INSTALLED, "0.9.0")
    assert status.model_digest is None


def test_a_name_without_a_tag_is_the_latest_tag() -> None:
    models = [{"name": "example:latest", "digest": "a"}, {"model": "other:2b", "digest": "b"}]
    assert installed(models, "example") == models[0]
    assert installed(models, "example:latest") == models[0]
    assert installed(models, "other:2b") == models[1]
    assert installed(models, "other") is None
    assert installed(models, "example:7b") is None


def test_server_not_reachable() -> None:
    status = _health(closed_port_url()).status()
    assert (status.ready, status.reason, status.server_version) == (False, NOT_REACHABLE, None)


def test_the_connect_timeout_bounds_the_probe(server: FakeOllama) -> None:
    server.delay_seconds = 2.0
    started = time.monotonic()
    status = _health(server.base_url, connect_timeout_seconds=0.2).status()
    assert time.monotonic() - started < 1.5
    assert status.reason == NOT_REACHABLE


@pytest.mark.parametrize(
    "change",
    [
        {"status": 500},
        {"raw_body": b"not json"},
        {"raw_body": b"[1, 2]"},
        {"version": 7},
        {"version": ""},
        {"version": "x" * 201},
        {"models": "none"},
        {"models": ["a"]},
        {"raw_body": b" " * (MAX_RESPONSE_BYTES + 1)},
    ],
)
def test_unexpected_answers(server: FakeOllama, change: dict[str, object]) -> None:
    for name, value in change.items():
        setattr(server, name, value)
    status = _health(server.base_url).status()
    assert (status.ready, status.reason) == (False, UNEXPECTED_RESPONSE)


def test_a_digest_that_is_not_text_is_not_shown(server: FakeOllama) -> None:
    server.models = [{"name": MODEL, "digest": 42}]
    status = _health(server.base_url).status()
    assert status.ready and status.model_digest is None


def test_a_path_prefix_is_kept() -> None:
    with fake_ollama("/ollama") as fake:
        status = _health(fake.base_url).status()
        assert status.ready
        assert fake.paths == ["/ollama/api/version", "/ollama/api/tags"]


def test_probed_at_most_every_30_seconds(server: FakeOllama) -> None:
    clock = Clock()
    llm = LLMSettings(provider="ollama", base_url=server.base_url, model=MODEL)
    health = LLMHealth(llm, monotonic=clock)
    first = health.status()
    clock.now += PROBE_INTERVAL_SECONDS - 0.1
    server.models = []  # the server changed, but the next probe is not due yet
    assert health.status() is first
    assert len(server.paths) == 2
    clock.now += 0.2
    second = health.status()
    assert (second.ready, second.reason) == (False, NOT_INSTALLED)
    assert len(server.paths) == 4
    assert PROBE_INTERVAL_SECONDS == 30.0


def test_a_failed_probe_is_cached_too() -> None:
    clock = Clock()
    llm = LLMSettings(provider="ollama", base_url=closed_port_url(), model=MODEL)
    health = LLMHealth(llm, monotonic=clock)
    first = health.status()
    assert health.status() is first


class TestHealthEndpoint:
    def test_not_configured_by_default(self, tmp_path: Path) -> None:
        workbench = build_workbench(
            Settings(data_dir=tmp_path, environment="test"),
            uow=InMemoryUnitOfWorkFactory(InMemoryDatabase()),
        )
        with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
            body = client.get("/api/v1/health").json()
        workbench.close()
        assert body["llm"] == {
            "provider": "none",
            "model": None,
            "ready": False,
            "reason": "not configured",
            "server_version": None,
            "model_digest": None,
        }
        assert body["ai_planner"]["configured"] is False  # unchanged

    def test_a_configured_and_installed_model(self, tmp_path: Path, server: FakeOllama) -> None:
        llm = LLMSettings(provider="ollama", base_url=server.base_url, model=MODEL)
        allowed = {MODEL: AllowedModel(name=MODEL, licence="Apache-2.0", source="test")}
        workbench = build_workbench(
            Settings(data_dir=tmp_path, environment="test", llm=llm),
            uow=InMemoryUnitOfWorkFactory(InMemoryDatabase()),
            files=LocalFileStore(tmp_path),
            ids=SequentialIdFactory(),
            clock=FixedClock(),
            allowed_models=allowed,
        )
        with TestClient(create_app(workbench=workbench), base_url="http://localhost") as client:
            first = client.get("/api/v1/health").json()["llm"]
            again = client.get("/api/v1/health").json()["llm"]
        workbench.close()
        assert first == {
            "provider": "ollama",
            "model": MODEL,
            "ready": True,
            "reason": None,
            "server_version": "0.9.0",
            "model_digest": DIGEST,
        }
        assert again == first
        assert len(server.paths) == 2  # the second health check answered from the last probe
