"""The error envelope (``docs/api/rest-api.md``, "Errors") and the exception handlers.

Expected errors (:class:`WorkbenchError`) keep their stable ``code`` and map to an HTTP status by
class; anything else is ``500 internal_error`` with a generic message, logged with the request
id. Every envelope carries the request id, also as the ``X-Request-ID`` header.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import Scope

from app.core.errors import (
    ConflictError,
    ExtractionError,
    FileRejectedError,
    FileTooLargeError,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
    UnsupportedFormatError,
    WorkbenchError,
)
from app.schemas.errors import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
ERROR_CODE_STATE = "error_code"  # key of the request state that holds the sent error code
_BY_CLASS: list[tuple[type[WorkbenchError], int]] = [
    (NotFoundError, 404),
    (UnsupportedFormatError, 415),
    (FileTooLargeError, 413),
    (FileRejectedError, 422),
    (ConflictError, 409),
    (UnavailableError, 503),
    (InvalidInputError, 422),
    (ExtractionError, 422),
]
_HTTP_CODES = {404: "not_found", 405: "method_not_allowed", 413: "request_too_large"}


class RequestTooLargeError(HTTPException):
    """A request body over its limit. An ``HTTPException`` so FastAPI does not turn it into
    "error parsing the body" while it reads the body."""

    def __init__(self, code: str, limit: int) -> None:
        super().__init__(status_code=413, detail=f"The request body exceeds {limit} bytes.")
        self.code = code
        self.limit = limit


def request_id_of(scope_or_request: Request | Scope) -> str | None:
    scope = scope_or_request.scope if isinstance(scope_or_request, Request) else scope_or_request
    state = scope.get("state") or {}
    value = state.get("request_id")
    return value if isinstance(value, str) else None


def envelope(
    status: int,
    code: str,
    message: str,
    *,
    request_id: str | None,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    sent = dict(headers or {})
    if request_id:
        sent[REQUEST_ID_HEADER] = request_id
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details or {}, request_id=request_id)
    )
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=sent)


def rejection(
    scope: Scope,
    status: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """The envelope for a rejected or failed request. The code is also kept in the request's
    state, where the access log line picks it up (:func:`error_code_of`)."""
    scope.setdefault("state", {})[ERROR_CODE_STATE] = code
    return envelope(
        status, code, message, request_id=request_id_of(scope), details=details, headers=headers
    )


def error_code_of(scope: Scope) -> str | None:
    value = (scope.get("state") or {}).get(ERROR_CODE_STATE)
    return value if isinstance(value, str) else None


def status_for(error: WorkbenchError) -> int | None:
    for cls, status in _BY_CLASS:
        if isinstance(error, cls):
            return status
    return None


async def _workbench_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, WorkbenchError)
    status = status_for(exc)
    if status is None:  # persistence, profile or registry failures: not the client's fault
        logger.error(
            "request %s failed: %s (%s)", request_id_of(request), exc.code, exc, exc_info=exc
        )
        return rejection(request.scope, 500, "internal_error", "An internal error occurred.")
    headers = None
    if isinstance(exc, UnavailableError) and exc.retry_after is not None:
        headers = {"Retry-After": str(exc.retry_after)}
    return rejection(
        request.scope, status, exc.code, str(exc), details=exc.details, headers=headers
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(error.get("loc", ())), "msg": error.get("msg"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return rejection(
        request.scope,
        422,
        "request_validation_failed",
        "The request is malformed.",
        details={"errors": errors},
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    code = getattr(exc, "code", None) or _HTTP_CODES.get(exc.status_code, "http_error")
    details = {"limit": exc.limit} if isinstance(exc, RequestTooLargeError) else None
    return rejection(request.scope, exc.status_code, code, str(exc.detail), details=details)


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.error("request %s failed unexpectedly", request_id_of(request), exc_info=exc)
    return rejection(request.scope, 500, "internal_error", "An internal error occurred.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(WorkbenchError, _workbench_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
