"""``configure_logging`` and ``Settings.logging`` (contract K5)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import LoggingSettings, Settings
from app.core.logging import JsonFormatter, configure_logging, request_id_var
from app.main import create_app


@pytest.fixture
def app_logger() -> Iterator[logging.Logger]:
    """The ``app`` logger, restored after the test."""
    logger = logging.getLogger("app")
    saved = list(logger.handlers), logger.level, logger.propagate
    yield logger
    logger.handlers[:] = saved[0]
    logger.setLevel(saved[1])
    logger.propagate = saved[2]


def test_text_lines(app_logger: logging.Logger, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LoggingSettings(level="DEBUG"))
    logging.getLogger("app.example").debug("checked %d rows", 3)
    token = request_id_var.set("req-1")
    try:
        logging.getLogger("app.example").info("inside a request")
    finally:
        request_id_var.reset(token)
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].endswith(" DEBUG app.example [-] checked 3 rows")
    assert lines[1].endswith(" INFO app.example [req-1] inside a request")


def test_json_lines(app_logger: logging.Logger, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(LoggingSettings(format="json"))
    log = logging.getLogger("app.example")
    log.info("stored %s", "doc_1", extra={"document_id": "doc_1", "size_bytes": 12})
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed")
    first, second = (json.loads(line) for line in capsys.readouterr().err.splitlines())
    assert first["level"] == "INFO" and first["logger"] == "app.example"
    assert first["message"] == "stored doc_1" and first["request_id"] is None
    assert first["document_id"] == "doc_1" and first["size_bytes"] == 12
    assert first["time"].endswith("Z")
    assert second["level"] == "ERROR" and "ValueError: boom" in second["exception"]


def test_the_level_applies_and_reconfiguring_replaces_the_handler(
    app_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(LoggingSettings())
    configure_logging(LoggingSettings(level="WARNING", format="json"))
    ours = [h for h in app_logger.handlers if isinstance(h.formatter, JsonFormatter)]
    assert len(app_logger.handlers) == len(set(app_logger.handlers)) and len(ours) == 1
    assert app_logger.level == logging.WARNING and app_logger.propagate
    logging.getLogger("app.example").info("not shown")
    logging.getLogger("app.example").warning("shown")
    lines = capsys.readouterr().err.splitlines()
    assert [json.loads(line)["message"] for line in lines] == ["shown"]


def test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    assert LoggingSettings() == LoggingSettings(level="INFO", format="text")
    assert LoggingSettings(level="debug").level == "DEBUG"
    with pytest.raises(ValidationError):
        LoggingSettings(format="xml")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        LoggingSettings(level="LOUD")  # type: ignore[arg-type]
    monkeypatch.setenv("TWB_LOGGING__LEVEL", "warning")
    monkeypatch.setenv("TWB_LOGGING__FORMAT", "json")
    assert Settings().logging == LoggingSettings(level="WARNING", format="json")


def test_the_application_configures_logging_when_it_starts(
    app_logger: logging.Logger, tmp_path: Path
) -> None:
    settings = Settings(data_dir=tmp_path, logging=LoggingSettings(level="ERROR", format="json"))
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.get("/api/v1/health").status_code == 200
    assert app_logger.level == logging.ERROR
    assert any(isinstance(h.formatter, JsonFormatter) for h in app_logger.handlers)


def test_importing_the_application_configures_nothing() -> None:
    code = "import logging, app.main; print(len(logging.getLogger('app').handlers))"
    backend = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "0"
