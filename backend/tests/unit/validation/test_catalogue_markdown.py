"""The committed detector catalogue matches the registered detectors."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.validation.catalogue_markdown import render
from app.validation.registry import DetectorRegistry

PAGE = Path(__file__).resolve().parents[4] / "docs" / "architecture" / "detector-catalogue.md"


def test_the_committed_catalogue_is_current() -> None:
    expected = render(DetectorRegistry.from_packages(Settings().detector_packages))
    assert PAGE.read_text(encoding="utf-8") == expected, (
        "Regenerate from backend/: .venv/bin/python -m app.validation.catalogue_markdown"
        " > ../docs/architecture/detector-catalogue.md"
    )


def test_every_detector_has_a_section_and_a_working_link() -> None:
    registry = DetectorRegistry.from_packages(Settings().detector_packages)
    page = render(registry)
    for detector_id in registry.ids():
        assert f"\n## {detector_id}\n" in page
        assert f"(#{detector_id.replace('.', '')})" in page


def test_every_detector_names_its_finding_category() -> None:
    registry = DetectorRegistry.from_packages(Settings().detector_packages)
    page = render(registry)
    assert page.count("\n- Finding category: ") == len(registry.ids())
    assert "| [Line total = quantity × unit price](#deterministicline_total) | " in page
    assert "- Finding category: `error`; rule `same_description_dimension`: `inconsistency`" in (
        page
    )
    assert "rule `formula_result_unavailable`: none (reading the file)" in page
