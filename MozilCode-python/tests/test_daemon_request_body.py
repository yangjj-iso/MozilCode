from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.request_body import (
    parse_json_object,
    required_string_field,
    string_field,
    string_mapping_field,
)
from mozilcode.daemon.server import create_app
from mozilcode.daemon.session_store import SessionStore


def _app(tmp_path):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    return create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )


class _RunningTask:
    def done(self) -> bool:
        return False


class _JsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_parse_json_object_returns_typed_value():
    parsed = await parse_json_object(
        _JsonRequest({"name": "main"}),
        lambda body: string_field(body, "name"),
    )

    assert parsed.ok
    assert parsed.unwrap() == "main"


@pytest.mark.asyncio
async def test_parse_json_object_rejects_blank_required_string():
    parsed = await parse_json_object(
        _JsonRequest({"name": "   "}),
        lambda body: required_string_field(body, "name"),
    )

    assert not parsed.ok
    assert parsed.error is not None
    assert parsed.error.status_code == 400
    assert json.loads(parsed.error.body) == {"error": "'name' is required"}


@pytest.mark.asyncio
async def test_parse_json_object_maps_field_error_to_bad_request():
    parsed = await parse_json_object(
        _JsonRequest({"name": 123}),
        lambda body: string_field(body, "name"),
    )

    assert not parsed.ok
    assert parsed.error is not None
    assert parsed.error.status_code == 400
    assert json.loads(parsed.error.body) == {"error": "'name' must be a string"}


@pytest.mark.asyncio
async def test_parse_json_object_rejects_non_string_mapping_values():
    parsed = await parse_json_object(
        _JsonRequest({"answers": {"language": ["Python"]}}),
        lambda body: string_mapping_field(body, "answers"),
    )

    assert not parsed.ok
    assert parsed.error is not None
    assert parsed.error.status_code == 400
    assert json.loads(parsed.error.body) == {
        "error": "'answers' must be an object of strings"
    }


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


@pytest.mark.parametrize("path", ["/api/session", "/a2a/message:send"])
def test_json_object_routes_reject_invalid_json_encoding(tmp_path, path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            path,
            content=b"\xff",
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
        ("/api/session/missing/mode", {}, "'mode' is required"),
        ("/api/session/missing/mode", {"mode": "   "}, "'mode' is required"),
        ("/api/session/missing/mode", {"mode": 1}, "'mode' must be a string"),
        (
            "/api/session/missing/mode",
            {"mode": "invalid"},
            (
                "'mode' must be one of: acceptEdits, bypassPermissions, "
                "custom, default, do, dontAsk, plan"
            ),
        ),
        (
            "/api/task",
            {"session_id": 1, "prompt": "go"},
            "'session_id' must be a string",
        ),
        (
            "/api/task",
            {"session_id": "", "prompt": "go"},
            "'session_id' is required",
        ),
        (
            "/api/task",
            {"session_id": "sid", "prompt": []},
            "'prompt' must be a string",
        ),
        (
            "/api/task",
            {"session_id": "sid", "prompt": "   "},
            "'prompt' is required",
        ),
        (
            "/api/permission/missing",
            {},
            "'request_id' is required",
        ),
        (
            "/api/permission/missing",
            {"request_id": 1},
            "'request_id' must be a string",
        ),
        (
            "/api/permission/missing",
            {"request_id": " "},
            "'request_id' is required",
        ),
        (
            "/api/permission/missing",
            {"request_id": "req", "response": []},
            "'response' must be a string",
        ),
        (
            "/api/permission/missing",
            {"request_id": "req", "response": "maybe"},
            "'response' must be one of: allow, allow_always, deny",
        ),
        (
            "/api/askuser/missing",
            {"request_id": 1},
            "'request_id' must be a string",
        ),
        (
            "/api/askuser/missing",
            {"request_id": " ", "answers": {}},
            "'request_id' is required",
        ),
        (
            "/api/askuser/missing",
            {"request_id": "req", "answers": []},
            "'answers' must be an object",
        ),
        (
            "/api/askuser/missing",
            {"request_id": "req", "answers": {"language": []}},
            "'answers' must be an object of strings",
        ),
        (
            "/api/session/missing/worktrees",
            {"name": 123},
            "'name' must be a string",
        ),
        (
            "/api/session/missing/worktrees",
            {"name": "   "},
            "'name' is required",
        ),
        (
            "/api/session/missing/worktrees",
            {"name": "feature", "base_branch": []},
            "'base_branch' must be a string",
        ),
        (
            "/api/session/missing/worktrees/exit",
            {"remove": "false"},
            "'remove' must be a boolean",
        ),
        (
            "/api/session/missing/worktrees/exit",
            {"discard": "true"},
            "'discard' must be a boolean",
        ),
    ],
)
def test_session_routes_reject_invalid_field_types(tmp_path, path, payload, error):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(path, json=payload)

    assert response.status_code == 400
    assert response.json()["error"] == error


def test_create_session_rejects_path_traversal_session_id(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/session", json={"session_id": "../escape"})

    assert response.status_code == 400
    assert response.json()["error"].startswith("session_id must be")
    assert not (tmp_path / "escape").exists()
    assert app.state.server.list_session_infos() == []


def test_create_session_accepts_safe_custom_session_id(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/session", json={"session_id": "custom-1"})

    assert response.status_code == 200
    assert response.json()["session_id"] == "custom-1"
    assert (tmp_path / "sessions" / "custom-1" / "meta.json").exists()


def test_create_session_generates_safe_default_session_id(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/session", json={})

    assert response.status_code == 200
    body = response.json()
    session_id = body["session_id"]
    assert len(session_id) == 12
    assert app.state.server.has_session(session_id)
    assert (tmp_path / "sessions" / session_id / "meta.json").exists()


def test_create_session_rejects_duplicate_session_id_without_resetting_state(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        first = client.post("/api/session", json={"session_id": "custom-1"})
        app.state.server._records.event_logs["custom-1"].append({"type": "Existing"})
        app.state.server._records.session_meta["custom-1"]["title"] = "kept"

        second = client.post("/api/session", json={"session_id": "custom-1"})

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"] == "session already exists: custom-1"
    assert app.state.server._records.event_logs["custom-1"] == [{"type": "Existing"}]
    assert app.state.server._records.session_meta["custom-1"]["title"] == "kept"


def test_start_task_rejects_active_session_task(tmp_path):
    app = _app(tmp_path)
    app.state.server._active_tasks.tasks["busy"] = _RunningTask()

    with TestClient(app) as client:
        response = client.post(
            "/api/task",
            json={"session_id": "busy", "prompt": "second"},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "task already running"


def test_close_session_rejects_invalid_session_id(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.delete("/api/session/bad.id")

    assert response.status_code == 400
    assert response.json()["error"].startswith("session_id must be")


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


def test_a2a_json_rpc_maps_invalid_json_encoding_to_parse_error(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/a2a/rpc",
            content=b"\xff",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }


def test_a2a_json_rpc_rejects_empty_batch(tmp_path):
    app = _app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/a2a/rpc", json=[])

    assert response.status_code == 200
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "Invalid JSON-RPC request"},
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
