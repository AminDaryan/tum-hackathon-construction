"""Whether the configured language model can answer: the ``llm`` part of ``GET /health``.

:class:`LLMHealth` asks the Ollama server for its version (``GET /api/version``) and its
installed models (``GET /api/tags``) at most once every :data:`PROBE_INTERVAL_SECONDS`, each
request with the connect timeout, so the health check stays fast; between probes it answers
from the last result. With ``provider = "none"`` nothing connects anywhere.

Requests use :mod:`http.client` directly: no proxy from the environment and no redirects, so
a request meant for this machine cannot be passed on to another host. Answers are read up to
:data:`MAX_RESPONSE_BYTES`. Nothing from a document is sent; the probe sends no body.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.core.config import LLMSettings

PROBE_INTERVAL_SECONDS = 30.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

# Why the model is not ready (fixed text, shown as ``llm.reason``).
NOT_CONFIGURED = "not configured"
NO_MODEL = "no model configured"
NOT_REACHABLE = "server not reachable"
NOT_INSTALLED = "model not installed"
UNEXPECTED_RESPONSE = "unexpected server response"

_MAX_TEXT = 200  # longest server version or model digest shown


@dataclass(frozen=True, slots=True)
class LLMStatus:
    provider: str
    model: str | None
    ready: bool
    reason: str | None
    server_version: str | None = None
    model_digest: str | None = None


class ServerError(Exception):
    """The server answered, but not as the Ollama API does."""


class OllamaClient:
    """The two read-only calls the health check needs."""

    def __init__(self, base_url: str, *, timeout_seconds: float) -> None:
        parts = urlsplit(base_url)
        if parts.hostname is None:  # pragma: no cover - LLMSettings guarantees a host
            raise ValueError("base_url needs a host")
        self._https = parts.scheme == "https"
        self._host = parts.hostname
        self._port = parts.port
        self._prefix = parts.path.rstrip("/")
        self._timeout = timeout_seconds

    def version(self) -> str:
        data = self._get("/api/version")
        value = data.get("version")
        if not isinstance(value, str) or not value or len(value) > _MAX_TEXT:
            raise ServerError("no version")
        return value

    def models(self) -> list[dict[str, Any]]:
        data = self._get("/api/tags")
        models = data.get("models")
        if not isinstance(models, list) or not all(isinstance(m, dict) for m in models):
            raise ServerError("no model list")
        return models

    def _get(self, path: str) -> dict[str, Any]:
        connection: http.client.HTTPConnection
        if self._https:
            connection = http.client.HTTPSConnection(self._host, self._port, timeout=self._timeout)
        else:
            connection = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            connection.request("GET", self._prefix + path, headers={"Accept": "application/json"})
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
        finally:
            connection.close()
        if response.status != 200 or len(body) > MAX_RESPONSE_BYTES:
            raise ServerError(f"status {response.status}")
        try:
            data = json.loads(body)
        except ValueError:
            raise ServerError("not JSON") from None
        if not isinstance(data, dict):
            raise ServerError("not an object")
        return data


# What a call to the server raises when it fails: no connection or a timeout, a broken HTTP
# exchange, an answer not in the API's shape, or a reply that is not the JSON asked for.
CALL_FAILURES = (OSError, ServerError, http.client.HTTPException, ValueError)


def installed(models: list[dict[str, Any]], model: str) -> dict[str, Any] | None:
    """The entry of ``model`` among the server's installed models (a name without a tag is
    the ``latest`` tag, as Ollama reads it)."""
    wanted = {model, f"{model}:latest"} if ":" not in model else {model}
    for entry in models:
        if entry.get("name") in wanted or entry.get("model") in wanted:
            return entry
    return None


class LLMHealth:
    """The model's status for the health check, probed at most every ``interval_seconds``."""

    def __init__(
        self,
        settings: LLMSettings,
        *,
        interval_seconds: float = PROBE_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._interval = interval_seconds
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last: tuple[float, LLMStatus] | None = None

    def status(self) -> LLMStatus:
        settings = self._settings
        if settings.provider == "none":
            return LLMStatus(provider="none", model=None, ready=False, reason=NOT_CONFIGURED)
        if settings.model is None:
            return LLMStatus(provider=settings.provider, model=None, ready=False, reason=NO_MODEL)
        with self._lock:
            now = self._monotonic()
            if self._last is not None and now - self._last[0] < self._interval:
                return self._last[1]
            status = self._probe(settings.model)
            self._last = (self._monotonic(), status)
            return status

    def _probe(self, model: str) -> LLMStatus:
        settings = self._settings
        client = OllamaClient(settings.base_url, timeout_seconds=settings.connect_timeout_seconds)

        def not_ready(reason: str, version: str | None = None) -> LLMStatus:
            return LLMStatus(
                provider=settings.provider,
                model=model,
                ready=False,
                reason=reason,
                server_version=version,
            )

        try:
            version = client.version()
        except (OSError, http.client.HTTPException):
            return not_ready(NOT_REACHABLE)
        except ServerError:
            return not_ready(UNEXPECTED_RESPONSE)
        try:
            entry = installed(client.models(), model)
        except (OSError, http.client.HTTPException):
            return not_ready(NOT_REACHABLE, version)
        except ServerError:
            return not_ready(UNEXPECTED_RESPONSE, version)
        if entry is None:
            return not_ready(NOT_INSTALLED, version)
        digest = entry.get("digest")
        return LLMStatus(
            provider=settings.provider,
            model=model,
            ready=True,
            reason=None,
            server_version=version,
            model_digest=digest if isinstance(digest, str) and len(digest) <= _MAX_TEXT else None,
        )
