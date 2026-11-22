"""The built web interface (``Settings.frontend_dist_dir``), served by the backend.

When the setting names a directory with ``index.html`` (the output of ``npm run build``), its
files are served at ``/`` with explicit media types, and client-side routes (paths whose last
segment has no file extension, such as ``/documents/doc_1``) get ``index.html``. The interface
only answers requests that no route matched, never under ``/api``, and only ``GET`` and
``HEAD``; everything else keeps the router's JSON 404. "Under ``/api``" is checked on the path
as sent and on the path the file lookup uses, which drops empty, ``.`` and ``..`` segments, so
``//api/...`` or ``/x/%2e%2e/api/...`` cannot reach a file of the build either. It sits behind
the same host and origin checks as the API, and its files forbid framing (``NO_FRAMING``).
Files outside the directory (Starlette's static files) and hidden files and directories (a
segment that starts with ``.``, such as ``.env`` or ``.git/``) are never served.
"""

from __future__ import annotations

import logging
from os import PathLike, stat_result
from pathlib import Path, PurePath

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.middleware import route_path

logger = logging.getLogger(__name__)

RESERVED_PREFIXES = ("/api",)  # never answered by the interface
# Media types of the files a Vite build produces; text types get "; charset=utf-8".
MEDIA_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".txt": "text/plain",
    ".wasm": "application/wasm",
}
INDEX = "index.html"
HASHED_ASSETS = "assets"  # Vite's output directory for content-hashed files
# Clickjacking: no other site may show the interface in a frame and trick a reviewer into
# clicking (a review decision or a run is one click away). The CSP directive is the modern
# form, X-Frame-Options the one older browsers know.
NO_FRAMING = {"Content-Security-Policy": "frame-ancestors 'none'", "X-Frame-Options": "DENY"}


class _InterfaceFiles(StaticFiles):
    def file_response(
        self,
        full_path: PathLike[str] | str,
        stat_result: stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        path = Path(full_path)
        response = FileResponse(
            path,
            status_code=status_code,
            stat_result=stat_result,
            media_type=MEDIA_TYPES.get(path.suffix.lower()),  # None: guessed from the name
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.update(NO_FRAMING)
        # Only Vite's assets are content-hashed (a new build gives them new names), so only they
        # may be reused without asking. Every other file keeps its address across builds
        # (index.html, the Coordination Lab's models, manifests and source copies) and is
        # revalidated (ETag) on every load, so a rebuild is never hidden behind a cached copy.
        if not self._hashed(path):
            response.headers["Cache-Control"] = "no-cache"
        if self.is_not_modified(response.headers, Headers(scope=scope)):
            return NotModifiedResponse(response.headers)
        return response

    def _hashed(self, path: Path) -> bool:
        """Whether ``path`` is one of the build's content-hashed assets (``/assets/``)."""
        try:
            relative = path.resolve().relative_to(Path(str(self.directory)).resolve())
        except ValueError:
            return False
        return relative.parts[:1] == (HASHED_ASSETS,)


def _reserved(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in RESERVED_PREFIXES)


def _refused_lookup(lookup: str) -> bool:
    """Whether the file lookup path (normalized, with the OS's separators) is under a reserved
    prefix or names a hidden file or directory, or one outside the build (``..``)."""
    parts = PurePath(lookup).parts  # "." (the root itself) has no parts
    return _reserved("/" + "/".join(parts)) or any(part.startswith(".") for part in parts)


def _client_route(path: str) -> bool:
    return "." not in path.rsplit("/", 1)[-1]


class BuiltInterface:
    """The router's fallback: a file of the build, ``index.html`` for a client-side route, or
    ``not_found`` (the router's own 404) for everything else."""

    def __init__(self, directory: Path, *, not_found: ASGIApp) -> None:
        self.files = _InterfaceFiles(directory=directory)
        self.not_found = not_found

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = route_path(scope) if scope["type"] == "http" else ""  # without a root path
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD") or _reserved(path):
            await self.not_found(scope, receive, send)
            return
        lookup = self.files.get_path(scope)
        if _refused_lookup(lookup):
            await self.not_found(scope, receive, send)
            return
        try:
            response = await self.files.get_response(lookup, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not _client_route(path):
                raise
            response = await self.files.get_response(INDEX, scope)
        await response(scope, receive, send)


def serve_built_interface(app: FastAPI, directory: Path | None) -> bool:
    """Serve the build in ``directory`` for requests no route matches; ``False`` when there is
    nothing to serve (no setting, or no ``index.html`` in it)."""
    if directory is None:
        return False
    if not (directory / INDEX).is_file():
        logger.warning("frontend_dist_dir has no %s; the web interface is not served", INDEX)
        return False
    app.router.default = BuiltInterface(directory.resolve(), not_found=app.router.not_found)
    logger.info("serving the built web interface at /")
    return True
