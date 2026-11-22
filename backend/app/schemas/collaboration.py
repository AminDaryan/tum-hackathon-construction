"""The API input shapes of finding discussions and tasks (see :mod:`app.services.collaboration`)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["todo", "in_progress", "waiting", "done"]
TaskType = Literal["check", "fix", "ask_client", "discussion"]


class ReviewerChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")


class CommentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignee: str | None = None
    status: TaskStatus = "todo"
    task_type: TaskType | None = None
    due_date: date | None = None
