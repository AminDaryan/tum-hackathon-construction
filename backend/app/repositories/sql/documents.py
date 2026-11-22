"""SQL implementation of :class:`~app.repositories.base.DocumentRepository`."""

from __future__ import annotations

from sqlalchemy import select

from app.models.document import Document
from app.repositories.base import Page
from app.repositories.querying import DOCUMENT_ORDER, check_paging
from app.repositories.records import document_columns, load_model, to_payload
from app.repositories.sql.schema import documents
from app.repositories.sql.statements import (
    SqlRepository,
    count_rows,
    insert_rows,
    next_sequence_value,
    order_by,
    update_row,
)


class SqlDocumentRepository(SqlRepository):
    def add(self, document: Document) -> None:
        connection = self._connection
        payload = to_payload(document)
        row = {
            **document_columns(document),
            "seq": next_sequence_value(connection, documents),
            "payload": payload,
        }
        insert_rows(connection, documents, [row], what=f"document {document.document_id!r}")

    def update(self, document: Document) -> None:
        update_row(
            self._connection,
            documents,
            documents.c.document_id == document.document_id,
            {**document_columns(document), "payload": to_payload(document)},
            what=f"document {document.document_id!r}",
        )

    def get(self, document_id: str) -> Document | None:
        payload = self._connection.execute(
            select(documents.c.payload).where(documents.c.document_id == document_id)
        ).scalar_one_or_none()
        if payload is None:
            return None
        return load_model(Document, payload, what=f"document {document_id!r}")

    def list(self, *, offset: int = 0, limit: int = 50) -> Page[Document]:
        """Newest upload first; uploads at the same instant: most recently stored first."""
        check_paging(offset, limit)
        connection = self._connection
        rows = connection.execute(
            select(documents.c.document_id, documents.c.payload)
            .order_by(*order_by(documents, DOCUMENT_ORDER))
            .offset(offset)
            .limit(limit)
        ).all()
        items = [
            load_model(Document, row.payload, what=f"document {row.document_id!r}") for row in rows
        ]
        return Page(
            items=items, total=count_rows(connection, documents), offset=offset, limit=limit
        )
