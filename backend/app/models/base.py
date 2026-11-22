"""Shared Pydantic base classes for the canonical model."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator


class FrozenModel(BaseModel):
    """Immutable, strict-shape model. Canonical records are never mutated in place: changes
    produce new, fully validated objects through :meth:`evolve`, so history can be audited.

    Do not use ``model_copy(update=...)`` for domain changes: Pydantic skips validation there,
    which would let a review decision bypass the review rules or an issue bypass the evidence
    policy. ``model_copy`` without ``update`` (a plain copy) is fine.

    Computed fields (e.g. ``SourceLocation.a1``) are included when serializing and silently
    dropped when parsing, so dumps round-trip while unknown keys are still rejected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        computed = cls.__pydantic_computed_fields__
        if computed and isinstance(data, dict) and any(name in data for name in computed):
            return {key: value for key, value in data.items() if key not in computed}
        return data

    def evolve(self, **changes: Any) -> Self:
        """A validated copy with ``changes`` applied (every validator runs again)."""
        unknown = set(changes) - set(type(self).model_fields)
        if unknown:
            raise ValueError(f"Unknown field(s) for {type(self).__name__}: {sorted(unknown)}")
        data = {name: getattr(self, name) for name in type(self).model_fields}
        data.update(changes)
        return type(self).model_validate(data)
