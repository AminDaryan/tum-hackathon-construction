"""``/openapi.json`` describes every response: a schema for each JSON success response, and the
error envelope for every error response. The REST API page names the same success schemas."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.models.finding_category import FindingCategory, FindingCategoryKey
from tests.unit.api.conftest import MakeClient

REST_API_PAGE = Path(__file__).resolve().parents[4] / "docs" / "api" / "rest-api.md"
_DOCUMENTED_ROUTE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`?\s]*)")
_DOCUMENTED_SCHEMA = re.compile(r"`([A-Z][A-Za-z0-9]*)`")


def _operations(spec: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (f"{method.upper()} {path}", operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
    ]


def _resolves(spec: dict[str, Any], schema: dict[str, Any]) -> bool:
    ref = schema.get("$ref")
    if ref is None:
        return bool(schema)
    name = ref.removeprefix("#/components/schemas/")
    return name in spec["components"]["schemas"]


def test_every_json_success_response_has_a_schema(make_client: MakeClient) -> None:
    spec = make_client().get("/openapi.json").json()
    operations = _operations(spec)
    assert len(operations) >= 17
    problems = []
    for name, operation in operations:
        successes = {
            code: response
            for code, response in operation["responses"].items()
            if code.startswith("2")
        }
        if not successes:
            problems.append(f"{name}: no success response")
        for code, response in successes.items():
            content = response.get("content", {})
            if not content:
                problems.append(f"{name} {code}: no content")
            json_content = content.get("application/json")
            if json_content is not None and not _resolves(spec, json_content.get("schema") or {}):
                problems.append(f"{name} {code}: application/json without a schema")
    assert problems == []


def test_errors_are_documented_as_the_envelope(make_client: MakeClient) -> None:
    spec = make_client().get("/openapi.json").json()
    for name, operation in _operations(spec):
        errors = {code: r for code, r in operation["responses"].items() if code[0] in "45"}
        assert {"4XX", "5XX"} <= set(errors), name
        for response in errors.values():
            schema = response["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, name
    # FastAPI's own validation error shape is not what the API sends (it sends the envelope).
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_the_finding_category_is_part_of_the_contract(make_client: MakeClient) -> None:
    """Typed clients read the computed field, its filter and its counts from ``/openapi.json``:
    the six categories, and ``none`` where filters and counts name the findings without one."""
    spec = make_client().get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert schemas["FindingCategory"]["enum"] == [category.value for category in FindingCategory]
    assert schemas["FindingCategoryKey"]["enum"] == [key.value for key in FindingCategoryKey]
    category = "#/components/schemas/FindingCategory"
    key = "#/components/schemas/FindingCategoryKey"
    for name in ("ValidationIssue", "IssueView"):
        field = schemas[name]["properties"]["finding_category"]
        assert field["anyOf"] == [{"$ref": category}, {"type": "null"}], name
        assert field["readOnly"] is True, name
        assert "finding_category" in schemas[name]["required"], name
    counts = schemas["IssueCountsSummary"]["properties"]["by_finding_category"]
    assert counts["propertyNames"] == {"$ref": key}
    assert counts["additionalProperties"] == {"type": "integer"}
    parameters = spec["paths"]["/api/v1/validation-runs/{run_id}/issues"]["get"]["parameters"]
    (parameter,) = [p for p in parameters if p["name"] == "finding_category"]
    assert (parameter["in"], parameter["required"]) == ("query", False)
    assert parameter["schema"]["anyOf"][0] == {"type": "array", "items": {"$ref": key}}
    # `none` is not only "reading the file": a detector the tables do not know has no category.
    for description in (parameter["description"], counts["description"]):
        assert "reading the file" in description
        assert "a detector the category tables do not know" in description


def test_health_names_the_default_profile_and_the_sign_in(make_client: MakeClient) -> None:
    health = make_client(default_profile_id="generic").get("/api/v1/health").json()
    assert health["default_profile_id"] == "generic" and health["auth_required"] is False


def _path_shape(path: str) -> str:
    """``path`` with every path parameter's name dropped (the page and the code may name them
    differently, as ``{format}`` and ``{format_id}``)."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def _endpoint_table(page: str) -> list[tuple[list[tuple[str, str]], set[str]]]:
    """The rows of the page's "Endpoints" table: the routes named in the first column, and the
    schema names (backticked words in CamelCase) of the second."""
    section = page.split("\n## Endpoints\n", 1)[1].split("\n#", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0].startswith("`"):
            routes = _DOCUMENTED_ROUTE.findall(cells[0])
            rows.append((routes, set(_DOCUMENTED_SCHEMA.findall(cells[1]))))
    return rows


def test_the_rest_api_page_names_the_response_schemas(make_client: MakeClient) -> None:
    """The endpoint table of ``docs/api/rest-api.md`` names, for the routes of each row, the
    schemas of their JSON success responses, exactly as ``/openapi.json`` does."""
    spec = make_client().get("/openapi.json").json()
    served = {
        (method.upper(), _path_shape(path)): {
            content["schema"]["$ref"].removeprefix("#/components/schemas/")
            for code, response in operation["responses"].items()
            if code.startswith("2")
            for content in response.get("content", {}).values()
            if "$ref" in content.get("schema", {})
        }
        for path, item in spec["paths"].items()
        for method, operation in item.items()
    }
    rows = _endpoint_table(REST_API_PAGE.read_text(encoding="utf-8"))
    assert sum(len(routes) for routes, _ in rows) >= 17
    problems = []
    for routes, names in rows:
        answered: set[str] = set()
        for method, path in routes:
            key = (method, _path_shape(f"/api/v1{path}"))
            if key not in served:
                problems.append(f"{method} {path}: no such route")
            answered |= served.get(key, set())
        if names != answered:
            listed = ", ".join(f"{method} {path}" for method, path in routes)
            problems.append(f"{listed}: the page names {sorted(names)}, the API {sorted(answered)}")
    assert problems == []
