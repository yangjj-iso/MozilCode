from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import create_app
from mozilcode.daemon.responses import DaemonActionResult
from mozilcode.daemon.server_state import DaemonServer
from mozilcode.permissions import PermissionMode


class _Registry:
    def list_tools(self):
        return []

    def is_enabled(self, _name):
        return False


class _Agent:
    permission_mode = PermissionMode.DEFAULT
    plan_mode = False
    context_window = 128_000
    total_input_tokens = 0
    total_output_tokens = 0
    registry = _Registry()
    memory_hub = None


class _Conversation:
    def current_tokens(self):
        return 0


class _Provider:
    name = "local"
    protocol = "openai-compat"
    model = "smoke-model"

    def get_context_window(self):
        return 128_000


class _TaskManager:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def list_tasks(self):
        return [
            SimpleNamespace(
                id="task-1",
                name="lint",
                task="run lint",
                status="running",
                result="",
                start_time=10.0,
                end_time=12.5,
                progress=SimpleNamespace(
                    input_tokens=13,
                    output_tokens=5,
                    tool_call_count=2,
                    last_activity="Bash",
                ),
            )
        ]

    def cancel(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return task_id == "task-1"


def _server_with_tasks(tmp_path) -> tuple[DaemonServer, str, _TaskManager]:
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    server = DaemonServer(AppConfig(providers=[provider]), str(tmp_path))
    sid = "session-tasks"
    task_manager = _TaskManager()
    server._agents[sid] = (
        _Agent(),
        SimpleNamespace(provider=_Provider(), task_manager=task_manager),
        _Conversation(),
    )
    server._event_logs[sid] = []
    server._session_meta[sid] = {"work_dir": str(tmp_path), "title": "tasks"}
    server._persisted_count[sid] = 0
    return server, sid, task_manager


@pytest.mark.asyncio
async def test_list_background_tasks_serializes_task_manager_payload(tmp_path):
    server, sid, _task_manager = _server_with_tasks(tmp_path)

    result = await server.list_background_tasks(sid)

    assert result.status_code == 200
    assert result.payload == {
        "tasks": [
            {
                "id": "task-1",
                "name": "lint",
                "task": "run lint",
                "status": "running",
                "result": "",
                "elapsed": 2.5,
                "input_tokens": 13,
                "output_tokens": 5,
                "tool_call_count": 2,
                "last_activity": "Bash",
            }
        ]
    }


@pytest.mark.asyncio
async def test_cancel_background_task_delegates_to_task_manager(tmp_path):
    server, sid, task_manager = _server_with_tasks(tmp_path)

    result = await server.cancel_background_task(sid, "task-1")

    assert result == DaemonActionResult({"cancelled": True})
    assert task_manager.cancelled == ["task-1"]


@pytest.mark.asyncio
async def test_background_task_actions_return_404_for_missing_session(tmp_path):
    server = DaemonServer(AppConfig(providers=[]), str(tmp_path))

    listed = await server.list_background_tasks("missing")
    cancelled = await server.cancel_background_task("missing", "task-1")

    assert listed == DaemonActionResult(
        {"error": "session not found"},
        status_code=404,
    )
    assert cancelled == DaemonActionResult(
        {"error": "session not found"},
        status_code=404,
    )


def test_background_task_route_uses_server_action_result(tmp_path, monkeypatch):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    async def fake_cancel_background_task(sid: str, task_id: str):
        assert (sid, task_id) == ("sid-1", "task-7")
        return DaemonActionResult({"cancelled": False}, status_code=200)

    monkeypatch.setattr(
        app.state.server,
        "cancel_background_task",
        fake_cancel_background_task,
    )

    with TestClient(app) as client:
        response = client.post("/api/session/sid-1/tasks/task-7/cancel")

    assert response.status_code == 200
    assert response.json() == {"cancelled": False}
