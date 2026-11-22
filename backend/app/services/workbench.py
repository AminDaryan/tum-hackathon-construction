"""The application's services, wired once per process and shared by the API routers.

:func:`build_workbench` loads the profiles and the detector catalogue (and checks that they
match), opens the database and the file store. Tests pass an in-memory unit of work, a file
store under a temporary directory, a ``SequentialIdFactory`` and a ``FixedClock``. The planner
for runs requested without a plan is the baseline planner unless one is passed in. A
configured language model must be on the allow-list (``app.agents.models``).

Every service function takes the :class:`Workbench` first and opens its own unit of work, so a
request is one or two short transactions; nothing from a document is ever executed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.agents.models import ALLOWED_MODELS, AllowedModel, check_configured_model
from app.agents.ollama import LLMHealth
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.ids import IdFactory, IdPrefix, RandomIdFactory
from app.ingestion.registry import AdapterRegistry, default_adapters
from app.models.audit import AuditAction, AuditEvent, EntityType
from app.profiles.loader import ProfileCatalog
from app.repositories.base import UnitOfWork, UnitOfWorkFactory
from app.repositories.lru_cache import LruCache
from app.repositories.sql.database import Database
from app.repositories.sql.unit_of_work import SqlUnitOfWorkFactory
from app.services import identity
from app.services.jobs import JobRunner
from app.storage.file_store import FileStore, LocalFileStore
from app.validation.planner import BaselinePlanner, Planner
from app.validation.profile_check import check_profiles
from app.validation.registry.registry import DetectorRegistry

if TYPE_CHECKING:
    from app.risk.service import RunQuestions


@dataclass(frozen=True, slots=True)
class Workbench:
    settings: Settings
    uow: UnitOfWorkFactory
    files: FileStore
    adapters: AdapterRegistry
    profiles: ProfileCatalog
    detectors: DetectorRegistry
    ids: IdFactory
    clock: Clock
    planner: Planner  # plans runs requested without a plan
    llm: LLMHealth  # the language model's status for the health check
    database: Database | None = None  # owned (and closed) only when built here
    # Background validation runs; shut down (and waited for) before the database closes.
    jobs: JobRunner = field(default_factory=lambda: JobRunner(workers=1))
    # The clarification questions of finished runs, by run id (app.risk.service).
    run_questions: LruCache[str, RunQuestions] = field(default_factory=lambda: LruCache(256))

    def close(self) -> None:
        self.jobs.shutdown()
        if self.database is not None:
            self.database.dispose()

    def audit(
        self,
        uow: UnitOfWork,
        action: AuditAction,
        entity_type: EntityType,
        entity_id: str,
        summary: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        acting = identity.current()  # who the request acts for (app.api.auth)
        context = dict(context or {})
        if acting.user_id is not None:  # names can repeat; the id cannot
            context.setdefault("actor_id", acting.user_id)
        uow.audit.append(
            AuditEvent(
                event_id=self.ids.new(IdPrefix.AUDIT),
                occurred_at=self.clock.now(),
                actor=acting.actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=summary,
                before=before,
                after=after,
                context=context,
            )
        )


def build_workbench(
    settings: Settings,
    *,
    uow: UnitOfWorkFactory | None = None,
    files: FileStore | None = None,
    ids: IdFactory | None = None,
    clock: Clock | None = None,
    planner: Planner | None = None,
    allowed_models: Mapping[str, AllowedModel] = ALLOWED_MODELS,
) -> Workbench:
    check_configured_model(settings.llm, allowed_models)  # a model not allowed fails at startup
    profiles = ProfileCatalog.from_directories(settings.profile_dirs)
    detectors = DetectorRegistry.from_packages(settings.detector_packages)
    check_profiles(profiles.list(), detectors)  # a profile/catalogue mismatch fails at startup
    database: Database | None = None
    if uow is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        database = Database(
            settings.resolved_database_url,
            dataset_cache_entries=settings.persistence.dataset_cache_entries,
            busy_timeout_ms=settings.persistence.busy_timeout_ms,
            lock_timeout_seconds=settings.persistence.lock_timeout_seconds,
            auto_upgrade=settings.persistence.auto_upgrade,
            backup_before_upgrade=settings.persistence.backup_before_upgrade,
        )
        uow = SqlUnitOfWorkFactory(database)
    return Workbench(
        settings=settings,
        uow=uow,
        files=files or LocalFileStore(settings.data_dir),
        adapters=AdapterRegistry(default_adapters(settings.ocr)),
        profiles=profiles,
        detectors=detectors,
        ids=ids or RandomIdFactory(),
        clock=clock or SystemClock(),
        planner=planner or BaselinePlanner(detectors),
        llm=LLMHealth(settings.llm),
        database=database,
        jobs=JobRunner(
            workers=settings.jobs.workers,
            max_waiting=settings.jobs.max_waiting,
            thread_name_prefix="twb-run",
        ),
    )
