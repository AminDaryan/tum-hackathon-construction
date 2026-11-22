"""The FastAPI application.

Run locally (bound to the loopback interface; sign-in is optional, see ``Settings.auth``)::

    uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000

With ``TWB_FRONTEND_DIST_DIR`` naming the web interface's build, the same process serves it at
``/`` (``app.api.interface``).

Middleware, outermost first: request id, access log, trusted hosts (DNS-rebinding protection),
the optional gate (``app.api.gate``), CORS for the dev origin, the CSRF origin check, sign-in and
roles (``app.api.auth``), request body limits. Logging (``Settings.logging``) is configured when
the application builds its own workbench, i.e. on a real start.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI

from app.api.auth import BearerAuthMiddleware, check_tokens, document_bearer_auth
from app.api.errors import REQUEST_ID_HEADER, install_error_handlers
from app.api.gate import GateMiddleware
from app.api.interface import serve_built_interface
from app.api.middleware import (
    AccessLogMiddleware,
    BodyLimitMiddleware,
    EnvelopeCORSMiddleware,
    HostCheckMiddleware,
    OriginCheckMiddleware,
    RequestIdMiddleware,
)
from app.api.routes import api_router
from app.api.routes.documents import UPLOAD_PATH
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services import projects, runs, users
from app.services.catalogue import _version
from app.services.collaboration import seed_reviewers
from app.services.workbench import Workbench, build_workbench

API_PREFIX = "/api/v1"
OPEN_GET_PATHS = frozenset({API_PREFIX + "/health"})  # open even when sign-in is required


def create_app(settings: Settings | None = None, *, workbench: Workbench | None = None) -> FastAPI:
    """The application. Tests pass a ``workbench`` (in-memory storage, fixed ids and clock);
    otherwise one is built from ``settings`` and closed on shutdown."""
    if workbench is None:
        settings = settings or get_settings()
        configure_logging(settings.logging)  # a real start; tests keep their runner's logging
        workbench = build_workbench(settings)
        owned = True
    else:
        owned = False
    wb = workbench
    settings = wb.settings

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(runs.recover_interrupted, wb)  # runs a crash left unfinished
        await asyncio.to_thread(projects.recover_interrupted, wb)
        await asyncio.to_thread(runs.check_unvalidated, wb)  # bills without a run
        await asyncio.to_thread(seed_reviewers, wb)
        if owned:  # a real start; a test's workbench starts with nothing kept to warm
            projects.read_questions_at_start(wb)
        yield
        if owned:  # closing shuts the job runner down, which waits for running background runs
            await asyncio.to_thread(wb.close)

    app = FastAPI(
        title="Desvio",
        version=_version(),
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
    )
    app.state.workbench = wb
    install_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    serve_built_interface(app, settings.frontend_dist_dir)  # only what no route matches
    # add_middleware puts each new middleware outside the previous ones.
    app.add_middleware(
        BodyLimitMiddleware,
        json_limit=settings.max_json_body_bytes,
        upload_limit=settings.ingestion.max_upload_bytes,
        upload_path=API_PREFIX + UPLOAD_PATH,
    )
    # Every API request acts for an identity, and its role decides what it may do. With sign-in
    # required, unauthenticated requests never reach a route.
    tokens = [token.get_secret_value() for token in settings.auth.tokens]
    check_tokens(tokens)  # at start: the middleware is only built when the first request comes
    app.add_middleware(
        BearerAuthMiddleware,
        tokens=tokens,
        prefix=API_PREFIX,
        open_get_paths=OPEN_GET_PATHS,
        resolve_user=partial(users.signed_in_identity, wb),
    )
    if settings.auth.required:
        document_bearer_auth(app, prefix=API_PREFIX, open_get_paths=OPEN_GET_PATHS)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(
        EnvelopeCORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        # Location and Preference-Applied answer Prefer: respond-async (202, contract K3).
        expose_headers=[REQUEST_ID_HEADER, "Content-Disposition", "Location", "Preference-Applied"],
    )
    if settings.gate_phrase is not None:  # inside the host check, outside everything else
        app.add_middleware(GateMiddleware, phrase=settings.gate_phrase.get_secret_value())
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app
