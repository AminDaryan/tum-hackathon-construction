"""SQL implementation of :class:`~app.repositories.base.ExplanationRepository`."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select

from app.models.explanation import Explanation
from app.repositories.querying import EXPLANATION_ORDER
from app.repositories.records import explanation_columns, load_model, to_payload
from app.repositories.sql.schema import explanations
from app.repositories.sql.statements import (
    SqlRepository,
    insert_rows,
    next_sequence_value,
    order_by,
    update_row,
)


def _describe(explanation_id: str) -> str:
    return f"explanation {explanation_id!r}"


class SqlExplanationRepository(SqlRepository):
    def add(self, explanation: Explanation) -> None:
        connection = self._connection
        row = {
            **explanation_columns(explanation),
            "seq": next_sequence_value(connection, explanations),
            "payload": to_payload(explanation),
        }
        insert_rows(connection, explanations, [row], what=_describe(explanation.explanation_id))

    def update(self, explanation: Explanation) -> None:
        update_row(
            self._connection,
            explanations,
            explanations.c.explanation_id == explanation.explanation_id,
            {**explanation_columns(explanation), "payload": to_payload(explanation)},
            what=_describe(explanation.explanation_id),
        )

    def get(self, explanation_id: str) -> Explanation | None:
        payload = self._connection.execute(
            select(explanations.c.payload).where(explanations.c.explanation_id == explanation_id)
        ).scalar_one_or_none()
        if payload is None:
            return None
        return load_model(Explanation, payload, what=_describe(explanation_id))

    def latest_for_problem(self, run_id: str, problem_id: str) -> Explanation | None:
        row = self._connection.execute(
            self._newest_first(run_id).where(explanations.c.problem_id == problem_id).limit(1)
        ).first()
        if row is None:
            return None
        return load_model(Explanation, row.payload, what=_describe(row.explanation_id))

    def list_for_run(self, run_id: str) -> list[Explanation]:
        rows = self._connection.execute(self._newest_first(run_id)).all()
        return [
            load_model(Explanation, row.payload, what=_describe(row.explanation_id)) for row in rows
        ]

    @staticmethod
    def _newest_first(run_id: str) -> Select[str, Any]:
        return (
            select(explanations.c.explanation_id, explanations.c.payload)
            .where(explanations.c.run_id == run_id)
            .order_by(*order_by(explanations, EXPLANATION_ORDER))
        )
