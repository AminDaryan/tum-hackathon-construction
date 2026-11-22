"""User accounts and their roles (ADR 0015, ``docs/api/rest-api.md``, "Users and roles").

A user signs in with a personal access token. Only the token's SHA-256 digest is stored, with
its last four characters as a hint; the token itself is shown once, when it is issued.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.models.base import FrozenModel


class Role(StrEnum):
    """What a user may do. Each role includes everything the roles below it may do."""

    ADMIN = "admin"  # everything, and the user accounts
    REVIEWER = "reviewer"  # upload, validate, review and correct
    VIEWER = "viewer"  # read only

    @property
    def rank(self) -> int:
        return _RANKS[self]

    def includes(self, other: Role) -> bool:
        return self.rank >= other.rank


_RANKS = {Role.VIEWER: 0, Role.REVIEWER: 1, Role.ADMIN: 2}


# The profile fields a user may change themselves (``PATCH /me``); the role and the active flag
# are an administrator's.
PROFILE_FIELDS = ("first_name", "last_name", "email", "job_title", "phone")


class User(FrozenModel):
    user_id: str
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(default="", max_length=80)
    email: str = Field(default="", max_length=254)
    job_title: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=40)
    role: Role
    active: bool = True
    created_at: datetime
    token_digest: str | None = None  # hex SHA-256 of the access token; never sent to clients
    token_hint: str | None = None  # the token's last four characters
    token_issued_at: datetime | None = None

    @property
    def name(self) -> str:
        """The full name: first and last name."""
        return f"{self.first_name} {self.last_name}".strip()


IdentityKind = Literal["local", "service", "user"]


class Identity(FrozenModel):
    """Who a request acts for.

    ``local``: no sign-in is configured and the request names no user, so it acts as the local
    administrator. ``service``: one of the configured ``TWB_AUTH__TOKENS``, which keep full
    access. ``user``: a user account.
    """

    kind: IdentityKind
    name: str
    role: Role
    user_id: str | None = None
    email: str = ""

    @property
    def actor(self) -> str:
        """The audit actor: the user's name, or ``local`` and ``service`` for the others."""
        return self.name if self.kind == "user" else self.kind


LOCAL = Identity(kind="local", name="Local administrator", role=Role.ADMIN)
SERVICE = Identity(kind="service", name="Administrator (configured token)", role=Role.ADMIN)
