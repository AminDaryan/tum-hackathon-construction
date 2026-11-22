"""Optional sign-in (contract K4): with tokens set, every ``/api/v1`` route except
``GET /api/v1/health`` needs a valid bearer token; without tokens nothing changes."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.auth import check_tokens
from app.core.config import AuthSettings, Settings
from app.main import create_app
from tests.unit.api.conftest import MakeClient, make_workbench

API = "/api/v1"
TOKENS = ["token-a-7Hq2", "token-b-9Zx4"]


def _routes(client: TestClient) -> list[tuple[str, str]]:
    """(method, path) of every API operation, path parameters filled in."""
    paths = client.get("/openapi.json").json()["paths"]
    return [
        (method.upper(), re.sub(r"\{[^}]+\}", "x", path))
        for path, item in paths.items()
        if path.startswith(API)
        for method in item
    ]


def _unauthorized(response: Any) -> None:
    assert response.status_code == 401, response.text
    assert response.headers["WWW-Authenticate"] == "Bearer"
    error = response.json()["error"]
    assert error["code"] == "unauthorized" and error["details"] == {}
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_every_api_route_is_protected(make_client: MakeClient) -> None:
    client = make_client(auth={"tokens": TOKENS})
    routes = _routes(client)
    assert len(routes) >= 17
    for method, path in routes:
        if (method, path) == ("GET", f"{API}/health"):
            continue
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic eA=="}):
            _unauthorized(client.request(method, path, headers=headers))


def test_health_and_the_docs_stay_open(make_client: MakeClient) -> None:
    client = make_client(auth={"tokens": TOKENS})
    health = client.get(f"{API}/health")
    assert health.status_code == 200 and health.json()["auth_required"] is True  # contract K2
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
    _unauthorized(client.post(f"{API}/health"))  # only GET is open


@pytest.mark.parametrize("header", [f"Bearer {TOKENS[0]}", f"bearer  {TOKENS[1]} "])
def test_a_valid_token_passes(make_client: MakeClient, header: str) -> None:
    client = make_client(auth={"tokens": TOKENS})
    response = client.get(f"{API}/documents", headers={"Authorization": header})
    assert response.status_code == 200 and response.json()["total"] == 0
    missing = client.get(f"{API}/documents/doc_x", headers={"Authorization": header})
    assert missing.status_code == 404  # authenticated, then the route answers


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", TOKENS[0], f"Token {TOKENS[0]}"])
def test_malformed_credentials_are_rejected(make_client: MakeClient, header: str) -> None:
    client = make_client(auth={"tokens": TOKENS})
    _unauthorized(client.get(f"{API}/documents", headers={"Authorization": header}))


def test_without_tokens_nothing_changes(make_client: MakeClient) -> None:
    client = make_client()
    for method, path in _routes(client):
        response = client.request(method, path, headers={"Authorization": "Bearer anything"})
        assert response.status_code != 401, (method, path)
    spec = client.get("/openapi.json").json()
    assert "securitySchemes" not in spec.get("components", {})


def test_the_docs_declare_the_scheme_when_sign_in_is_required(make_client: MakeClient) -> None:
    spec = make_client(auth={"tokens": TOKENS}).get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["bearer"] == {"type": "http", "scheme": "bearer"}
    assert "security" not in spec["paths"][f"{API}/health"]["get"]
    assert spec["paths"][f"{API}/documents"]["post"]["security"] == [{"bearer": []}]


def test_a_preflight_needs_no_token(make_client: MakeClient) -> None:
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    response = make_client(auth={"tokens": TOKENS}).options(f"{API}/documents", headers=headers)
    assert response.status_code == 200


def test_tokens_never_reach_the_logs(
    make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="app")
    client = make_client(auth={"tokens": TOKENS})
    client.get(f"{API}/documents", headers={"Authorization": f"Bearer {TOKENS[0]}"})
    client.get(f"{API}/documents", headers={"Authorization": "Bearer guessed-token"})
    assert [record.status for record in caplog.records if hasattr(record, "status")] == [200, 401]
    for secret in (*TOKENS, "guessed-token"):
        assert secret not in caplog.text
    assert TOKENS[0] not in repr(Settings(auth={"tokens": TOKENS}))  # type: ignore[arg-type]


def test_token_settings(monkeypatch: pytest.MonkeyPatch, make_client: MakeClient) -> None:
    assert AuthSettings().required is False
    monkeypatch.setenv("TWB_AUTH__TOKENS", f'["{TOKENS[0]}"]')
    auth = Settings().auth
    assert auth.required and [t.get_secret_value() for t in auth.tokens] == [TOKENS[0]]
    for bad in ("", "with space", "tab\there", "umlaut-ä"):
        with pytest.raises(ValueError, match="token 2 is empty or has spaces") as raised:
            check_tokens([TOKENS[0], bad])
        assert TOKENS[0] not in str(raised.value) and (not bad or bad not in str(raised.value))
    with pytest.raises(ValueError, match="token 1"):
        make_client(auth={"tokens": ["with space"]})


@pytest.mark.parametrize("raw", ['"{t}"', '{{"a": "{t}"}}', '[["{t}"]]', '[{{"a": "{t}"}}]'])
def test_a_malformed_token_setting_does_not_echo_the_token(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A token given as a JSON string, an object or a nested list fails validation; the error
    goes to the startup traceback and the process log, so it must not repeat the input."""
    monkeypatch.setenv("TWB_AUTH__TOKENS", raw.format(t=TOKENS[0]))
    with pytest.raises(ValueError, match=r"auth\.tokens") as raised:
        Settings()
    assert TOKENS[0] not in str(raised.value)
    assert TOKENS[0] not in repr(raised.value)


def test_a_token_that_cannot_be_sent_fails_when_the_app_is_created(tmp_path: Path) -> None:
    """``uvicorn --factory`` creates the app at start. The middleware stack is only built for the
    first request, and uvicorn's default lifespan mode swallows a failure there and serves 500s."""
    with pytest.raises(ValueError, match="token 1"):
        create_app(workbench=make_workbench(tmp_path, auth={"tokens": ["with space"]}))


def test_a_root_path_does_not_open_the_api(tmp_path: Path) -> None:
    """Behind a proxy (``uvicorn --root-path /twb``) the server puts the root path in front of
    every path and the router strips it again; the sign-in check must see the same path."""
    app = create_app(workbench=make_workbench(tmp_path, auth={"tokens": TOKENS}))
    with TestClient(app, base_url="http://localhost", root_path="/twb") as client:
        _unauthorized(client.get("/twb/api/v1/documents"))
        _unauthorized(client.post("/twb/api/v1/datasets/x/validation-runs"))
        signed_in = {"Authorization": f"Bearer {TOKENS[0]}"}
        assert client.get("/twb/api/v1/documents", headers=signed_in).status_code == 200
        assert client.get("/twb/api/v1/health").status_code == 200
