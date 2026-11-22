"""Logging configuration (``Settings.logging``), applied when the application starts.

Every module logs through ``logging.getLogger(__name__)``, so the application's loggers form the
``app`` namespace. :func:`configure_logging` sets that namespace's level and gives it one handler
that writes to standard error, as text or as one JSON object per line. Records still propagate,
so a log collector or a test runner attached to the root logger sees them too.

Each record carries the id of the request it belongs to (``request_id``, ``None`` outside a
request), set by the API's request id middleware through :data:`request_id_var`. Nothing here
logs request bodies, headers or file contents; callers log ids, sizes and codes only.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from app.core.config import LoggingSettings

APP_LOGGER = "app"
TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_RECORD_ATTRIBUTES = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "request_id",
}


class RequestIdFilter(logging.Filter):
    """Adds ``request_id`` to every record: the current request's id, else ``missing``."""

    def __init__(self, missing: str | None = None) -> None:
        super().__init__()
        self.missing = missing

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = request_id_var.get() or self.missing
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per record: time (UTC), level, logger, message, request id, the record's
    ``extra`` fields and, when present, the formatted exception."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        entry.update(
            (key, value)
            for key, value in vars(record).items()
            if key not in _RECORD_ATTRIBUTES and not key.startswith("_")
        )
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class _StandardErrorHandler(logging.StreamHandler[TextIO]):
    """Writes to the *current* ``sys.stderr``, so a replaced stream (a test runner capturing
    output, for example) never leaves the handler writing to a closed file."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, _: TextIO) -> None:
        pass


def configure_logging(settings: LoggingSettings) -> logging.Handler:
    """Apply ``settings`` to the ``app`` loggers; calling it again replaces the handler it
    installed before. Returns the handler."""
    logger = logging.getLogger(APP_LOGGER)
    for handler in list(logger.handlers):
        if isinstance(handler, _StandardErrorHandler):
            logger.removeHandler(handler)
    handler = _StandardErrorHandler()
    if settings.format == "json":
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(JsonFormatter())
    else:
        handler.addFilter(RequestIdFilter(missing="-"))
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(settings.level)
    return handler
