"""User accounts. The token digest is also a column, with a unique index, for the sign-in lookup."""

from sqlalchemy import delete, select

from app.core.errors import NotFoundError
from app.models.user import User
from app.repositories.records import load_model, to_payload
from app.repositories.sql.schema import users
from app.repositories.sql.statements import SqlRepository, insert_rows, update_row


class SqlUserRepository(SqlRepository):
    def add(self, user: User) -> None:
        insert_rows(
            self._connection,
            users,
            [
                {
                    "user_id": user.user_id,
                    "token_digest": user.token_digest,
                    "payload": to_payload(user),
                }
            ],
            what=f"user {user.user_id!r}",
        )

    def update(self, user: User) -> None:
        update_row(
            self._connection,
            users,
            users.c.user_id == user.user_id,
            {"token_digest": user.token_digest, "payload": to_payload(user)},
            what=f"user {user.user_id!r}",
        )

    def delete(self, user_id: str) -> None:
        result = self._connection.execute(delete(users).where(users.c.user_id == user_id))
        if result.rowcount != 1:
            raise NotFoundError(f"Cannot delete user {user_id!r}: it does not exist.")

    def get(self, user_id: str) -> User | None:
        payload = self._connection.execute(
            select(users.c.payload).where(users.c.user_id == user_id)
        ).scalar_one_or_none()
        return None if payload is None else load_model(User, payload, what="user")

    def by_token_digest(self, token_digest: str) -> User | None:
        payload = self._connection.execute(
            select(users.c.payload).where(users.c.token_digest == token_digest)
        ).scalar_one_or_none()
        return None if payload is None else load_model(User, payload, what="user")

    def list(self) -> list[User]:
        found = [
            load_model(User, payload, what="user")
            for payload in self._connection.execute(select(users.c.payload)).scalars()
        ]
        return sorted(found, key=lambda user: (user.name.casefold(), user.user_id))
