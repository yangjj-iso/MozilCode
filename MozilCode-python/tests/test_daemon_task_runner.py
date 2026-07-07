from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mozilcode.agent import PermissionRequest, PermissionResponse, StreamText
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


class _PermissionAgent(_Agent):
    def __init__(self, future) -> None:
        self.future = future

    async def run(self, _conversation):
        yield PermissionRequest(
            tool_name="WriteFile",
            description="write file",
            future=self.future,
        )


class _BlockingAgent(_Agent):
    def __init__(self, started: asyncio.Event) -> None:
        self.started = started
        self.release = asyncio.Event()

    async def run(self, _conversation):
        self.started.set()
        await self.release.wait()
        yield StreamText("released")


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


async def _create_server_with_agent(tmp_path, agent, conversation):
    provider = _provider()
    server = DaemonServer(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )
    sid = "sid-task"
    server._agents[sid] = DaemonSessionRuntime(
        agent,
        SimpleNamespace(provider=provider),
        conversation,
    )
    server._event_logs[sid] = []
    server._session_meta[sid] = {"work_dir": str(tmp_path), "title": ""}
    server._persisted_count[sid] = 0
    await server.session_mgr.create_session(sid, agent, conversation)
    return server, sid


@pytest.mark.asyncio
async def test_start_task_runs_agent_and_cleans_active_task(tmp_path):
    conversation = _Conversation()
    server, sid = await _create_server_with_agent(tmp_path, _Agent(), conversation)

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


@pytest.mark.asyncio
async def test_start_task_rejects_concurrent_session_task(tmp_path):
    started = asyncio.Event()
    agent = _BlockingAgent(started)
    conversation = _Conversation()
    server, sid = await _create_server_with_agent(tmp_path, agent, conversation)

    first_task_id = await server.start_task(sid, "first")
    await started.wait()

    with pytest.raises(ValueError, match="task already running"):
        await server.start_task(sid, "second")

    assert server._active_task_ids[sid] == first_task_id
    assert conversation.user_messages == ["first"]

    agent.release.set()
    await server._tasks[sid]


@pytest.mark.asyncio
async def test_start_task_registers_pending_permission_prompt(tmp_path):
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    conversation = _Conversation()
    server, sid = await _create_server_with_agent(
        tmp_path,
        _PermissionAgent(future),
        conversation,
    )

    task_id = await server.start_task(sid, "needs permission")
    await server._tasks[sid]

    request_id = str(id(future))
    session = await server.session_mgr.get_session(sid)
    assert session is not None
    assert session._pending_futures[request_id] is future
    assert server.pending_prompt_events(sid) == [
        {
            "type": "PermissionRequest",
            "task_id": task_id,
            "data": {
                "tool_name": "WriteFile",
                "description": "write file",
                "request_id": request_id,
                "resolved": False,
            },
        }
    ]


async def _register_pending_future(
    server: DaemonServer,
    sid: str,
    request_id: str,
    event_type: str = "PermissionRequest",
) -> asyncio.Future:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    session = await server.session_mgr.get_session(sid)
    assert session is not None
    session.register_future(request_id, future)
    server._pending_prompts.record(
        sid,
        request_id,
        {
            "type": event_type,
            "data": {"request_id": request_id, "resolved": False},
        },
    )
    return future


@pytest.mark.asyncio
async def test_resolve_permission_clears_pending_prompt_and_emits_event(tmp_path):
    conversation = _Conversation()
    server, sid = await _create_server_with_agent(tmp_path, _Agent(), conversation)
    future = await _register_pending_future(server, sid, "req-permission")

    ok = await server.resolve_permission(sid, "req-permission", "allow")

    assert ok is True
    assert future.result() is PermissionResponse.ALLOW
    assert server.pending_prompt_events(sid) == []
    assert server._event_logs[sid] == [
        {
            "type": "PermissionResolved",
            "data": {"request_id": "req-permission"},
        }
    ]


@pytest.mark.asyncio
async def test_resolve_askuser_clears_pending_prompt_and_emits_event(tmp_path):
    conversation = _Conversation()
    server, sid = await _create_server_with_agent(tmp_path, _Agent(), conversation)
    future = await _register_pending_future(
        server,
        sid,
        "req-ask",
        "AskUserRequest",
    )

    ok = await server.resolve_askuser(sid, "req-ask", {"language": "Python"})

    assert ok is True
    assert future.result() == {"language": "Python"}
    assert server.pending_prompt_events(sid) == []
    assert server._event_logs[sid] == [
        {
            "type": "AskUserResolved",
            "data": {"request_id": "req-ask"},
        }
    ]


@pytest.mark.asyncio
async def test_close_session_clears_pending_prompt_state(tmp_path):
    conversation = _Conversation()
    server, sid = await _create_server_with_agent(tmp_path, _Agent(), conversation)
    future = await _register_pending_future(server, sid, "req-close")

    await server.close_session(sid)

    assert future.cancelled()
    assert server.pending_prompt_events(sid) == []
    assert sid not in server._pending_prompts
