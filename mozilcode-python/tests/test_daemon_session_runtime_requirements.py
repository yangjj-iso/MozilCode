"""Daemon 动作模块运行时依赖解析测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.daemon.responses import session_not_found_result
from mozilcode.daemon.session.runtime import DaemonSessionRuntime
from mozilcode.daemon.session.runtime_requirements import SessionRuntimeRequirements


class _EnsureAgent:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls: list[str] = []

    async def __call__(self, sid: str) -> bool:
        self.calls.append(sid)
        return self.result


def _runtime() -> DaemonSessionRuntime:
    return DaemonSessionRuntime(
        SimpleNamespace(name="agent"),
        SimpleNamespace(name="deps"),
        SimpleNamespace(name="conversation"),
    )


@pytest.mark.asyncio
async def test_ensure_runtime_returns_runtime_after_agent_is_ready() -> None:
    runtime = _runtime()
    ensure_agent = _EnsureAgent(True)
    requirements = SessionRuntimeRequirements(
        ensure_agent=ensure_agent,
        runtimes={"sid": runtime},
    )

    assert await requirements.ensure_runtime("sid") is runtime
    assert ensure_agent.calls == ["sid"]


@pytest.mark.asyncio
async def test_ensure_runtime_returns_none_when_agent_cannot_be_ensured() -> None:
    ensure_agent = _EnsureAgent(False)
    requirements = SessionRuntimeRequirements(
        ensure_agent=ensure_agent,
        runtimes={"sid": _runtime()},
    )

    assert await requirements.ensure_runtime("sid") is None
    assert ensure_agent.calls == ["sid"]


@pytest.mark.asyncio
async def test_require_runtime_returns_standard_session_not_found_error() -> None:
    requirements = SessionRuntimeRequirements(
        ensure_agent=_EnsureAgent(True),
        runtimes={},
    )

    runtime, error = await requirements.require_runtime("missing")

    assert runtime is None
    assert error == session_not_found_result()


@pytest.mark.asyncio
async def test_require_deps_returns_runtime_deps() -> None:
    runtime = _runtime()
    requirements = SessionRuntimeRequirements(
        ensure_agent=_EnsureAgent(True),
        runtimes={"sid": runtime},
    )

    deps, error = await requirements.require_deps("sid")

    assert deps is runtime.deps
    assert error is None


@pytest.mark.asyncio
async def test_require_agent_and_deps_returns_runtime_parts() -> None:
    runtime = _runtime()
    requirements = SessionRuntimeRequirements(
        ensure_agent=_EnsureAgent(True),
        runtimes={"sid": runtime},
    )

    agent, deps, error = await requirements.require_agent_and_deps("sid")

    assert agent is runtime.agent
    assert deps is runtime.deps
    assert error is None


@pytest.mark.asyncio
async def test_require_agent_and_conversation_returns_runtime_parts() -> None:
    runtime = _runtime()
    requirements = SessionRuntimeRequirements(
        ensure_agent=_EnsureAgent(True),
        runtimes={"sid": runtime},
    )

    agent, conversation, error = await requirements.require_agent_and_conversation("sid")

    assert agent is runtime.agent
    assert conversation is runtime.conversation
    assert error is None
