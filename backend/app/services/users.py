"""User accounts: create, change, delete, and issue personal access tokens (ADR 0015).

A token is ``twb_`` and 43 URL-safe characters (32 random bytes). Only its SHA-256 digest and
its last four characters are stored; the token is returned once, when it is issued. Issuing a
new one replaces the old, which stops working at once.

An administrator cannot demote, deactivate or delete their own account, so a signed-in
administrator never locks themselves out by mistake. The configured ``TWB_AUTH__TOKENS`` (and,
without sign-in, the local administrator) keep full access whatever the user accounts say.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from typing import Any

from app.core.errors import ConflictError, NotFoundError
from app.models.audit import AuditAction, EntityType
from app.models.user import PROFILE_FIELDS, Identity, Role, User
from app.repositories.base import UnitOfWork
from app.services import identity
from app.services.workbench import Workbench

TOKEN_PREFIX = "twb_"  # noqa: S105 - the visible prefix of every user token


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def _summary(user: User) -> dict[str, Any]:
    """What the audit trail keeps of an account (never the token or its digest)."""
    return {
        **{field: getattr(user, field) for field in PROFILE_FIELDS},
        "role": user.role.value,
        "active": user.active,
    }


def load(uow: UnitOfWork, user_id: str) -> User:
    user = uow.users.get(user_id)
    if user is None:
        raise NotFoundError(f"Unknown user {user_id!r}.")
    return user


def list_users(wb: Workbench) -> list[User]:
    with wb.uow() as uow:
        return uow.users.list()


def _with_token(wb: Workbench, user: User) -> tuple[User, str]:
    token = _new_token()
    issued = user.model_copy(
        update={
            "token_digest": token_digest(token),
            "token_hint": token[-4:],
            "token_issued_at": wb.clock.now(),
        }
    )
    return issued, token


def create(wb: Workbench, *, role: Role, profile: Mapping[str, str]) -> tuple[User, str]:
    """A new, active account and its first token (returned once). ``profile``: the
    :data:`~app.models.user.PROFILE_FIELDS` (``first_name`` is required)."""
    user = User.model_validate(
        {**profile, "user_id": wb.ids.new("usr"), "role": role, "created_at": wb.clock.now()}
    )
    user, token = _with_token(wb, user)
    with wb.uow() as uow:
        uow.users.add(user)
        wb.audit(
            uow,
            AuditAction.USER_CREATED,
            EntityType.USER,
            user.user_id,
            f"Created the account of {user.name} ({user.role.value})",
            after=_summary(user),
        )
    return user, token


def _check_not_self(user: User, what: str) -> None:
    acting: Identity = identity.current()
    if acting.kind == "user" and acting.user_id == user.user_id:
        raise ConflictError(f"You cannot {what} your own account.")


def update(
    wb: Workbench,
    user_id: str,
    *,
    profile: Mapping[str, str | None] | None = None,
    role: Role | None = None,
    active: bool | None = None,
) -> User:
    """Changes an account (an administrator's change; see :func:`update_own_profile`)."""
    profile = profile or {}
    unknown = set(profile) - set(PROFILE_FIELDS)
    if unknown:  # pragma: no cover - the routes pass only profile fields
        raise ValueError(f"Not profile fields: {sorted(unknown)}")
    with wb.uow() as uow:
        user = load(uow, user_id)
        if role is not None and role != user.role:
            _check_not_self(user, "change the role of")
        if active is False and user.active:
            _check_not_self(user, "deactivate")
        changes: dict[str, Any] = {
            key: value
            for key, value in {**profile, "role": role, "active": active}.items()
            if value is not None
        }
        changed = User.model_validate({**user.model_dump(), **changes})
        if changed == user:
            return user
        uow.users.update(changed)
        wb.audit(
            uow,
            AuditAction.USER_UPDATED,
            EntityType.USER,
            user.user_id,
            f"Changed the account of {changed.name}",
            before=_summary(user),
            after=_summary(changed),
        )
        return changed


def update_own_profile(wb: Workbench, profile: Mapping[str, str | None]) -> User:
    """The signed-in user changes their own profile fields (any role may)."""
    acting = identity.current()
    if acting.kind != "user" or acting.user_id is None:
        raise ConflictError(
            "Only a user account has a profile to change; sign in with a personal access token."
        )
    return update(wb, acting.user_id, profile=profile)


def delete(wb: Workbench, user_id: str) -> None:
    with wb.uow() as uow:
        user = load(uow, user_id)
        _check_not_self(user, "delete")
        uow.users.delete(user_id)
        wb.audit(
            uow,
            AuditAction.USER_DELETED,
            EntityType.USER,
            user.user_id,
            f"Deleted the account of {user.name}",
            before=_summary(user),
        )


def issue_token(wb: Workbench, user_id: str) -> tuple[User, str]:
    """A new token for the account; the previous one stops working."""
    with wb.uow() as uow:
        user, token = _with_token(wb, load(uow, user_id))
        uow.users.update(user)
        wb.audit(
            uow,
            AuditAction.USER_TOKEN_ISSUED,
            EntityType.USER,
            user.user_id,
            f"Issued a new access token for {user.name}",
            context={"token_hint": user.token_hint},
        )
    return user, token


def signed_in_user(wb: Workbench, token: str) -> User | None:
    """The active account whose token this is, or ``None``."""
    if not token.startswith(TOKEN_PREFIX):  # not a user token: no lookup
        return None
    with wb.uow() as uow:
        user = uow.users.by_token_digest(token_digest(token))
    return user if user is not None and user.active else None


def identity_of(user: User) -> Identity:
    return Identity(
        kind="user", name=user.name, role=user.role, user_id=user.user_id, email=user.email
    )


def signed_in_identity(wb: Workbench, token: str) -> Identity | None:
    """What the sign-in middleware calls for a bearer token that is not a configured one."""
    user = signed_in_user(wb, token)
    return None if user is None else identity_of(user)
