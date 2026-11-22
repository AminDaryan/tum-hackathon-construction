"""AuditRepository on both adapters: append-only trail, oldest first, deterministic ties."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.audit import EntityType
from app.repositories.base import UnitOfWorkFactory
from app.repositories.errors import IntegrityViolationError
from tests.unit.repositories.samples import T0, make_event, minutes


def test_events_are_listed_oldest_first_and_ties_keep_appending_order(
    uow_factory: UnitOfWorkFactory,
) -> None:
    with uow_factory() as uow:
        uow.audit.append(make_event("aud_late_1", occurred_at=minutes(5)))
        uow.audit.append(make_event("aud_early", occurred_at=minutes(0)))
        uow.audit.append(make_event("aud_late_2", occurred_at=minutes(5)))  # tie with late_1
        uow.audit.append(make_event("aud_other_issue", entity_id="iss_000002"))
        uow.audit.append(make_event("aud_other_type", entity_type=EntityType.DOCUMENT))  # same id
    with uow_factory() as uow:
        events = uow.audit.list_for_entity(EntityType.ISSUE, "iss_000001")
        assert [e.event_id for e in events] == ["aud_early", "aud_late_1", "aud_late_2"]
        assert uow.audit.list_for_entity("issue", "iss_unknown") == []
    assert events[0] == make_event("aud_early", occurred_at=minutes(0))  # payload round trip


def test_ties_keep_appending_order_across_units_of_work(uow_factory: UnitOfWorkFactory) -> None:
    for event_id in ("aud_3", "aud_1", "aud_2"):
        with uow_factory() as uow:
            uow.audit.append(make_event(event_id))
    with uow_factory() as uow:
        ids = [e.event_id for e in uow.audit.list_for_entity("issue", "iss_000001")]
    assert ids == ["aud_3", "aud_1", "aud_2"]


def test_duplicate_event_id_is_refused(uow_factory: UnitOfWorkFactory) -> None:
    with uow_factory() as uow:
        uow.audit.append(make_event("aud_1"))
    with pytest.raises(IntegrityViolationError), uow_factory() as uow:
        uow.audit.append(make_event("aud_1"))


def test_untyped_values_come_back_in_their_json_form_on_both_adapters(
    uow_factory: UnitOfWorkFactory,
) -> None:
    # ``context`` is Any-typed, so only its JSON form is stored; the in-memory adapter returns
    # that form as well instead of the original objects.
    event = make_event("aud_1").evolve(
        context={"amount": Decimal("12.50"), "cell": ("C", 4), "checked_at": T0}
    )
    with uow_factory() as uow:
        uow.audit.append(event)
    with uow_factory() as uow:
        (stored,) = uow.audit.list_for_entity("issue", "iss_000001")
    assert stored.context == {
        "amount": "12.50",
        "cell": ["C", 4],
        "checked_at": "2026-03-01T09:00:00Z",
    }
