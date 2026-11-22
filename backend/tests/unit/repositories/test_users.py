"""UserRepository on every adapter: storage, updates, deletion, the token lookup, the listing
order, and integrity (unique ids and token digests, a failed unit of work stores nothing)."""

from __future__ import annotations

import pytest

from app.core.errors import NotFoundError
from app.models.user import Role, User
from app.repositories.base import UnitOfWorkFactory
from app.repositories.errors import IntegrityViolationError
from tests.unit.repositories.samples import T0, Boom, fail_after, minutes


def _user(user_id: str, name: str, *, digest: str | None = None, role: Role = Role.REVIEWER):
    return User(
        user_id=user_id,
        first_name=name,
        email=f"{user_id}@example.test",
        role=role,
        created_at=T0,
        token_digest=digest,
        token_hint=None if digest is None else digest[-4:],
        token_issued_at=None if digest is None else minutes(1),
    )


def test_add_get_update_and_delete(uow_factory: UnitOfWorkFactory) -> None:
    anna = _user("usr_1", "Anna", digest="a" * 64)
    with uow_factory() as uow:
        uow.users.add(anna)
    with uow_factory() as uow:
        assert uow.users.get("usr_1") == anna
        assert uow.users.get("usr_x") is None
        assert uow.users.by_token_digest("a" * 64) == anna
        assert uow.users.by_token_digest("b" * 64) is None
    viewer = anna.model_copy(update={"role": Role.VIEWER, "token_digest": "c" * 64})
    with uow_factory() as uow:
        uow.users.update(viewer)
    with uow_factory() as uow:
        assert uow.users.get("usr_1") == viewer
        assert uow.users.by_token_digest("a" * 64) is None  # the old token no longer matches
        assert uow.users.by_token_digest("c" * 64) == viewer
        uow.users.delete("usr_1")
    with uow_factory() as uow:
        assert uow.users.get("usr_1") is None and uow.users.list() == []
        with pytest.raises(NotFoundError):
            uow.users.delete("usr_1")
        with pytest.raises(NotFoundError):
            uow.users.update(viewer)


def test_listed_by_name_ignoring_case(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        for user in (_user("usr_3", "zoe"), _user("usr_1", "Bert"), _user("usr_2", "anna")):
            uow.users.add(user)
    with uow_factory() as uow:
        assert [user.name for user in uow.users.list()] == ["anna", "Bert", "zoe"]


def test_ids_and_token_digests_are_unique(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.users.add(_user("usr_1", "Anna", digest="a" * 64))
        uow.users.add(_user("usr_2", "Bert"))
        uow.users.add(_user("usr_3", "Carl"))  # several accounts may have no token
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.users.add(_user("usr_1", "Again"))
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.users.add(_user("usr_4", "Dora", digest="a" * 64))
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.users.update(_user("usr_2", "Bert", digest="a" * 64))
    with uow_factory() as uow:
        assert [user.user_id for user in uow.users.list()] == ["usr_1", "usr_2", "usr_3"]


def test_a_failed_unit_of_work_stores_nothing(uow_factory: UnitOfWorkFactory) -> None:
    with pytest.raises(Boom):
        fail_after(uow_factory, lambda uow: uow.users.add(_user("usr_1", "Anna")))
    with uow_factory() as uow:
        assert uow.users.list() == []
