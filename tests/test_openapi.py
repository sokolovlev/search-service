"""docs.json must describe the same API as the application."""

import json
from pathlib import Path

from app.main import create_app

DOCS_PATH = Path(__file__).resolve().parents[1] / "docs.json"


def _operations(spec: dict) -> dict[str, dict[str, list[str]]]:
    return {
        f"{method.upper()} {path}": {
            "responses": sorted(operation["responses"]),
            "parameters": sorted(parameter["name"] for parameter in operation.get("parameters", [])),
        }
        for path, methods in spec["paths"].items()
        for method, operation in methods.items()
    }


def _documented() -> dict:
    return json.loads(DOCS_PATH.read_text(encoding="utf-8"))


def test_docs_json_matches_application(settings):
    documented = _documented()

    assert documented["openapi"].startswith("3.")
    assert _operations(documented) == _operations(create_app(settings).openapi())


async def test_specification_is_served_at_docs_json(client):
    response = await client.get("/docs.json")

    assert response.status_code == 200
    assert response.json()["paths"].keys() == _documented()["paths"].keys()
