"""The error envelope of every rejected or failed request (``docs/api/rest-api.md``, "Errors")."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.base import ResponseModel


class ErrorDetail(ResponseModel):
    code: str = Field(description="Stable, machine-readable error code.")
    message: str = Field(description="Explanation for people; not meant to be parsed.")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Structured context; the keys depend on the code."
    )
    request_id: str | None = Field(description="The request id, also sent as X-Request-ID.")


class ErrorResponse(ResponseModel):
    error: ErrorDetail
