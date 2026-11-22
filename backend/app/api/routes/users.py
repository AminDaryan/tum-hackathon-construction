"""Who is signed in (``/me``) and the user accounts (``/users``, administrators only; the role
check is in ``app.api.auth``)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.routes._deps import workbench
from app.models.user import PROFILE_FIELDS, IdentityKind, Role, User
from app.services import identity, users

router = APIRouter(tags=["users"])

EMAIL_PATTERN = r"^$|^[^@\s]+@[^@\s]+$"
PHONE_PATTERN = r"^[0-9+()./ -]*$"
PERMISSIONS = {
    Role.VIEWER: ["read"],
    Role.REVIEWER: ["read", "write"],
    Role.ADMIN: ["read", "write", "manage_users"],
}


class UserView(BaseModel):
    user_id: str
    name: str = Field(description="The full name: first and last name.")
    first_name: str
    last_name: str
    email: str
    job_title: str
    phone: str
    role: Role
    active: bool
    created_at: datetime
    token_hint: str | None = Field(description="The last four characters of the access token.")
    token_issued_at: datetime | None

    @classmethod
    def of(cls, user: User) -> UserView:
        return cls(
            user_id=user.user_id,
            name=user.name,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            job_title=user.job_title,
            phone=user.phone,
            role=user.role,
            active=user.active,
            created_at=user.created_at,
            token_hint=user.token_hint,
            token_issued_at=user.token_issued_at,
        )


class Me(BaseModel):
    kind: IdentityKind = Field(
        description="`user` (a user account), `service` (a configured TWB_AUTH__TOKENS token) "
        "or `local` (sign-in is off and the request names no user)."
    )
    name: str
    email: str
    role: Role
    user_id: str | None
    auth_required: bool = Field(description="Whether the API asks for a token.")
    permissions: list[str] = Field(description="`read`, `write` and `manage_users`, by role.")
    account: UserView | None = Field(
        description="The user's profile, for `kind` `user`; the others have none."
    )


class IssuedToken(BaseModel):
    user: UserView
    token: str = Field(description="The access token. Shown once: only its digest is stored.")


class ProfileChanges(BaseModel):
    """The fields a user may change in their own profile; a missing field stays as it is."""

    first_name: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    last_name: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)
    job_title: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40, pattern=PHONE_PATTERN)

    def stripped(self) -> dict[str, str | None]:
        return {
            field: None if value is None else value.strip()
            for field, value in self.model_dump(include=set(PROFILE_FIELDS)).items()
        }


class CreateUser(ProfileChanges):
    first_name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    role: Role = Role.REVIEWER


class ChangeUser(ProfileChanges):
    role: Role | None = None
    active: bool | None = None


def _me(request: Request) -> Me:
    acting = identity.current()
    account = None
    if acting.kind == "user" and acting.user_id is not None:
        with workbench(request).uow() as uow:
            user = uow.users.get(acting.user_id)
        account = None if user is None else UserView.of(user)
    return Me(
        kind=acting.kind,
        name=account.name if account else acting.name,
        email=account.email if account else acting.email,
        role=acting.role,
        user_id=acting.user_id,
        auth_required=workbench(request).settings.auth.required,
        permissions=PERMISSIONS[acting.role],
        account=account,
    )


@router.get("/me")
def me(request: Request) -> Me:
    return _me(request)


@router.patch("/me")
def change_my_profile(request: Request, body: ProfileChanges) -> Me:
    """Any signed-in user changes their own profile; role and status stay an administrator's."""
    users.update_own_profile(workbench(request), body.stripped())
    return _me(request)


@router.get("/users")
def list_users(request: Request) -> list[UserView]:
    return [UserView.of(user) for user in users.list_users(workbench(request))]


@router.post("/users", status_code=201)
def create_user(request: Request, body: CreateUser) -> IssuedToken:
    profile = {field: value or "" for field, value in body.stripped().items()}
    user, token = users.create(workbench(request), role=body.role, profile=profile)
    return IssuedToken(user=UserView.of(user), token=token)


@router.patch("/users/{user_id}")
def change_user(request: Request, user_id: str, body: ChangeUser) -> UserView:
    user = users.update(
        workbench(request), user_id, profile=body.stripped(), role=body.role, active=body.active
    )
    return UserView.of(user)


@router.delete("/users/{user_id}")
def delete_user(request: Request, user_id: str) -> list[UserView]:
    """Deletes the account; answers with the accounts that remain."""
    wb = workbench(request)
    users.delete(wb, user_id)
    return list_users(request)


@router.post("/users/{user_id}/token")
def issue_token(request: Request, user_id: str) -> IssuedToken:
    user, token = users.issue_token(workbench(request), user_id)
    return IssuedToken(user=UserView.of(user), token=token)
