"""Base classes of the response models."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ResponseModel(BaseModel):
    """An API response shape. Immutable, and unknown fields are rejected, so a service cannot
    send a key that the schema does not describe."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Page(ResponseModel, Generic[T]):
    """One page of a list: at most ``limit`` items from position ``offset`` of ``total``."""

    items: list[T]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
