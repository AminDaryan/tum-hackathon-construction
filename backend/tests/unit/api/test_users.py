"""User accounts and roles (ADR 0015): ``/me``, ``/users``, the role check of every route, the
audit actor, and tokens (shown once, replaced on reissue, refused once deactivated)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.auth import required_role
from app.models.audit import EntityType
from app.models.user import Role
from tests.unit.api.conftest import MakeClient

API = "/api/v1"
CONFIGURED = "configured-token-5Kp1"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create(client: TestClient, name: str, role: str, **headers: Any) -> dict[str, Any]:
    response = client.post(
        f"{API}/users",
        json={"first_name": name, "email": f"{name.lower()}@example.test", "role": role},
        headers=headers.get("headers"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _forbidden(response: Any, role: str, needed: str) -> None:
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == "forbidden"
    assert error["details"] == {"role": role, "required_role": needed}


def test_without_sign_in_the_local_administrator_acts(make_client: MakeClient) -> None:
    me = make_client().get(f"{API}/me").json()
    assert me == {
        "kind": "local",
        "name": "Local administrator",
        "email": "",
        "role": "admin",
        "user_id": None,
        "auth_required": False,
        "permissions": ["read", "write", "manage_users"],
        "account": None,
    }


def test_an_administrator_creates_accounts_and_the_token_is_shown_once(
    make_client: MakeClient,
) -> None:
    client = make_client()
    issued = _create(client, "Anna", "reviewer")
    token, user = issued["token"], issued["user"]
    assert token.startswith("twb_") and len(token) == 47
    assert user["role"] == "reviewer" and user["active"] is True
    assert user["token_hint"] == token[-4:] and user["email"] == "anna@example.test"
    listed = client.get(f"{API}/users").json()
    assert listed == [user]
    assert token not in client.get(f"{API}/users").text
    assert "digest" not in client.get(f"{API}/users").text
    me = client.get(f"{API}/me", headers=_bearer(token)).json()
    assert me["kind"] == "user" and me["name"] == "Anna" and me["user_id"] == user["user_id"]
    assert me["role"] == "reviewer" and me["permissions"] == ["read", "write"]
    assert me["account"] == user


def test_roles_decide_what_a_user_may_do(make_client: MakeClient) -> None:
    client = make_client()
    viewer = _bearer(_create(client, "Vera", "viewer")["token"])
    reviewer = _bearer(_create(client, "Rolf", "reviewer")["token"])

    assert client.get(f"{API}/documents", headers=viewer).status_code == 200
    assert client.get(f"{API}/projects", headers=viewer).status_code == 200
    _forbidden(
        client.post(f"{API}/projects", json={"name": "P"}, headers=viewer), "viewer", "reviewer"
    )
    _forbidden(client.get(f"{API}/users", headers=viewer), "viewer", "admin")

    assert client.post(f"{API}/projects", json={"name": "P"}, headers=reviewer).status_code == 201
    _forbidden(client.get(f"{API}/users", headers=reviewer), "reviewer", "admin")
    _forbidden(
        client.post(f"{API}/users", json={"first_name": "X"}, headers=reviewer),
        "reviewer",
        "admin",
    )
    assert client.get(f"{API}/me", headers=viewer).json()["role"] == "viewer"


def test_every_write_needs_a_reviewer_and_every_read_a_viewer() -> None:
    assert required_role("GET", f"{API}/documents", API) is Role.VIEWER
    assert required_role("HEAD", f"{API}/documents/doc_1/original", API) is Role.VIEWER
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert required_role(method, f"{API}/issues/iss_1/review", API) is Role.REVIEWER
    for method in ("GET", "POST", "PATCH", "DELETE"):
        assert required_role(method, f"{API}/users", API) is Role.ADMIN
        assert required_role(method, f"{API}/users/usr_1/token", API) is Role.ADMIN
    assert required_role("GET", f"{API}/me/", API) is Role.VIEWER
    assert required_role("GET", f"{API}/usersx", API) is Role.VIEWER  # not the users resource


def test_the_audit_trail_names_the_user(make_client: MakeClient) -> None:
    client = make_client()
    ada = _create(client, "Ada", "admin")
    created = _create(client, "Bert", "viewer", headers=_bearer(ada["token"]))
    wb = client.app.state.workbench  # type: ignore[attr-defined]
    with wb.uow() as uow:
        [event] = uow.audit.list_for_entity(EntityType.USER, created["user"]["user_id"])
        [local] = uow.audit.list_for_entity(EntityType.USER, ada["user"]["user_id"])
    assert event.actor == "Ada" and event.context == {"actor_id": ada["user"]["user_id"]}
    assert event.after == {
        "first_name": "Bert",
        "last_name": "",
        "email": "bert@example.test",
        "job_title": "",
        "phone": "",
        "role": "viewer",
        "active": True,
    }
    assert local.actor == "local" and local.context == {}


def test_an_administrator_cannot_lock_themselves_out(make_client: MakeClient) -> None:
    client = make_client()
    ada = _create(client, "Ada", "admin")
    headers, user_id = _bearer(ada["token"]), ada["user"]["user_id"]
    for body in ({"role": "reviewer"}, {"active": False}):
        response = client.patch(f"{API}/users/{user_id}", json=body, headers=headers)
        assert response.status_code == 409 and response.json()["error"]["code"] == "conflict"
    assert client.delete(f"{API}/users/{user_id}", headers=headers).status_code == 409
    renamed = client.patch(f"{API}/users/{user_id}", json={"last_name": "L."}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ada L."
    # another administrator (here the local one) may
    assert (
        client.patch(f"{API}/users/{user_id}", json={"role": "viewer"}).json()["role"] == "viewer"
    )
    assert client.delete(f"{API}/users/{user_id}").json() == []


def test_with_sign_in_required(make_client: MakeClient) -> None:
    client = make_client(auth={"tokens": [CONFIGURED]})
    assert client.get(f"{API}/me").status_code == 401
    service = _bearer(CONFIGURED)
    me = client.get(f"{API}/me", headers=service).json()
    assert me["kind"] == "service" and me["role"] == "admin" and me["auth_required"] is True
    issued = _create(client, "Anna", "reviewer", headers=service)
    anna, user_id = _bearer(issued["token"]), issued["user"]["user_id"]
    assert client.get(f"{API}/me", headers=anna).json()["name"] == "Anna"

    reissued = client.post(f"{API}/users/{user_id}/token", headers=service).json()
    assert reissued["token"] != issued["token"]
    assert reissued["user"]["token_hint"] == reissued["token"][-4:]
    assert client.get(f"{API}/me", headers=anna).status_code == 401  # the old token stops
    anna = _bearer(reissued["token"])
    assert client.get(f"{API}/me", headers=anna).status_code == 200

    off = client.patch(f"{API}/users/{user_id}", json={"active": False}, headers=service)
    assert off.json()["active"] is False
    assert client.get(f"{API}/me", headers=anna).status_code == 401
    client.patch(f"{API}/users/{user_id}", json={"active": True}, headers=service)
    assert client.get(f"{API}/me", headers=anna).status_code == 200


def test_without_sign_in_an_unknown_or_deactivated_token_changes_nothing(
    make_client: MakeClient,
) -> None:
    client = make_client()
    issued = _create(client, "Vera", "viewer")
    client.patch(f"{API}/users/{issued['user']['user_id']}", json={"active": False})
    for token in (issued["token"], "twb_unknown", "anything"):
        assert client.get(f"{API}/me", headers=_bearer(token)).json()["kind"] == "local"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"first_name": ""},
        {"first_name": "   "},
        {"first_name": "A", "email": "not an email"},
        {"first_name": "A", "phone": "call me"},
        {"first_name": "A", "role": "owner"},
    ],
)
def test_invalid_accounts_are_refused(make_client: MakeClient, body: dict[str, Any]) -> None:
    response = make_client().post(f"{API}/users", json=body)
    assert response.status_code == 422, response.text


def test_unknown_accounts(make_client: MakeClient) -> None:
    client = make_client()
    assert client.patch(f"{API}/users/usr_x", json={"first_name": "A"}).status_code == 404
    assert client.delete(f"{API}/users/usr_x").status_code == 404
    assert client.post(f"{API}/users/usr_x/token").status_code == 404


def test_issued_tokens_never_reach_the_logs(
    make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="app")
    client = make_client()
    token = _create(client, "Anna", "reviewer")["token"]
    client.get(f"{API}/me", headers=_bearer(token))
    assert token not in caplog.text


def test_a_user_edits_their_own_profile_but_not_their_role(make_client: MakeClient) -> None:
    client = make_client()
    issued = _create(client, "Vera", "viewer")
    vera, user_id = _bearer(issued["token"]), issued["user"]["user_id"]
    body = {
        "first_name": " Vera ",
        "last_name": "Kühn",
        "email": "vera@example.test",
        "job_title": "Quantity surveyor",
        "phone": "+49 30 1234-56",
    }
    me = client.patch(f"{API}/me", json=body, headers=vera)
    assert me.status_code == 200, me.text  # a viewer may change their own profile
    account = me.json()["account"]
    assert me.json()["name"] == account["name"] == "Vera Kühn"
    assert account["first_name"] == "Vera" and account["job_title"] == "Quantity surveyor"
    assert account["phone"] == "+49 30 1234-56" and account["role"] == "viewer"
    ignored = client.patch(f"{API}/me", json={"role": "admin", "active": False}, headers=vera)
    assert ignored.status_code == 200 and ignored.json()["role"] == "viewer"
    assert ignored.json()["account"]["active"] is True
    partial = client.patch(f"{API}/me", json={"job_title": ""}, headers=vera).json()["account"]
    assert partial["job_title"] == "" and partial["last_name"] == "Kühn"
    assert client.patch(f"{API}/me", json={"phone": "x"}, headers=vera).status_code == 422
    wb = client.app.state.workbench  # type: ignore[attr-defined]
    with wb.uow() as uow:
        events = uow.audit.list_for_entity(EntityType.USER, user_id)
    # each entry names the actor as they were when they acted
    assert [event.actor for event in events] == ["local", "Vera", "Vera Kühn"]


def test_only_a_user_account_has_a_profile_to_change(make_client: MakeClient) -> None:
    response = make_client().patch(f"{API}/me", json={"first_name": "Me"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "conflict"
