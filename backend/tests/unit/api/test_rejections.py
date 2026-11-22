"""Every rejection uses the error envelope: wrong hosts and refused CORS preflight requests
included, with the same checks as before."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette

from app.api.middleware import MAX_ECHOED_CHARS, HostCheckMiddleware
from tests.unit.api.conftest import MakeClient

API = "/api/v1"
OWN = "http://localhost:5173"
PREFLIGHT = {"Access-Control-Request-Method": "POST"}


def _envelope(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    error = response.json()["error"]
    assert error["code"] == code and error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error  # type: ignore[no-any-return]


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "", "127.0.0.2"])
def test_a_wrong_host_gets_the_envelope(make_client: MakeClient, host: str) -> None:
    client = make_client()
    for path in (f"{API}/health", f"{API}/no-such-route", "/openapi.json"):
        error = _envelope(client.get(path, headers={"Host": host}), 400, "host_not_allowed")
        assert error["details"] == {"host": host}


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000"])
def test_allowed_hosts_pass(make_client: MakeClient, host: str) -> None:
    assert make_client().get(f"{API}/health", headers={"Host": host}).status_code == 200


def test_host_patterns(make_client: MakeClient) -> None:
    client = make_client(allowed_hosts=["*.example.org"])
    assert client.get(f"{API}/health", headers={"Host": "a.example.org"}).status_code == 200
    for host in ("example.org", "a.example.org.evil", "localhost"):
        _envelope(client.get(f"{API}/health", headers={"Host": host}), 400, "host_not_allowed")
    anyone = make_client(allowed_hosts=["*"])
    assert anyone.get(f"{API}/health", headers={"Host": "anything"}).status_code == 200


@pytest.mark.parametrize("pattern", ["exa*mple.org", "*example.org", "*.*.org"])
def test_misplaced_wildcards_are_a_configuration_error(pattern: str) -> None:
    with pytest.raises(ValueError, match="Invalid allowed host"):
        HostCheckMiddleware(Starlette(), allowed_hosts=[pattern])


def test_a_preflight_from_a_foreign_origin_gets_the_envelope(make_client: MakeClient) -> None:
    client = make_client()
    headers = {"Origin": "http://evil.example", **PREFLIGHT}
    response = client.options(f"{API}/documents", headers=headers)
    error = _envelope(response, 400, "origin_not_allowed")
    assert error["details"] == {"origin": "http://evil.example", "rejected": ["origin"]}
    assert "access-control-allow-origin" not in response.headers


def test_a_preflight_with_a_refused_method_gets_the_envelope(make_client: MakeClient) -> None:
    headers = {"Origin": OWN, "Access-Control-Request-Method": "TRACE"}
    response = make_client().options(f"{API}/documents", headers=headers)
    error = _envelope(response, 400, "preflight_rejected")
    assert error["details"]["rejected"] == ["method"]


def test_an_allowed_preflight_is_unchanged(make_client: MakeClient) -> None:
    response = make_client().options(f"{API}/documents", headers={"Origin": OWN, **PREFLIGHT})
    assert response.status_code == 200 and response.text == "OK"
    assert response.headers["access-control-allow-origin"] == OWN
    assert "POST" in response.headers["access-control-allow-methods"]


def test_simple_cross_origin_requests_are_unchanged(make_client: MakeClient) -> None:
    client = make_client()
    own = client.get(f"{API}/health", headers={"Origin": OWN})
    assert own.headers["access-control-allow-origin"] == OWN
    foreign = client.get(f"{API}/health", headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 200 and "access-control-allow-origin" not in foreign.headers


def test_echoed_header_values_are_cut(make_client: MakeClient) -> None:
    """Every rejection that quotes a refused header back cuts it to MAX_ECHOED_CHARS
    characters: the host check, the CORS preflight and the CSRF origin check alike."""
    client = make_client()
    origin = "http://" + "a" * 2000 + ".example"
    host = client.get(f"{API}/health", headers={"Host": "a" * 2000 + ".example"})
    preflight = client.options(f"{API}/documents", headers={"Origin": origin, **PREFLIGHT})
    csrf = client.post(f"{API}/documents", headers={"Origin": origin})
    echoed = [
        _envelope(host, 400, "host_not_allowed")["details"]["host"],
        _envelope(preflight, 400, "origin_not_allowed")["details"]["origin"],
        _envelope(csrf, 403, "origin_not_allowed")["details"]["origin"],
    ]
    assert [len(value) for value in echoed] == [MAX_ECHOED_CHARS] * 3


def test_refusals_quote_back_at_most_the_echo_limit(make_client: MakeClient) -> None:
    # A header value quoted back in error details is cut to MAX_ECHOED_CHARS, whichever check
    # refused it: the host check, a refused preflight and the CSRF check of a state change.
    client = make_client()
    long_host = "a" * 600 + ".example"
    host = _envelope(client.get(f"{API}/health", headers={"Host": long_host}), 400,
                     "host_not_allowed")  # fmt: skip
    assert host["details"] == {"host": long_host[:MAX_ECHOED_CHARS]}
    long_origin = f"http://{long_host}"
    cut = long_origin[:MAX_ECHOED_CHARS]
    preflight = client.options(f"{API}/documents", headers={"Origin": long_origin, **PREFLIGHT})
    assert _envelope(preflight, 400, "origin_not_allowed")["details"]["origin"] == cut
    for method in ("post", "put", "patch", "delete"):
        response = client.request(method, f"{API}/documents", headers={"Origin": long_origin})
        assert _envelope(response, 403, "origin_not_allowed")["details"] == {"origin": cut}


def test_a_cross_site_state_change_without_an_origin_carries_no_details(
    make_client: MakeClient,
) -> None:
    response = make_client().post(f"{API}/documents", headers={"Sec-Fetch-Site": "cross-site"})
    assert _envelope(response, 403, "origin_not_allowed")["details"] == {}


def test_the_documented_headers_are_exposed(make_client: MakeClient) -> None:
    response = make_client().get(f"{API}/health", headers={"Origin": OWN})
    exposed = {h.strip() for h in response.headers["access-control-expose-headers"].split(",")}
    assert exposed == {"X-Request-ID", "Content-Disposition", "Location", "Preference-Applied"}
