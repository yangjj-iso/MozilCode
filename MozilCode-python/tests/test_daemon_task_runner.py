from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.agent import StreamText
from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server_state import DaemonServer, DaemonSessionRuntime
from mozilcode.daemon.session_store import SessionStore
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

    async def run(self, _conversation):
        yield StreamText("done")


class _Conversation:
    def __init__(self) -> None:
        self.user_messages: list[str] = []

    def add_user_message(self, prompt: str) -> None:
        self.user_messages.append(prompt)

    def current_tokens(self):
        return 0


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )


@pytest.mark.asyncio
async def test_start_task_runs_agent_and_cleans_active_task(tmp_path):
    provider = _provider()
    server = DaemonServer(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )
    sid = "sid-task"
    conversation = _Conversation()
    server._agents[sid] = DaemonSessionRuntime(
        _Agent(),
        SimpleNamespace(provider=provider),
        conversation,
    )
    server._event_logs[sid] = []
    server._session_meta[sid] = {"work_dir": str(tmp_path), "title": ""}
    server._persisted_count[sid] = 0

    task_id = await server.start_task(sid, "run task")
    task = server._tasks[sid]

    await task

    assert conversation.user_messages == ["run task"]
    assert server._session_meta[sid]["title"] == "run task"
    assert sid not in server._tasks
    assert sid not in server._active_task_ids
    assert server._event_logs[sid] == [
        {"type": "UserMessage", "task_id": task_id, "data": {"content": "run task"}},
        {"type": "StreamText", "task_id": task_id, "data": {"text": "done"}},
        {"type": "LoopComplete", "task_id": task_id, "data": {}},
    ]
