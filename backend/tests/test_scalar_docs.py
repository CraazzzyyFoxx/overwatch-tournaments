from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.core.scalar import _prefix_root_path, register_scalar_docs


def test_scalar_docs_route_uses_request_root_path() -> None:
    app = FastAPI(title="Test API")
    register_scalar_docs(app)
    client = TestClient(app, root_path="/api/test")

    response = client.get("/scalar")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/api/test/openapi.json" in response.text


def test_scalar_docs_route_is_hidden_from_openapi_schema() -> None:
    app = FastAPI(title="Test API")
    register_scalar_docs(app)

    assert "/scalar" not in app.openapi()["paths"]


def test_prefix_root_path_normalizes_relative_values() -> None:
    assert _prefix_root_path("api/test/", "openapi.json") == "/api/test/openapi.json"
