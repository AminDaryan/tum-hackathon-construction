"""SYSTEM_REQUIREMENTS.md is the one list of tool versions; every place that installs a tool
must use the version it lists.

The places are CI (``.github/workflows/ci.yml``), the ``Dockerfile``, ``docker-compose.yml``,
``backend/pyproject.toml``, ``frontend/package.json`` and the header of the backend lock file.
A version changed in one of them and not in the list (or the other way round) fails here, so
the versions cannot drift apart again.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.agents.models import ALLOWED_MODELS

ROOT = Path(__file__).resolve().parents[3]
VERSION = re.compile(r"\d+(?:\.\d+)+")
PINNED_TOOLS = (
    "Python",
    "Python on Windows",
    "pip",
    "hatchling",
    "Node.js",
    "npm",
    "PostgreSQL",
    "Tesseract OCR",
    "Ollama",
)


def listed_versions(markdown: str) -> dict[str, str]:
    """Requirement → version, from the table that follows the "## Versions" heading."""
    _, _, part = markdown.partition("## Versions")
    rows: dict[str, str] = {}
    for line in part.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == "Requirement" or set(cells[0]) <= {"-", ":"}:
            continue
        rows[cells[0]] = cells[1].strip("`")
    return rows


def as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def minor(version: str) -> str:
    return ".".join(version.split(".")[:2])


def accepts(npm_range: str, version: str) -> bool:
    """Whether an npm range of ``^x.y.z`` and ``>=x.y.z`` clauses joined by ``||`` accepts
    ``version`` (the only forms ``engines`` uses; anything else is refused)."""
    wanted = as_tuple(version)
    for clause in (part.strip() for part in npm_range.split("||")):
        if clause.startswith("^"):
            lowest = as_tuple(clause[1:])
            if wanted[0] == lowest[0] and wanted >= lowest:
                return True
        elif clause.startswith(">="):
            if wanted >= as_tuple(clause[2:]):
                return True
        else:
            raise ValueError(f"unsupported range clause {clause!r}")
    return False


@pytest.fixture(scope="module")
def versions() -> dict[str, str]:
    return listed_versions((ROOT / "SYSTEM_REQUIREMENTS.md").read_text(encoding="utf-8"))


def read_yaml(relative: str) -> Any:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def test_every_pinned_tool_has_an_exact_version(versions: dict[str, str]) -> None:
    for name in PINNED_TOOLS:
        assert VERSION.fullmatch(versions.get(name, "")), f"{name}: {versions.get(name)!r}"


def test_pyproject_starts_at_the_lowest_listed_python(versions: dict[str, str]) -> None:
    pyproject = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    lowest = minor(min(versions["Python"], versions["Python on Windows"], key=as_tuple))
    assert pyproject["project"]["requires-python"] == f">={lowest}"
    # Type check and lint as code for that version, so nothing newer slips in.
    assert pyproject["tool"]["mypy"]["python_version"] == lowest
    assert pyproject["tool"]["ruff"]["target-version"] == "py" + lowest.replace(".", "")
    assert pyproject["build-system"]["requires"] == [f"hatchling=={versions['hatchling']}"]


def test_ci_uses_the_listed_versions(versions: dict[str, str]) -> None:
    workflow = read_yaml(".github/workflows/ci.yml")
    pythons: set[str] = set()
    for name, job in workflow["jobs"].items():
        on_windows = str(job["runs-on"]).startswith("windows")
        for step in job["steps"]:
            options = step.get("with", {})
            if "python-version" in options:
                expected = versions["Python on Windows" if on_windows else "Python"]
                assert options["python-version"] == expected, name
                pythons.add(options["python-version"])
            if "node-version" in options:
                assert options["node-version"] == versions["Node.js"], name
        for service in job.get("services", {}).values():
            image, _, tag = service["image"].partition(":")
            if image == "postgres":
                assert tag == versions["PostgreSQL"], name
    assert pythons == {versions["Python"], versions["Python on Windows"]}, "both are tested"

    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lock_installs = re.findall(r"pip install -c requirements\.lock\.txt", text)
    pip_pins = re.findall(r"pip install pip==(\S+)", text)
    assert len(pip_pins) == len(lock_installs) > 0, "pip is pinned before every lock install"
    assert set(pip_pins) == {versions["pip"]}


def test_the_dockerfile_uses_the_listed_versions(versions: dict[str, str]) -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    # The Debian release is part of the tag: it fixes the Tesseract version (trixie: 5.5.0).
    assert re.findall(r"^FROM (\S+)", text, re.MULTILINE) == [
        f"node:{versions['Node.js']}-bookworm-slim",
        f"python:{versions['Python']}-slim-trixie",
    ]
    assert re.findall(r"pip install pip==(\S+)", text) == [versions["pip"]]


def test_compose_uses_the_listed_versions(versions: dict[str, str]) -> None:
    services = read_yaml("docker-compose.yml")["services"]
    assert services["postgres"]["image"] == f"postgres:{versions['PostgreSQL']}"
    assert services["ollama"]["image"] == f"ollama/ollama:{versions['Ollama']}"


def test_package_json_accepts_the_listed_node(versions: dict[str, str]) -> None:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert accepts(package["engines"]["node"], versions["Node.js"])


def test_the_lock_file_names_the_tested_versions(versions: dict[str, str]) -> None:
    lock = (ROOT / "backend" / "requirements.lock.txt").read_text(encoding="utf-8")
    header = "".join(line for line in lock.splitlines(keepends=True) if line.startswith("#"))
    for name in ("Python", "Python on Windows", "PostgreSQL"):
        assert re.search(rf"\b{re.escape(versions[name])}\b", header), name


def test_the_listed_model_is_on_the_allow_list(versions: dict[str, str]) -> None:
    assert versions["Language model"] in ALLOWED_MODELS


@pytest.mark.parametrize(
    ("npm_range", "version", "expected"),
    [
        ("^22.22.2 || ^24.15.0 || >=26.0.0", "22.23.5", True),
        ("^22.22.2 || ^24.15.0 || >=26.0.0", "22.22.1", False),
        ("^22.22.2 || ^24.15.0 || >=26.0.0", "23.0.0", False),
        ("^22.22.2 || ^24.15.0 || >=26.0.0", "24.15.0", True),
        ("^22.22.2 || ^24.15.0 || >=26.0.0", "27.1.0", True),
    ],
)
def test_the_range_check(npm_range: str, version: str, expected: bool) -> None:
    assert accepts(npm_range, version) is expected


def test_an_unknown_range_form_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        accepts("~22.1.0", "22.1.5")


def test_the_table_is_read_up_to_its_end() -> None:
    markdown = (
        "| a | 1 |\n\n## Versions\n\n| Requirement | Version | Why |\n| --- | --- | --- |\n"
        "| Python | `3.13.18` | x |\n| pip | 26.3 | y |\n\nText.\n\n| Other | 9 | z |\n"
    )
    assert listed_versions(markdown) == {"Python": "3.13.18", "pip": "26.3"}
