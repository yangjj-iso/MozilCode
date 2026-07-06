from __future__ import annotations

import pytest

from mozilcode.a2a.bridge import (
    A2ABridge,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_INPUT_REQUIRED,
)
from mozilcode.config import AppConfig, ProviderConfig


class _FakeDaemon:
    def __init__(self) -> None:
        self.work_dir = "."
        self.config = AppConfig(
            providers=[
                ProviderConfig(
                    name="test",
                    protocol="openai",
                    base_url="http://127.0.0.1:8080/v1",
                    model="test-model",
                )
            ]
        )
        self.logs: dict[str, list[dict | None]] = {}
        self.sessions: list[str] = []
        self._task_counter = 0

    async def init_session(self, work_dir=None):
        sid = f"session-{len(self.sessions) + 1}"
        self.sessions.append(sid)
        self.logs[sid] = []
        return sid

    def get_event_log(self, sid):
        return self.logs.get(sid)

    async def start_task(self, sid, prompt):
        self._task_counter += 1
        task_id = f"task-{self._task_counter}"
        self.logs[sid].append({"type": "UserMessage", "task_id": task_id, "data": {"content": prompt}})
        self.logs[sid].append({"type": "StreamText", "task_id": task_id, "data": {"text": "echo: "}})
        self.logs[sid].append({"type": "StreamText", "task_id": task_id, "data": {"text": prompt}})
        self.logs[sid].append({"type": "LoopComplete", "task_id": task_id, "data": {}})
        return task_id

    def cancel_active_task(self, sid):
        self.logs[sid].append({"type": "TaskCancelled", "task_id": "task-x", "data": {}})
        return True


class _ScriptedDaemon(_FakeDaemon):
    def __init__(self, script):
        super().__init__()
        self.script = script

    async def start_task(self, sid, prompt):
        self._task_counter += 1
        task_id = f"task-{self._task_counter}"
        self.logs[sid].extend(self.script(task_id, prompt))
        return task_id


@pytest.mark.asyncio
async def test_a2a_message_send_waits_and_collects_text():
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    result = await bridge.send_message({
        "message": {
            "messageId": "m1",
            "contextId": "ctx-1",
            "parts": [{"kind": "text", "text": "hello"}],
        },
        "configuration": {"returnImmediately": False},
    })

    assert result["status"]["state"] == TASK_COMPLETED
    assert result["contextId"] == "ctx-1"
    assert result["artifacts"][0]["parts"][0]["text"] == "echo: hello"


@pytest.mark.asyncio
async def test_a2a_json_rpc_send_and_get_task():
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    send = await bridge.handle_json_rpc({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "m1",
                "parts": [{"kind": "text", "text": "rpc"}],
            },
            "configuration": {"returnImmediately": False},
        },
    })
    task_id = send["result"]["id"]

    get = await bridge.handle_json_rpc({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tasks/get",
        "params": {"id": task_id},
    })

    assert get["result"]["id"] == task_id
    assert get["result"]["status"]["state"] == TASK_COMPLETED


@pytest.mark.asyncio
async def test_a2a_task_enters_input_required_for_interactive_events():
    bridge = A2ABridge(
        _ScriptedDaemon(
            lambda task_id, _prompt: [
                {"type": "PermissionRequest", "task_id": task_id, "data": {}},
            ]
        ),
        default_wait_timeout=1,
    )

    result = await bridge.send_message({
        "message": {"parts": [{"kind": "text", "text": "needs input"}]},
        "configuration": {"returnImmediately": True},
    })

    assert result["status"]["state"] == TASK_INPUT_REQUIRED
    assert "requires interactive input" in result["status"]["message"]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_a2a_task_ignores_foreign_events_before_failure():
    bridge = A2ABridge(
        _ScriptedDaemon(
            lambda task_id, _prompt: [
                {"type": "StreamText", "task_id": "other", "data": {"text": "ignore"}},
                {"type": "ErrorEvent", "task_id": task_id, "data": {"message": "boom"}},
            ]
        ),
        default_wait_timeout=1,
    )

    result = await bridge.send_message({
        "message": {"parts": [{"kind": "text", "text": "fail"}]},
        "configuration": {"returnImmediately": True},
    })

    assert result["status"]["state"] == TASK_FAILED
    assert result["metadata"]["error"] == "boom"
    assert "artifacts" not in result


@pytest.mark.asyncio
async def test_a2a_task_ignores_malformed_event_data():
    bridge = A2ABridge(
        _ScriptedDaemon(
            lambda task_id, _prompt: [
                {"type": "StreamText", "task_id": task_id, "data": "bad"},
                {"type": "StreamText", "task_id": task_id, "data": {"text": "ok"}},
                {"type": "LoopComplete", "task_id": task_id, "data": {}},
            ]
        ),
        default_wait_timeout=1,
    )

    result = await bridge.send_message({
        "message": {"parts": [{"kind": "text", "text": "malformed"}]},
        "configuration": {"returnImmediately": True},
    })

    assert result["status"]["state"] == TASK_COMPLETED
    assert result["artifacts"][0]["parts"][0]["text"] == "ok"


@pytest.mark.asyncio
async def test_a2a_task_metadata_cannot_override_internal_fields():
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    result = await bridge.send_message({
        "message": {
            "parts": [{"kind": "text", "text": "metadata"}],
        },
        "metadata": {
            "source": "user-source",
            "session_id": "fake-session",
            "internal_task_id": "fake-task",
            "ticket": "T-1",
        },
        "configuration": {"returnImmediately": False},
    })

    assert result["metadata"]["source"] == "a2a"
    assert result["metadata"]["session_id"] == "session-1"
    assert result["metadata"]["internal_task_id"] == "task-1"
    assert result["metadata"]["ticket"] == "T-1"


@pytest.mark.asyncio
async def test_a2a_json_rpc_rejects_non_object_metadata():
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    response = await bridge.handle_json_rpc({
        "jsonrpc": "2.0",
        "id": 7,
        "method": "message/send",
        "params": {
            "message": {"parts": [{"kind": "text", "text": "hello"}]},
            "metadata": "bad",
        },
    })

    assert response["id"] == 7
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "metadata must be an object"
    assert bridge._server.sessions == []


@pytest.mark.asyncio
async def test_a2a_json_rpc_rejects_non_object_configuration():
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    response = await bridge.handle_json_rpc({
        "jsonrpc": "2.0",
        "id": 8,
        "method": "message/send",
        "params": {
            "message": {"parts": [{"kind": "text", "text": "hello"}]},
            "configuration": "bad",
        },
    })

    assert response["id"] == 8
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "configuration must be an object"
    assert bridge._server.sessions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params", "message"),
    [
        ("message/send", [], "message/send params must be an object"),
        ("tasks/get", False, "task params must be an object"),
        ("tasks/get", "", "task id is required"),
    ],
)
async def test_a2a_json_rpc_preserves_invalid_params_types(
    method, params, message
):
    bridge = A2ABridge(_FakeDaemon(), default_wait_timeout=1)

    response = await bridge.handle_json_rpc({
        "jsonrpc": "2.0",
        "id": 9,
        "method": method,
        "params": params,
    })

    assert response["id"] == 9
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == message
    assert bridge._server.sessions == []
