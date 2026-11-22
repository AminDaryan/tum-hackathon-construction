"""SQL persistence adapter (SQLAlchemy Core): SQLite now, PostgreSQL by changing the URL.

Typical wiring::

    database = Database(settings.resolved_database_url)  # once per process
    uow_factory = SqlUnitOfWorkFactory(database)          # satisfies UnitOfWorkFactory
    with uow_factory() as uow:                            # once per request
        uow.documents.add(document)
"""

from app.repositories.sql.database import Database
from app.repositories.sql.schema import SCHEMA_VERSION
from app.repositories.sql.unit_of_work import SqlUnitOfWork, SqlUnitOfWorkFactory

__all__ = ["SCHEMA_VERSION", "Database", "SqlUnitOfWork", "SqlUnitOfWorkFactory"]
