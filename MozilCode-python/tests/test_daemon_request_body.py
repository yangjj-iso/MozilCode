from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import create_app


def _app(tmp_path):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    return create_app(AppConfig(providers=[provider]), str(tmp_path))


@pytest.mark.parametrize(
    "path",
    [
        "/api/session",
        "/api/session/missing/mode",
        "/api/task",
        "/api/permission/missing",
        "/api/askuser/missing",
        "/api/session/missing/worktrees",
        "/api/session/missing/worktrees/exit",
        "/api/settings/mcp",
        "/api/skills",
        "/a2a/message:send",
    ],
)
def test_json_object_routes_reject_malformed_json(tmp_path, path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            path,
            content="{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid JSON body"


@pytest.mark.parametrize(
    "path",
    [
        "/api/session",
        "/api/session/missing/mode",
        "/api/task",
        "/api/permission/missing",
        "/api/askuser/missing",
        "/api/session/missing/worktrees",
        "/api/session/missing/worktrees/exit",
        "/api/settings/mcp",
        "/api/skills",
        "/a2a/message:send",
    ],
)
def test_json_object_routes_reject_non_object_json(tmp_path, path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(path, json=[])

    assert response.status_code == 400
    assert response.json()["error"] == "JSON object is required"


def test_config_route_reports_json_errors_in_public_config_shape(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/config",
            content="{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    data = response.json()
    assert data["configured"] is True
    assert data["error"] == "Invalid JSON body"


def test_memory_settings_route_reports_json_errors_in_settings_shape(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/settings/memory", json=[])

    assert response.status_code == 400
    data = response.json()
    assert data["enabled"] is True
    assert data["error"] == "JSON object is required"


def test_a2a_json_rpc_keeps_json_rpc_parse_error_shape(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/a2a/rpc",
            content="{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }
