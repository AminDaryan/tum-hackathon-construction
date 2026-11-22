"""SQL implementation of :class:`~app.repositories.base.AuditRepository` (append-only)."""

from __future__ import annotations

from sqlalchemy import select

from app.models.audit import AuditEvent, EntityType
from app.repositories.querying import AUDIT_ORDER, entity_type_value
from app.repositories.records import audit_columns, load_model, to_payload
from app.repositories.sql.schema import audit_events
from app.repositories.sql.statements import (
    SqlRepository,
    insert_rows,
    next_sequence_value,
    order_by,
)


class SqlAuditRepository(SqlRepository):
    def append(self, event: AuditEvent) -> None:
        connection = self._connection
        payload = to_payload(event)
        row = {
            **audit_columns(event),
            "seq": next_sequence_value(connection, audit_events),
            "payload": payload,
        }
        insert_rows(connection, audit_events, [row], what=f"audit event {event.event_id!r}")

    def list_for_entity(self, entity_type: EntityType | str, entity_id: str) -> list[AuditEvent]:
        """The entity's events, oldest first (appending order for identical timestamps)."""
        stored_type = entity_type_value(entity_type)
        rows = self._connection.execute(
            select(audit_events.c.event_id, audit_events.c.payload)
            .where(audit_events.c.entity_type == stored_type)
            .where(audit_events.c.entity_id == entity_id)
            .order_by(*order_by(audit_events, AUDIT_ORDER))
        ).all()
        return [
            load_model(AuditEvent, row.payload, what=f"audit event {row.event_id!r}")
            for row in rows
        ]
