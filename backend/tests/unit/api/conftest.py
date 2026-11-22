"""Applications on in-memory storage for the API unit tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.ids import SequentialIdFactory
from app.main import create_app
from app.repositories.memory import InMemoryDatabase, InMemoryUnitOfWorkFactory
from app.services.workbench import Workbench, build_workbench
from app.storage.file_store import LocalFileStore

MakeClient = Callable[..., TestClient]


def make_workbench(root: Path, **settings: Any) -> Workbench:
    return build_workbench(
        Settings(data_dir=root, environment="test", **settings),
        uow=InMemoryUnitOfWorkFactory(InMemoryDatabase()),
        files=LocalFileStore(root),
        ids=SequentialIdFactory(),
        clock=FixedClock(),
    )


@pytest.fixture
def make_client(tmp_path: Path) -> Iterator[MakeClient]:
    """``make_client(**settings)``: a started test client of a new application."""
    clients: list[TestClient] = []

    def make(**settings: Any) -> TestClient:
        client = TestClient(
            create_app(workbench=make_workbench(tmp_path, **settings)),
            base_url="http://localhost",
        )
        clients.append(client.__enter__())
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)
