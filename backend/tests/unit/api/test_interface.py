"""The built web interface (contract K6): served at ``/`` with correct media types and
client-side routes, without ever shadowing the API or skipping the host and origin checks."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.unit.api.conftest import MakeClient, make_workbench

API = "/api/v1"
INDEX = b"<!doctype html><title>Workbench</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_bytes(INDEX)
    # Bytes, so that the served text is the same on Windows (write_text would write "\r\n").
    (root / "assets" / "app-1a2b.js").write_bytes(b"console.log('ok');\n")
    (root / "assets" / "app-1a2b.css").write_bytes(b"body{margin:0}\n")
    (root / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (root / "api" / "v1").mkdir(parents=True)  # a build must never shadow the API
    (root / "api" / "v1" / "health").write_text("shadowed")
    (root / "api" / "v1" / "secret.json").write_text("{}")
    (root / ".env").write_text("TOKEN=hidden")  # hidden files are never served
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]")
    (root / "assets" / ".cache").mkdir()
    (root / "assets" / ".cache" / "app-1a2b.js").write_text("hidden();")
    (tmp_path / "outside.txt").write_text("not part of the build")
    return root


@pytest.fixture
def client(make_client: MakeClient, dist: Path) -> TestClient:
    return make_client(frontend_dist_dir=dist)


def _json_404(response: object) -> None:
    assert response.status_code == 404  # type: ignore[attr-defined]
    assert response.headers["content-type"] == "application/json"  # type: ignore[attr-defined]
    assert response.json()["error"]["code"] == "not_found"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("path", "media_type"),
    [
        ("/assets/app-1a2b.js", "text/javascript; charset=utf-8"),
        ("/assets/app-1a2b.css", "text/css; charset=utf-8"),
        ("/favicon.svg", "image/svg+xml"),
        ("/index.html", "text/html; charset=utf-8"),
    ],
)
def test_files_have_their_media_types(client: TestClient, path: str, media_type: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == media_type
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.head(path).status_code == 200


@pytest.mark.parametrize(
    "path", ["/", "/index.html", "/documents/doc_000001", "/assets/app-1a2b.js", "/favicon.svg"]
)
def test_no_other_site_can_frame_the_interface(client: TestClient, path: str) -> None:
    """Clickjacking: a review decision or a run is one click away, so the interface refuses
    to be shown in a frame (the modern header and the one older browsers know)."""
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("path", ["/", "/documents", "/documents/doc_000001/issues", "/x/y/z"])
def test_client_side_routes_get_the_index(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200 and response.content == INDEX
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    ("path", "cache_control"),
    [
        ("/assets/app-1a2b.js", None),  # content-hashed: a new build gives it a new name
        ("/favicon.svg", "no-cache"),  # a fixed address: revalidated, so a rebuild shows
        ("/index.html", "no-cache"),
    ],
)
def test_only_hashed_assets_may_be_cached_without_asking(
    client: TestClient, path: str, cache_control: str | None
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers.get("cache-control") == cache_control
    revalidated = client.get(path, headers={"If-None-Match": response.headers["etag"]})
    assert revalidated.status_code == 304  # cheap: unchanged files are not sent again


def test_the_api_is_never_shadowed(client: TestClient) -> None:
    health = client.get(f"{API}/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    for path in (f"{API}/secret.json", f"{API}/nope", "/api", "/api/v2/documents"):
        _json_404(client.get(path))
    not_allowed = client.delete(f"{API}/documents")
    assert not_allowed.status_code == 405
    assert not_allowed.json()["error"]["code"] == "method_not_allowed"
    assert client.get("/openapi.json").json()["info"]["title"]
    assert client.get("/docs").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "http://localhost//api/v1/secret.json",  # a full URL: "//api/..." alone names a host
        "http://localhost//api/v1/health",
        "/%2e/api/v1/health",
        "/x/%2e%2e/api/v1/secret.json",
        "/assets/%2e%2e/api/v1/health",
    ],
)
def test_a_path_that_normalizes_into_the_api_is_never_served(client: TestClient, path: str) -> None:
    """The file lookup drops empty, ``.`` and ``..`` segments; the reserved prefixes apply to
    the path it looks up, so no file of the build answers under ``/api`` in any spelling."""
    _json_404(client.get(path))
    assert client.head(path).status_code == 404


@pytest.mark.parametrize(
    "path",
    ["/.env", "/%2Eenv", "/.git/config", "/.git/", "/assets/.cache/app-1a2b.js", "/x/%2e%2e/.env"],
)
def test_hidden_files_and_directories_are_never_served(client: TestClient, path: str) -> None:
    _json_404(client.get(path))
    assert client.head(path).status_code == 404


def test_missing_files_and_other_methods_get_the_json_404(client: TestClient) -> None:
    _json_404(client.get("/assets/missing-9z9z.js"))
    _json_404(client.post("/documents", headers={"Origin": "http://localhost:5173"}))
    _json_404(client.get("/%2e%2e/outside.txt"))  # outside the build directory


def test_the_host_and_origin_checks_still_apply(client: TestClient) -> None:
    wrong_host = client.get("/", headers={"Host": "evil.example"})
    assert wrong_host.status_code == 400
    assert wrong_host.json()["error"]["code"] == "host_not_allowed"
    cross = client.post("/documents", headers={"Origin": "http://evil.example"})
    assert cross.status_code == 403 and cross.json()["error"]["code"] == "origin_not_allowed"


def test_nothing_is_served_without_a_build(
    make_client: MakeClient, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _json_404(make_client().get("/"))
    empty = tmp_path / "empty"
    empty.mkdir()
    with caplog.at_level(logging.WARNING, logger="app"):
        client = make_client(frontend_dist_dir=empty)
    _json_404(client.get("/"))
    assert "no index.html" in caplog.text


def test_behind_a_root_path_the_api_is_not_shadowed(tmp_path: Path, dist: Path) -> None:
    """Behind a proxy (``uvicorn --root-path /twb``) every path starts with the root path."""
    app = create_app(workbench=make_workbench(tmp_path, frontend_dist_dir=dist))
    with TestClient(app, base_url="http://localhost", root_path="/twb") as client:
        for path in (
            "/twb/api",
            "/twb/api/v1/secret.json",
            "/twb/api/v1/nope",
            "/twb//api/v1/secret.json",
            "/twb/%2e/api/v1/health",
            "/twb/.env",
        ):
            _json_404(client.get(path))
        assert client.get("/twb/api/v1/health").json()["status"] == "ok"
        assert client.get("/twb/documents/doc_000001").content == INDEX
        script = client.get("/twb/assets/app-1a2b.js")
        assert script.headers["content-type"] == "text/javascript; charset=utf-8"


def test_the_gate_closes_every_path_until_the_phrase_is_given(
    make_client: MakeClient, dist: Path
) -> None:
    """A hosted preview: the interface, its files and the API all answer the gate page until the
    right phrase is posted; then the cookie opens them."""
    client = make_client(frontend_dist_dir=dist, gate_phrase="open-sesame")
    closed = ["/", "/assets/app-1a2b.js", "/favicon.svg", f"{API}/health", f"{API}/documents"]
    for path in closed:
        response = client.get(path)
        assert response.status_code == 401, path
        assert 'name="k"' in response.text
        assert "console.log" not in response.text
    assert client.post(f"{API}/documents", files={"file": ("a.csv", b"a\n1\n")}).status_code == 401

    wrong = client.post("/_enter", data={"k": "open", "n": "/favicon.svg"}, follow_redirects=False)
    assert wrong.status_code == 401
    assert "twb_k" not in client.cookies

    right = client.post(
        "/_enter", data={"k": "open-sesame", "n": "//evil.example"}, follow_redirects=False
    )
    assert right.status_code == 303
    assert right.headers["location"] == "/"  # never off-site
    assert client.get("/assets/app-1a2b.js").text == "console.log('ok');\n"
    assert client.get(f"{API}/health").status_code == 200
