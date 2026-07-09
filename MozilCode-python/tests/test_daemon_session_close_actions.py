from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mozilcode.daemon.active_tasks import ActiveTaskRegistry
from mozilcode.daemon.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session.close_actions import close_daemon_session
from mozilcode.permissions import PermissionMode


class _MemoryHub:
    def __init__(self) -> None:
        self.shutdown_called = False

    async def shutdown(self) -> None:
        self.shutdown_called = True


class _Records:
    def __init__(self) -> None:
        self.closed: list[str] = []

    def close(self, sid: str) -> None:
        self.closed.append(sid)


async def _blocked(release: asyncio.Event) -> None:
    await release.wait()


@pytest.mark.asyncio
async def test_close_daemon_session_cancels_task_and_clears_runtime_state() -> None:
    sid = "sid-close"
    active_tasks = ActiveTaskRegistry()
    release = asyncio.Event()
    task = asyncio.create_task(_blocked(release))
    active_tasks.register(sid, "task-1", task)
    session_mgr = SessionManager()
    await session_mgr.create_session(sid, object(), object())
    memory_hub = _MemoryHub()
    runtimes = {
        sid: SimpleNamespace(agent=SimpleNamespace(memory_hub=memory_hub)),
    }
    records = _Records()
    pre_plan_modes = {sid: PermissionMode.BYPASS}
    pending_prompts = PendingPromptRegistry()
    pending_prompts.record(sid, "req-1", {"type": "PermissionRequest"})

    await close_daemon_session(
        sid,
        active_tasks=active_tasks,
        session_mgr=session_mgr,
        runtimes=runtimes,
        records=records,
        pre_plan_modes=pre_plan_modes,
        pending_prompts=pending_prompts,
    )

    assert task.cancelled()
    assert active_tasks.task_id(sid) == ""
    assert await session_mgr.get_session(sid) is None
    assert runtimes == {}
    assert memory_hub.shutdown_called is True
    assert records.closed == [sid]
    assert pre_plan_modes == {}
    assert pending_prompts.events(sid) == []
    assert sid not in pending_prompts


@pytest.mark.asyncio
async def test_close_daemon_session_closes_records_without_runtime() -> None:
    records = _Records()

    await close_daemon_session(
        "sid-missing-runtime",
        active_tasks=ActiveTaskRegistry(),
        session_mgr=SessionManager(),
        runtimes={},
        records=records,
        pre_plan_modes={},
        pending_prompts=PendingPromptRegistry(),
    )

    assert records.closed == ["sid-missing-runtime"]


@pytest.mark.asyncio
async def test_close_daemon_session_validates_session_id_before_cleanup() -> None:
    records = _Records()
    pending_prompts = PendingPromptRegistry()
    pending_prompts.record("bad.id", "req-1", {"type": "PermissionRequest"})

    with pytest.raises(ValueError, match="session_id must be"):
        await close_daemon_session(
            "bad.id",
            active_tasks=ActiveTaskRegistry(),
            session_mgr=SessionManager(),
            runtimes={},
            records=records,
            pre_plan_modes={"bad.id": PermissionMode.DEFAULT},
            pending_prompts=pending_prompts,
        )

    assert records.closed == []
    assert pending_prompts.events("bad.id") == [{"type": "PermissionRequest"}]
