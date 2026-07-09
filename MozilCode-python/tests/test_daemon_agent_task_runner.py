from __future__ import annotations

import asyncio

import pytest

from mozilcode.agent import PermissionRequest, StreamText
from mozilcode.daemon.tasks.active import ActiveTaskRegistry
from mozilcode.daemon.tasks.runner import AgentTaskRunner
from mozilcode.daemon.tasks.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.session import SessionManager


class _Conversation:
    def __init__(self) -> None:
        self.user_messages: list[str] = []

    def add_user_message(self, prompt: str) -> None:
        self.user_messages.append(prompt)


class _Agent:
    async def run(self, _conversation):
        yield StreamText("done")


class _PermissionAgent:
    def __init__(self, future: asyncio.Future) -> None:
        self.future = future

    async def run(self, _conversation):
        yield PermissionRequest(
            tool_name="WriteFile",
            description="write file",
            future=self.future,
        )


def _runner():
    active_tasks = ActiveTaskRegistry()
    session_mgr = SessionManager()
    pending_prompts = PendingPromptRegistry()
    events: dict[str, list[dict | None]] = {}
    persisted: list[str] = []
    titles: list[tuple[str, str]] = []

    def emit_event(sid: str, event: dict | None) -> None:
        events.setdefault(sid, []).append(event)

    runner = AgentTaskRunner(
        active_tasks=active_tasks,
        session_mgr=session_mgr,
        pending_prompts=pending_prompts,
        emit_event=emit_event,
        persist_events=persisted.append,
        set_title_from_prompt=lambda sid, prompt: titles.append((sid, prompt)),
    )
    return runner, active_tasks, session_mgr, pending_prompts, events, persisted, titles


@pytest.mark.asyncio
async def test_agent_task_runner_emits_events_and_cleans_active_task() -> None:
    runner, active_tasks, _session_mgr, _pending, events, persisted, titles = _runner()
    conversation = _Conversation()

    task_id = runner.start("sid", "hello", _Agent(), conversation)
    task = active_tasks.tasks["sid"]
    await task

    assert conversation.user_messages == ["hello"]
    assert titles == [("sid", "hello")]
    assert persisted == ["sid"]
    assert "sid" not in active_tasks.tasks
    assert events["sid"] == [
        {"type": "UserMessage", "task_id": task_id, "data": {"content": "hello"}},
        {"type": "StreamText", "task_id": task_id, "data": {"text": "done"}},
        {"type": "LoopComplete", "task_id": task_id, "data": {}},
    ]


@pytest.mark.asyncio
async def test_agent_task_runner_registers_pending_permission_future() -> None:
    runner, active_tasks, session_mgr, pending, _events, _persisted, _titles = _runner()
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    agent = _PermissionAgent(future)
    conversation = _Conversation()
    await session_mgr.create_session("sid", agent, conversation)

    task_id = runner.start("sid", "needs permission", agent, conversation)
    await active_tasks.tasks["sid"]

    request_id = str(id(future))
    session = await session_mgr.get_session("sid")
    assert session is not None
    assert session._pending_futures[request_id] is future
    assert pending.events("sid") == [
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
