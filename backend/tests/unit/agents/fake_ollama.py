"""A local stand-in for an Ollama server: answers ``GET /api/version`` and ``GET /api/tags``
with what a test sets, counts the requests, and listens on 127.0.0.1 only."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODEL = "example-model:7b"
DIGEST = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


@dataclass
class FakeOllama:
    base_url: str = ""
    prefix: str = ""  # a path the server is mounted under, as behind a reverse proxy
    version: Any = "0.9.0"
    models: Any = field(default_factory=lambda: [{"name": MODEL, "model": MODEL, "digest": DIGEST}])
    status: int = 200
    raw_body: bytes | None = None  # sent instead of JSON when set
    delay_seconds: float = 0.0
    paths: list[str] = field(default_factory=list)

    def answer(self, path: str) -> tuple[int, bytes]:
        self.paths.append(path)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.raw_body is not None:
            return self.status, self.raw_body
        route = path.removeprefix(self.prefix) if self.prefix else path
        if route == "/api/version":
            return self.status, json.dumps({"version": self.version}).encode()
        if route == "/api/tags":
            return self.status, json.dumps({"models": self.models}).encode()
        return 404, b'{"error": "not found"}'


@contextmanager
def fake_ollama(path_prefix: str = "") -> Iterator[FakeOllama]:
    fake = FakeOllama(prefix=path_prefix)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, body = fake.answer(self.path)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return  # keep the test output quiet

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    fake.base_url = f"http://127.0.0.1:{server.server_address[1]}{path_prefix}"
    thread = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def closed_port_url() -> str:
    """The URL of a port on 127.0.0.1 that nothing listens on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"
