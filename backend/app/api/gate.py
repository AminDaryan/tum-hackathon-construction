"""A site-wide gate for a hosted preview (``Settings.gate_phrase``).

With the setting given, every request without the gate cookie gets a small page with one input,
whatever its path: the interface, its static files and the API alike. Posting the right phrase
to :data:`ENTER_PATH` sets the cookie and redirects back. The cookie holds a hash of the phrase,
not the phrase.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from html import escape
from urllib.parse import parse_qs

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

ENTER_PATH = "/_enter"
COOKIE = "twb_k"
MAX_FORM_BYTES = 4096
COOKIE_MAX_AGE = 30 * 24 * 3600


def _cookie_value(phrase: str) -> str:
    return hashlib.sha256(f"twb-gate:{phrase}".encode()).hexdigest()


def _page(next_path: str, *, rejected: bool) -> str:
    note = '<p class="note">Not accepted.</p>' if rejected else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Private preview</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;font:16px system-ui,sans-serif;
  background:#f4f5f7;color:#1f2937}}
form{{display:flex;flex-direction:column;gap:12px;width:min(320px,90vw)}}
input{{font:inherit;padding:10px 12px;border:1px solid #cbd5e1;border-radius:8px;
  -webkit-text-security:disc;text-security:disc}}
button{{font:inherit;padding:10px 12px;border:0;border-radius:8px;background:#1f2937;color:#fff;
  cursor:pointer}}
.note{{margin:0;color:#b91c1c}}
</style></head><body>
<form method="post" action="{ENTER_PATH}">
<h1 style="margin:0;font-size:20px">Private preview</h1>{note}
<input type="text" name="k" aria-label="Access key" autocomplete="off" autocapitalize="off"
  spellcheck="false" autofocus required>
<input type="hidden" name="n" value="{escape(next_path)}">
<button type="submit">Continue</button>
</form></body></html>"""


def _safe_next(value: str) -> str:
    return value if value.startswith("/") and not value.startswith(("//", "/\\")) else "/"


class GateMiddleware:
    def __init__(self, app: ASGIApp, *, phrase: str) -> None:
        self.app = app
        self.phrase = phrase
        self.cookie = _cookie_value(phrase)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        cookies = cookie_parser(headers.get("cookie", ""))
        if hmac.compare_digest(cookies.get(COOKIE, ""), self.cookie):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["path"] == ENTER_PATH and scope["method"] == "POST":
            response = await self._enter(scope, receive, headers)
        else:
            query = scope.get("query_string", b"").decode("latin-1")
            next_path = scope["path"] + (f"?{query}" if query else "")
            response = self._closed(next_path, rejected=False)
        await response(scope, receive, send)

    async def _enter(self, scope: Scope, receive: Receive, headers: Headers) -> Response:
        body = b""
        more = True
        while more and len(body) <= MAX_FORM_BYTES:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        form = parse_qs(body[:MAX_FORM_BYTES].decode("utf-8", "replace"))
        given = (form.get("k") or [""])[0]
        next_path = _safe_next((form.get("n") or ["/"])[0])
        if not hmac.compare_digest(given.encode(), self.phrase.encode()):
            await asyncio.sleep(1)  # slows guessing
            return self._closed(next_path, rejected=True)
        response = RedirectResponse(next_path, status_code=303)
        secure = headers.get("x-forwarded-proto", scope.get("scheme")) == "https"
        response.set_cookie(
            COOKIE,
            self.cookie,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=secure,
            samesite="lax",
        )
        return response

    @staticmethod
    def _closed(next_path: str, *, rejected: bool) -> Response:
        return HTMLResponse(
            _page(next_path, rejected=rejected),
            status_code=401,
            headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
        )
