"""Append-only audit trail of uploads, runs, review decisions and corrections."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.models.base import FrozenModel


class AuditAction(StrEnum):
    DOCUMENT_UPLOADED = "document_uploaded"
    DATASET_CREATED = "dataset_created"
    MODEL_ATTACHED = "model_attached"
    MODEL_DETACHED = "model_detached"
    VALIDATION_RUN_COMPLETED = "validation_run_completed"
    REVIEW_FINISHED = "review_finished"
    REVIEW_REOPENED = "review_reopened"
    ISSUE_REVIEWED = "issue_reviewed"
    RISK_REVIEWED = "risk_reviewed"
    CORRECTION_PROPOSED = "correction_proposed"
    CORRECTION_APPLIED = "correction_applied"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_TOKEN_ISSUED = "user_token_issued"  # noqa: S105 - an action name, not a secret


class EntityType(StrEnum):
    DOCUMENT = "document"
    DATASET = "dataset"
    VALIDATION_RUN = "validation_run"
    ISSUE = "issue"
    USER = "user"


class AuditEvent(FrozenModel):
    event_id: str
    occurred_at: datetime
    # Who acted (``Identity.actor``): a user's name, "service" for a configured token, "local"
    # for the local administrator when sign-in is off.
    actor: str
    action: AuditAction
    entity_type: EntityType
    entity_id: str
    summary: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)
