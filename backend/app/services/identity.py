"""Who the current request acts for: set by the sign-in middleware (``app.api.auth``) and read
by the audit trail. Background runs copy the context of the request that started them
(``JobRunner.submit``), so a run's audit entries name the user who started it."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.models.user import LOCAL, Identity

_CURRENT: ContextVar[Identity] = ContextVar("twb_identity", default=LOCAL)


def current() -> Identity:
    """The identity of the current request; the local administrator outside a request."""
    return _CURRENT.get()


@contextmanager
def acting_as(identity: Identity) -> Iterator[Identity]:
    token = _CURRENT.set(identity)
    try:
        yield identity
    finally:
        _CURRENT.reset(token)
