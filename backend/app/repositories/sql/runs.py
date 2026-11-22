"""SQL implementation of :class:`~app.repositories.base.ValidationRunRepository`."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import Select, select

from app.models.run import RunStatus, ValidationRun
from app.repositories.querying import RUN_ORDER
from app.repositories.records import load_model, run_columns, to_payload
from app.repositories.sql.schema import validation_runs
from app.repositories.sql.statements import (
    SqlRepository,
    insert_rows,
    next_sequence_value,
    order_by,
    update_row,
)


def _describe(run_id: str) -> str:
    return f"validation run {run_id!r}"


class SqlValidationRunRepository(SqlRepository):
    def add(self, run: ValidationRun) -> None:
        connection = self._connection
        payload = to_payload(run)
        row = {
            **run_columns(run),
            "seq": next_sequence_value(connection, validation_runs),
            "payload": payload,
        }
        insert_rows(connection, validation_runs, [row], what=_describe(run.run_id))

    def update(self, run: ValidationRun) -> None:
        update_row(
            self._connection,
            validation_runs,
            validation_runs.c.run_id == run.run_id,
            {**run_columns(run), "payload": to_payload(run)},
            what=_describe(run.run_id),
        )

    def get(self, run_id: str) -> ValidationRun | None:
        payload = self._connection.execute(
            select(validation_runs.c.payload).where(validation_runs.c.run_id == run_id)
        ).scalar_one_or_none()
        return (
            None if payload is None else load_model(ValidationRun, payload, what=_describe(run_id))
        )

    def list_for_dataset(self, dataset_id: str) -> list[ValidationRun]:
        """Runs of every revision of the dataset, newest started first."""
        rows = self._connection.execute(self._newest_first(dataset_id)).all()
        return [load_model(ValidationRun, row.payload, what=_describe(row.run_id)) for row in rows]

    def latest_for_dataset(self, dataset_id: str) -> ValidationRun | None:
        row = self._connection.execute(self._newest_first(dataset_id).limit(1)).first()
        return (
            None
            if row is None
            else load_model(ValidationRun, row.payload, what=_describe(row.run_id))
        )

    def list_with_status(self, statuses: Collection[RunStatus]) -> list[ValidationRun]:
        wanted = sorted({RunStatus(status).value for status in statuses})
        rows = self._connection.execute(
            select(validation_runs.c.run_id, validation_runs.c.payload)
            .where(validation_runs.c.status.in_(wanted))
            .order_by(*order_by(validation_runs, RUN_ORDER))
        ).all()
        return [load_model(ValidationRun, row.payload, what=_describe(row.run_id)) for row in rows]

    @staticmethod
    def _newest_first(dataset_id: str) -> Select[Any, Any]:
        return (
            select(validation_runs.c.run_id, validation_runs.c.payload)
            .where(validation_runs.c.dataset_id == dataset_id)
            .order_by(*order_by(validation_runs, RUN_ORDER))
        )
