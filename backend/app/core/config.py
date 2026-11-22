"""Centralized configuration.

All tunable limits live here so that security-relevant values (upload size, ZIP limits, plan
limits) are reviewed in one place. Values can be overridden with environment variables using the
``TWB_`` prefix and ``__`` for nesting, e.g. ``TWB_INGESTION__MAX_UPLOAD_BYTES=10485760``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BUILTIN_PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"


class IngestionLimits(BaseModel):
    """Hard limits applied to every uploaded file before and during extraction.

    The cell limits are a memory budget: a canonical cell with its provenance costs a few
    kilobytes in memory, so one million cells is already several gigabytes at peak. Realistic
    bills of quantities have tens of thousands of cells.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    max_zip_entries: int = Field(default=5_000, gt=0)
    max_uncompressed_bytes: int = Field(default=200 * 1024 * 1024, gt=0)
    max_compression_ratio: float = Field(default=200.0, gt=1)
    max_sheets: int = Field(default=64, gt=0)
    max_rows_per_table: int = Field(default=200_000, gt=0)
    max_columns_per_table: int = Field(default=512, gt=0)
    max_cells_per_sheet: int = Field(default=1_000_000, gt=0)
    max_cells_per_workbook: int = Field(default=1_000_000, gt=0)
    max_cell_chars: int = Field(default=32_767, gt=0)
    max_number_format_chars: int = Field(default=255, gt=0)  # Excel's own limit
    max_pdf_pages: int = Field(default=2_000, gt=0)


class OcrSettings(BaseModel):
    """Text recognition (OCR) for PDF pages without a usable text layer (scans), with the
    locally installed ``tesseract`` command. Nothing is sent to any service."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    command: str = Field(default="tesseract", min_length=1)
    # Tesseract language data, joined with "+": German and English bills.
    languages: str = Field(default="deu+eng", pattern=r"^[A-Za-z_]{3,}(?:\+[A-Za-z_]{3,})*$")
    dpi: int = Field(default=300, ge=150, le=600)  # resolution pages are rendered at
    # Tesseract page segmentation: 4 (one column of text of varying sizes) keeps the quantity
    # lines of printed bills that 6 (one uniform block) drops with their dotted leaders.
    page_segmentation: int = Field(default=4, ge=3, le=13)
    max_pages: int = Field(default=300, gt=0)  # pages one PDF may need OCR on
    # tesseract processes run in parallel; 0: one per CPU core, at most 8
    workers: int = Field(default=0, ge=0, le=32)
    page_timeout_seconds: float = Field(default=120.0, gt=0)


# Which databases written by an older build are upgraded at start-up (app.repositories.sql
# .migrations): "sqlite" upgrades SQLite files only (after copying the file), "always" every
# database, "never" none (run ``python -m app.cli db upgrade`` instead).
AutoUpgradePolicy = Literal["sqlite", "always", "never"]


class PersistenceSettings(BaseModel):
    """Database tunables (``app.repositories.sql.Database``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    busy_timeout_ms: int = Field(default=30_000, ge=0)  # SQLite writer wait before failing
    lock_timeout_seconds: float = Field(default=30.0, gt=0)  # in-memory test-mode lock
    dataset_cache_entries: int = Field(default=8, ge=0)  # decoded dataset snapshots kept
    # PostgreSQL is not upgraded at start-up by default: back it up, then run the CLI once.
    auto_upgrade: AutoUpgradePolicy = "sqlite"
    backup_before_upgrade: bool = True  # SQLite files: copy the file before an upgrade


class NormalizationOptions(BaseModel):
    """Tunables of normalization (raw grids -> canonical dataset). Label and pattern text
    is bounded by ``app.core.patterns.MAX_MATCH_CHARS`` (one place for that limit)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    header_scan_rows: int = Field(default=30, gt=0, le=500)  # non-empty rows searched
    type_dominance_threshold: float = Field(default=0.8, gt=0.5, le=1)  # dominant column type
    fuzzy_header_threshold: float = Field(default=0.85, ge=0.5, le=1)  # difflib ratio


class ValidationLimits(BaseModel):
    """Limits that keep validation runs bounded, including future LLM-generated plans.

    Issue caps are enforced when issues are created (the issue factory stops a detector at its
    cap), and time limits are checked while detectors iterate rows, so neither memory nor time
    can grow without bound before a limit applies.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_plan_steps: int = Field(default=64, gt=0)
    max_steps_per_detector: int = Field(default=3, gt=0)
    max_issues_per_detector: int = Field(default=10_000, gt=0)
    max_issues_per_run: int = Field(default=50_000, gt=0)
    max_detector_seconds: float = Field(default=60.0, gt=0)
    max_run_seconds: float = Field(default=300.0, gt=0)
    low_confidence_threshold: float = Field(default=0.9, ge=0, le=1)


class LoggingSettings(BaseModel):
    """Logging of the ``app`` loggers (``app.core.logging``): the level, and the format of the
    lines written to standard error: ``text`` for people, ``json`` (one object per line) for
    log collectors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    format: Literal["text", "json"] = "text"

    @field_validator("level", mode="before")
    @classmethod
    def _upper_case(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class AuthSettings(BaseModel):
    """Optional sign-in. Without tokens (the default) the API is open, as intended for one
    reviewer on their own machine. With tokens, every route under ``/api/v1`` except
    ``GET /api/v1/health`` requires ``Authorization: Bearer <token>`` naming one of them
    (``app.api.auth``). Set as a JSON list: ``TWB_AUTH__TOKENS='["…"]'``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Secret: masked in reprs and dumps. The middleware checks that each can be sent in a header.
    tokens: list[SecretStr] = Field(default_factory=list)

    @property
    def required(self) -> bool:
        return bool(self.tokens)


class JobSettings(BaseModel):
    """Background work: validation runs started with ``Prefer: respond-async``
    (``app.services.jobs``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workers: int = Field(default=2, ge=1, le=32)  # threads running background validation runs
    # Background runs that may wait for a free worker. A request beyond workers + max_waiting
    # is refused with 503 run_queue_full (and Retry-After) instead of growing the queue.
    max_waiting: int = Field(default=16, ge=0, le=1000)
    # At start-up, runs that a crash left queued or running become failed. Turn it off on all
    # but one instance when several application processes share one database.
    recover_interrupted_runs: bool = True
    # Validate every bill without being asked: after an upload, a model change or a change of
    # its project's files, and at start-up the bills that have no run yet. The image turns it
    # on (Dockerfile).
    auto_validate: bool = False


# Host names of this machine: the only hosts llm.base_url may name unless allow_remote is set.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class LLMSettings(BaseModel):
    """The local language model (``TWB_LLM__...``). With ``provider = "none"``, the default,
    nothing connects to a model. Only an Ollama server is supported, and only on this machine
    (``localhost``, ``127.0.0.1`` or ``::1``) unless ``allow_remote`` is true, so document
    content cannot leave the machine by a typo. A configured ``model`` must be on the
    allow-list in :mod:`app.agents.models`; both are checked at start-up."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["none", "ollama"] = "none"
    base_url: str = Field(default="http://127.0.0.1:11434", max_length=2048)
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    request_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)
    context_tokens: int = Field(default=8192, ge=1024, le=1_048_576)
    max_output_tokens: int = Field(default=1024, ge=1, le=65_536)
    allow_remote: bool = False
    # Reuse a stored answer for the same input, model and prompt instead of asking again.
    reuse_cached: bool = True

    @model_validator(mode="after")
    def _checked(self) -> LLMSettings:
        try:
            parts = urlsplit(self.base_url)
            _ = parts.port  # raises ValueError for a port that is not a number
        except ValueError:
            raise ValueError("llm.base_url is not a valid URL") from None
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("llm.base_url must be an http:// or https:// URL with a host name")
        if parts.username is not None or parts.password is not None:
            raise ValueError("llm.base_url must not contain a user name or password")
        if parts.query or parts.fragment:
            raise ValueError("llm.base_url must not contain a query or a fragment")
        if not self.allow_remote and parts.hostname.lower() not in LOOPBACK_HOSTS:
            raise ValueError(
                "llm.base_url names a host other than this machine (localhost, 127.0.0.1 or "
                "::1); set llm.allow_remote=true to send document content to that host"
            )
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("llm.max_output_tokens must be smaller than llm.context_tokens")
        return self


class BillReviewSettings(BaseModel):
    """The Claude bill review a reviewer starts for one bill (``TWB_BILL_REVIEW__...``). Without
    ``anthropic_api_key``, the default, it is off and nothing is sent anywhere. With a key (and
    the optional ``anthropic`` package), a validation run that asks for it sends the text of
    that one bill to Anthropic's API (:mod:`app.services.bill_reviews`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    anthropic_api_key: SecretStr | None = None


class Settings(BaseSettings):
    """Application settings. Construct directly in tests; use :func:`get_settings` elsewhere."""

    model_config = SettingsConfigDict(
        env_prefix="TWB_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        # A malformed value (for example a sign-in token given as a JSON string, not a list)
        # must not reach the startup traceback and the process log with its secret.
        hide_input_in_errors=True,
    )

    app_name: str = "Desvio"
    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("var")
    database_url: str | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    # Host header allowlist (blocks DNS-rebinding attacks on the local, unauthenticated API).
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    # With a value, every path (interface, static files, API) sits behind a one-input gate page
    # (``app.api.gate``); meant for a hosted preview.
    gate_phrase: SecretStr | None = None
    # Request bodies other than uploads (JSON plans, review decisions) are small.
    max_json_body_bytes: int = Field(default=1024 * 1024, gt=0)
    default_profile_id: str = "boq"
    extra_profile_dirs: list[Path] = Field(default_factory=list)
    detector_packages: list[str] = Field(
        default_factory=lambda: [
            "app.validation.deterministic",
            "app.validation.statistical",
            "app.validation.machine_learning",
            "app.validation.semantic",
            "app.validation.domain",
        ]
    )
    ingestion: IngestionLimits = Field(default_factory=IngestionLimits)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    normalization: NormalizationOptions = Field(default_factory=NormalizationOptions)
    persistence: PersistenceSettings = Field(default_factory=PersistenceSettings)
    validation: ValidationLimits = Field(default_factory=ValidationLimits)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    # The web interface's build (``npm run build``); with an index.html it is served at "/".
    frontend_dist_dir: Path | None = None
    jobs: JobSettings = Field(default_factory=JobSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    bill_review: BillReviewSettings = Field(default_factory=BillReviewSettings)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'workbench.sqlite3').as_posix()}"

    @property
    def profile_dirs(self) -> list[Path]:
        return [BUILTIN_PROFILE_DIR, *self.extra_profile_dirs]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
