"""The ``/api/v1`` routers, one module per resource.

Every route answers errors with the envelope of :class:`app.schemas.errors.ErrorResponse`, and
the OpenAPI document says so for every operation.
"""

from typing import Any

from fastapi import APIRouter

from app.api.routes import (
    catalogue,
    clarifications,
    collaboration,
    datasets,
    documents,
    issues,
    projects,
    risks,
    runs,
    users,
)
from app.schemas.errors import ErrorResponse

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "Rejected; `error.code` says why."},
    "5XX": {"model": ErrorResponse, "description": "Internal error (`internal_error`)."},
}

api_router = APIRouter(responses=ERROR_RESPONSES)
for module in (
    catalogue,
    documents,
    datasets,
    runs,
    issues,
    projects,
    clarifications,
    risks,
    users,
    collaboration,
):
    api_router.include_router(module.router)

__all__ = ["ERROR_RESPONSES", "api_router"]
