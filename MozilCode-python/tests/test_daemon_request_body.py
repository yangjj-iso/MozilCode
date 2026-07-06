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
        "/a2a/message:send",
    ],
)
def test_json_object_routes_reject_non_object_json(tmp_path, path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(path, json=[])

    assert response.status_code == 400
    assert response.json()["error"] == "JSON object is required"


@pytest.mark.parametrize(
    ("path", "payload", "error"),
    [
        ("/api/session", {"session_id": 123}, "'session_id' must be a string"),
        ("/api/session", {"work_dir": []}, "'work_dir' must be a string"),
        ("/api/session/missing/mode", {"mode": 1}, "'mode' must be a string"),
        (
            "/api/task",
            {"session_id": 1, "prompt": "go"},
            "'session_id' must be a string",
        ),
        (
            "/api/task",
            {"session_id": "sid", "prompt": []},
            "'prompt' must be a string",
        ),
        (
            "/api/permission/missing",
            {"request_id": 1},
            "'request_id' must be a string",
        ),
        (
            "/api/permission/missing",
            {"request_id": "req", "response": []},
            "'response' must be a string",
        ),
        (
            "/api/askuser/missing",
            {"request_id": 1},
            "'request_id' must be a string",
        ),
        (
            "/api/askuser/missing",
            {"request_id": "req", "answers": []},
            "'answers' must be an object",
        ),
    ],
)
def test_session_routes_reject_invalid_field_types(tmp_path, path, payload, error):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(path, json=payload)

    assert response.status_code == 400
    assert response.json()["error"] == error


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


def test_a2a_message_send_maps_bridge_error(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/a2a/message:send",
            json={"message": {"parts": []}},
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": "message must contain a text part",
        "code": -32602,
    }


def test_a2a_task_routes_map_missing_task_error(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        get_response = client.get("/a2a/tasks/missing")
        cancel_response = client.post("/a2a/tasks/missing:cancel")

    assert get_response.status_code == 404
    assert get_response.json() == {
        "error": "Task not found: missing",
        "code": -32003,
    }
    assert cancel_response.status_code == 404
    assert cancel_response.json() == {
        "error": "Task not found: missing",
        "code": -32003,
    }
