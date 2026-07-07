from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace

import pytest

from mozilcode.daemon.active_tasks import ACTIVE_TASK_RUNNING_ERROR, ActiveTaskRegistry
from mozilcode.daemon.foreground_task_actions import start_session_task
from mozilcode.daemon.session_runtime import DaemonSessionRuntime
from mozilcode.daemon.session_runtime_requirements import SessionRuntimeRequirements


class _EnsureAgent:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls: list[str] = []

    async def __call__(self, sid: str) -> bool:
        self.calls.append(sid)
        return self.result


class _TaskRunner:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, object, object]] = []

    def start(self, sid: str, prompt: str, agent, conversation) -> str:
        self.started.append((sid, prompt, agent, conversation))
        return "task-1"


async def _never_done() -> None:
    await asyncio.Event().wait()


def _runtime() -> DaemonSessionRuntime:
    return DaemonSessionRuntime(
        SimpleNamespace(name="agent"),
        SimpleNamespace(name="deps"),
        SimpleNamespace(name="conversation"),
    )


@pytest.mark.asyncio
async def test_start_session_task_starts_runner_with_runtime_parts() -> None:
    runtime = _runtime()
    ensure_agent = _EnsureAgent(True)
    runner = _TaskRunner()

    task_id = await start_session_task(
        sid="sid",
        prompt="hello",
        active_tasks=ActiveTaskRegistry(),
        runtime_requirements=SessionRuntimeRequirements(
            ensure_agent=ensure_agent,
            runtimes={"sid": runtime},
        ),
        get_event_log=lambda _sid: [],
        task_runner=runner,
    )

    assert task_id == "task-1"
    assert ensure_agent.calls == ["sid"]
    assert runner.started == [("sid", "hello", runtime.agent, runtime.conversation)]


@pytest.mark.asyncio
async def test_start_session_task_rejects_running_task_before_session_lookup() -> None:
    active_tasks = ActiveTaskRegistry()
    task = asyncio.create_task(_never_done())
    active_tasks.register("sid", "task-running", task)
    ensure_agent = _EnsureAgent(True)
    runner = _TaskRunner()
    try:
        with pytest.raises(ValueError, match=ACTIVE_TASK_RUNNING_ERROR):
            await start_session_task(
                sid="sid",
                prompt="hello",
                active_tasks=active_tasks,
                runtime_requirements=SessionRuntimeRequirements(
                    ensure_agent=ensure_agent,
                    runtimes={"sid": _runtime()},
                ),
                get_event_log=lambda _sid: [],
                task_runner=runner,
            )
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert ensure_agent.calls == []
    assert runner.started == []


@pytest.mark.asyncio
async def test_start_session_task_rejects_missing_runtime() -> None:
    runner = _TaskRunner()

    with pytest.raises(ValueError, match="Session missing not found"):
        await start_session_task(
            sid="missing",
            prompt="hello",
            active_tasks=ActiveTaskRegistry(),
            runtime_requirements=SessionRuntimeRequirements(
                ensure_agent=_EnsureAgent(False),
                runtimes={},
            ),
            get_event_log=lambda _sid: [],
            task_runner=runner,
        )

    assert runner.started == []


@pytest.mark.asyncio
async def test_start_session_task_rejects_missing_event_log() -> None:
    runner = _TaskRunner()

    with pytest.raises(ValueError, match="Session sid not found"):
        await start_session_task(
            sid="sid",
            prompt="hello",
            active_tasks=ActiveTaskRegistry(),
            runtime_requirements=SessionRuntimeRequirements(
                ensure_agent=_EnsureAgent(True),
                runtimes={"sid": _runtime()},
            ),
            get_event_log=lambda _sid: None,
            task_runner=runner,
        )

    assert runner.started == []
