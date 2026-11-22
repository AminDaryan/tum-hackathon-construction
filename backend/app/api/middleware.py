"""Pure ASGI middleware for the local API (``docs/api/rest-api.md``, "Security").

* :class:`RequestIdMiddleware`: a request id per request (echoed when the client's
  ``X-Request-ID`` is a short token), stored in ``scope["state"]`` and sent back as a header.
* :class:`AccessLogMiddleware`: one log line per request, with the error code of a rejection.
* :class:`HostCheckMiddleware`: DNS-rebinding protection; a ``Host`` header that is not an
  allowed host gets ``400 host_not_allowed``.
* :class:`EnvelopeCORSMiddleware`: Starlette's CORS handling, except that a rejected preflight
  request gets the error envelope (``400 origin_not_allowed`` or ``400 preflight_rejected``).
* :class:`OriginCheckMiddleware`: CSRF protection; state-changing requests from a browser origin
  that is not allowed (or marked ``Sec-Fetch-Site: cross-site``) get ``403
  origin_not_allowed``. Requests without ``Origin`` (command-line clients, tests) pass.
* :class:`BodyLimitMiddleware`: request bodies are counted while they stream; the upload route
  may carry ``max_upload_bytes`` (plus multipart overhead), every other route
  ``max_json_body_bytes``. A declared ``Content-Length`` over the limit fails before the body
  is read.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Sequence

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import (
    REQUEST_ID_HEADER,
    RequestTooLargeError,
    error_code_of,
    rejection,
    request_id_of,
)
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_ECHOED_CHARS = 255  # header values quoted back in error details
MAX_LOGGED_PATH_CHARS = 300


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = given if given and _REQUEST_ID.match(given) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if REQUEST_ID_HEADER not in headers:
                    headers.append(REQUEST_ID_HEADER, request_id)
            await send(message)

        token = request_id_var.set(request_id)  # every log line of the request carries it
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class AccessLogMiddleware:
    """One log line per request: method, path (without the query string), status, duration,
    request id, and the error code of a rejected or failed request. Successful requests are
    logged at INFO, 4xx at WARNING, 5xx at ERROR. Headers and bodies are never logged."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500  # unless a response starts: an exception escaped every handler

        async def send_and_note(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        finally:
            self._log(scope, status, (time.perf_counter() - started) * 1000)

    @staticmethod
    def _log(scope: Scope, status: int, duration_ms: float) -> None:
        code = error_code_of(scope) if status >= 400 else None
        if status >= 500:
            level, code = logging.ERROR, code or "internal_error"
        else:
            level = logging.WARNING if status >= 400 else logging.INFO
        method, path = scope["method"], _loggable_path(scope)
        logger.log(
            level,
            "%s %s %d %.1f ms%s",
            method,
            path,
            status,
            duration_ms,
            f" {code}" if code else "",
            extra={
                "request_id": request_id_of(scope),
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "error_code": code,
            },
        )


def _loggable_path(scope: Scope) -> str:
    """The path as sent (percent-encoded, so no control characters reach the log), bounded."""
    raw = scope.get("raw_path")
    path = raw.decode("ascii", "backslashreplace") if isinstance(raw, bytes) else scope["path"]
    path = path.split("?", 1)[0]
    if not path.isprintable():
        path = path.encode("unicode_escape").decode("ascii")
    return path[:MAX_LOGGED_PATH_CHARS]


def route_path(scope: Scope) -> str:
    """The path the router matches: ``scope["path"]`` without the root path that a server run
    behind a proxy puts in front of it (``uvicorn --root-path``), stripped as Starlette's routing
    strips it. A check that guards routes by path must look at this path, not ``scope["path"]``.
    """
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and path.startswith(root) and (path == root or path[len(root)] == "/"):
        return path[len(root) :]
    return path


class HostCheckMiddleware:
    """The rules of Starlette's ``TrustedHostMiddleware`` (an exact host, ``*.example.com`` for
    its sub-domains, ``*`` for any host; the port is ignored), answered with the envelope."""

    def __init__(self, app: ASGIApp, *, allowed_hosts: Sequence[str]) -> None:
        for pattern in allowed_hosts:
            misplaced = "*" in pattern[1:] or (pattern[:1] == "*" and pattern[:2] != "*.")
            if misplaced and pattern != "*":
                raise ValueError(f"Invalid allowed host {pattern!r}: use '*.example.com'.")
        self.app = app
        self.allowed = tuple(allowed_hosts)
        self.allow_any = "*" in self.allowed

    def _allowed(self, host: str) -> bool:
        return any(
            host == pattern or (pattern.startswith("*.") and host.endswith(pattern[1:]))
            for pattern in self.allowed
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.allow_any or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        host = Headers(scope=scope).get("host", "").split(":")[0]
        if self._allowed(host):
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            response = rejection(
                scope,
                400,
                "host_not_allowed",
                "The Host header does not name a host this server answers for.",
                details={"host": host[:MAX_ECHOED_CHARS]},
            )
            await response(scope, receive, send)


class EnvelopeCORSMiddleware(CORSMiddleware):
    """Starlette's CORS handling. A preflight request that fails (an origin, method or header
    that is not allowed) keeps Starlette's status and CORS headers but gets the envelope:
    ``origin_not_allowed`` when the origin is not allowed, else ``preflight_rejected``."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = Headers(scope=scope) if scope["type"] == "http" else None
        if (
            headers is None
            or scope["method"] != "OPTIONS"
            or "origin" not in headers
            or "access-control-request-method" not in headers
        ):
            await super().__call__(scope, receive, send)
            return
        response = self.preflight_response(request_headers=headers)
        if response.status_code >= 400:
            response = self._rejected(scope, headers, response)
        await response(scope, receive, send)

    def _rejected(self, scope: Scope, headers: Headers, response: Response) -> Response:
        origin = headers["origin"]
        text = bytes(response.body).decode("utf-8", "replace")
        failures = [part.strip() for part in text.removeprefix("Disallowed CORS ").split(",")]
        kept = {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in ("content-type", "content-length")
        }
        allowed_origin = self.is_allowed_origin(origin=origin)
        return rejection(
            scope,
            response.status_code,
            "preflight_rejected" if allowed_origin else "origin_not_allowed",
            "The cross-origin request is not allowed"
            + ("." if allowed_origin else " from this origin."),
            details={"origin": origin[:MAX_ECHOED_CHARS], "rejected": failures},
            headers=kept,
        )


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = frozenset(origin.rstrip("/") for origin in allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in _STATE_CHANGING:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            cross_site = headers.get("sec-fetch-site", "").lower() == "cross-site"
            if cross_site or (origin is not None and origin.rstrip("/") not in self.allowed):
                response = rejection(
                    scope,
                    403,
                    "origin_not_allowed",
                    "State-changing requests are only accepted from the workbench's own origin.",
                    details={"origin": origin[:MAX_ECHOED_CHARS]} if origin else None,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    def __init__(
        self, app: ASGIApp, *, json_limit: int, upload_limit: int, upload_path: str
    ) -> None:
        self.app = app
        self.json_limit = json_limit
        self.upload_limit = upload_limit + MULTIPART_OVERHEAD_BYTES
        self.upload_path = upload_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        upload = scope["method"] == "POST" and route_path(scope).rstrip("/") == self.upload_path
        limit = self.upload_limit if upload else self.json_limit
        code = "file_too_large" if upload else "request_too_large"
        declared = Headers(scope=scope).get("content-length")
        too_large = declared is not None and declared.isdigit() and int(declared) > limit
        received = 0

        async def limited() -> Message:
            nonlocal received
            if too_large:
                raise RequestTooLargeError(code, limit)
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestTooLargeError(code, limit)
            return message

        await self.app(scope, limited, send)
