"""Sign-in and roles (``Settings.auth``, ADR 0015, ``docs/api/rest-api.md``).

Every request under the API prefix acts for an identity (``app.models.user.Identity``):

* a bearer token that is one of the configured ``TWB_AUTH__TOKENS``: the administrator;
* a bearer token of an active user account: that user, with the user's role;
* otherwise, when no tokens are configured, the local administrator (an unknown token is then
  ignored, as before user accounts: sign-in is off);
* otherwise ``401 unauthorized`` with ``WWW-Authenticate: Bearer``.

``GET /api/v1/health`` stays open so that monitors and the web interface can check the server
before anyone signs in. The role decides what the identity may do: a viewer reads, a reviewer
also writes (uploads, runs, reviews, corrections, projects), an administrator also manages the
user accounts (``/users``). Anything else gets ``403 forbidden``. Tokens are compared in
constant time (as SHA-256 digests, so their length does not show either) and are never logged
or echoed.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable, Collection, Sequence
from typing import Any

import anyio.to_thread
from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.errors import rejection
from app.api.middleware import route_path
from app.models.user import LOCAL, SERVICE, Identity, Role
from app.services.identity import acting_as

CHALLENGE = {"WWW-Authenticate": "Bearer"}
SCHEME_NAME = "bearer"
_SENDABLE = re.compile(r"[\x21-\x7e]+")  # visible ASCII: what an Authorization header carries


def check_tokens(tokens: Sequence[str]) -> None:
    """Reject tokens a client could not send; the message names the position, never the token."""
    for position, token in enumerate(tokens, start=1):
        if not _SENDABLE.fullmatch(token):
            raise ValueError(
                f"Setting auth.tokens: token {position} is empty or has spaces or characters "
                "other than visible ASCII."
            )


def _bearer_token(header: str | None) -> str | None:
    if header is None:
        return None
    scheme, _, token = header.strip().partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token else None


ResolveUser = Callable[[str], Identity | None]
READS = frozenset({"GET", "HEAD"})


def required_role(method: str, path: str, prefix: str) -> Role:
    """The least role that may send ``method`` to ``path`` (a path under ``prefix``)."""
    relative = path[len(prefix) :].rstrip("/")
    if relative == "/me":
        return Role.VIEWER
    if relative == "/users" or relative.startswith("/users/"):
        return Role.ADMIN
    return Role.VIEWER if method in READS else Role.REVIEWER


class BearerAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        tokens: Sequence[str],
        prefix: str,
        open_get_paths: Collection[str] = (),
        resolve_user: ResolveUser | None = None,
    ) -> None:
        check_tokens(tokens)
        self.app = app
        self.digests = tuple(hashlib.sha256(token.encode()).digest() for token in tokens)
        self.prefix = prefix
        self.open_get_paths = frozenset(open_get_paths)
        self.resolve_user = resolve_user

    @property
    def required(self) -> bool:
        return bool(self.digests)

    def _under_prefix(self, path: str) -> bool:
        return path == self.prefix or path.startswith(self.prefix + "/")

    def _known(self, token: str) -> bool:
        digest = hashlib.sha256(token.encode()).digest()
        matched = False
        for known in self.digests:  # no early exit: every token is compared
            matched |= hmac.compare_digest(digest, known)
        return matched

    async def _identity(self, token: str | None) -> Identity | None:
        if token is None:
            return None if self.required else LOCAL
        if self.digests and self._known(token):
            return SERVICE
        if self.resolve_user is not None:
            user = await anyio.to_thread.run_sync(self.resolve_user, token)
            if user is not None:
                return user
        return None if self.required else LOCAL  # sign-in off: an unknown token changes nothing

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = route_path(scope)  # as the router matches it, so a root path cannot skip the check
        method = scope["method"]
        if not self._under_prefix(path) or (
            method == "GET" and path.rstrip("/") in self.open_get_paths
        ):
            await self.app(scope, receive, send)
            return
        token = _bearer_token(Headers(scope=scope).get("authorization"))
        identity = await self._identity(token)
        if identity is None:
            message = (
                "Sign-in required: send 'Authorization: Bearer <token>'."
                if token is None
                else "The token is not valid."
            )
            response = rejection(scope, 401, "unauthorized", message, headers=CHALLENGE)
            await response(scope, receive, send)
            return
        needed = required_role(method, path, self.prefix)
        if not identity.role.includes(needed):
            response = rejection(
                scope,
                403,
                "forbidden",
                f"This needs the {needed.value} role; {identity.name} is a {identity.role.value}.",
                details={"role": identity.role.value, "required_role": needed.value},
            )
            await response(scope, receive, send)
            return
        with acting_as(identity):
            await self.app(scope, receive, send)


def document_bearer_auth(app: FastAPI, *, prefix: str, open_get_paths: Collection[str]) -> None:
    """Declare the bearer scheme in ``/openapi.json`` for the protected operations, so the
    interactive docs (``/docs``) can send a token."""
    build: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = build()
        schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        schemes[SCHEME_NAME] = {"type": "http", "scheme": "bearer"}
        for path, item in schema["paths"].items():
            if not path.startswith(prefix):
                continue
            for method, operation in item.items():
                if not (method == "get" and path in open_get_paths):
                    operation["security"] = [{SCHEME_NAME: []}]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]  # FastAPI's documented override
