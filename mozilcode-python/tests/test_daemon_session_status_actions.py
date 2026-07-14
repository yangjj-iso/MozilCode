"""Daemon 会话 status 载荷组装测试。"""

from __future__ import annotations

import asyncio

import pytest

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.tasks.active import ActiveTaskRegistry
from mozilcode.daemon.session.runtime import DaemonSessionRuntime
from mozilcode.daemon.session.status_actions import (
    build_daemon_session_status,
    configured_provider,
    session_command_acceptance_mode,
)
from mozilcode.permissions import PermissionMode


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Registry:
    def list_tools(self):
        return [_Tool("ReadFile"), _Tool("WriteFile")]

    def is_enabled(self, name):
        return name == "ReadFile"


class _Agent:
    def __init__(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        self.context_window = 200_000
        self.total_input_tokens = 10
        self.total_output_tokens = 20
        self.plan_mode = mode == PermissionMode.PLAN
        self.registry = _Registry()


class _Provider:
    name = "runtime"
    protocol = "openai-compat"
    model = "runtime-model"

    def get_context_window(self):
        return 96_000


class _Deps:
    def __init__(self, provider) -> None:
        self.provider = provider


class _Conversation:
    def current_tokens(self):
        return 50_000


class _Records:
    def __init__(self, meta: dict[str, dict] | None = None) -> None:
        self._meta = meta or {}

    def meta(self, sid: str) -> dict[str, object]:
        return self._meta.get(sid, {})


def _provider(name: str = "configured") -> ProviderConfig:
    return ProviderConfig(
        name=name,
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model=f"{name}-model",
        context_window=128_000,
    )


def test_configured_provider_returns_first_provider() -> None:
    first = _provider("first")
    second = _provider("second")

    assert configured_provider(AppConfig(providers=[first, second])) is first
    assert configured_provider(AppConfig(providers=[])) is None
    assert configured_provider(None) is None


def test_session_command_acceptance_mode_uses_plan_fallback() -> None:
    agent = _Agent(PermissionMode.PLAN)

    mode = session_command_acceptance_mode(
        sid="sid",
        agent=agent,
        config=AppConfig(providers=[_provider()], permission_mode="acceptEdits"),
        pre_plan_modes={"sid": PermissionMode.BYPASS},
    )

    assert mode == PermissionMode.BYPASS


def test_session_command_acceptance_mode_uses_config_without_runtime() -> None:
    mode = session_command_acceptance_mode(
        sid="sid",
        agent=None,
        config=AppConfig(providers=[_provider()], permission_mode="acceptEdits"),
        pre_plan_modes={},
    )

    assert mode == PermissionMode.ACCEPT_EDITS


async def _never_done() -> None:
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_build_daemon_session_status_uses_runtime_records_and_active_task() -> None:
    active_tasks = ActiveTaskRegistry()
    task = asyncio.create_task(_never_done())
    runtime = DaemonSessionRuntime(
        _Agent(PermissionMode.PLAN),
        _Deps(_Provider()),
        _Conversation(),
    )
    active_tasks.register("sid", "task-1", task)
    try:
        status = build_daemon_session_status(
            sid="sid",
            config=AppConfig(providers=[_provider()], permission_mode="acceptEdits"),
            server_work_dir="/server",
            runtime=runtime,
            records=_Records({"sid": {"work_dir": "/work", "title": "Task"}}),
            active_tasks=active_tasks,
            pre_plan_modes={"sid": PermissionMode.BYPASS},
        )
    finally:
        task.cancel()

    assert status["work_dir"] == "/work"
    assert status["title"] == "Task"
    assert status["permission_mode"] == "plan"
    assert status["command_acceptance_mode"] == "bypassPermissions"
    assert status["input_tokens"] == 50_000
    assert status["output_tokens"] == 20
    assert status["context_window"] == 200_000
    assert status["tools"] == ["ReadFile"]
    assert status["active_task"] == {"id": "task-1", "running": True}
    assert status["provider"]["name"] == "runtime"


def test_build_daemon_session_status_falls_back_to_configured_provider() -> None:
    provider = _provider("configured")

    status = build_daemon_session_status(
        sid="sid",
        config=AppConfig(providers=[provider], permission_mode="acceptEdits"),
        server_work_dir="/server",
        runtime=None,
        records=_Records(),
        active_tasks=ActiveTaskRegistry(),
        pre_plan_modes={},
    )

    assert status["work_dir"] == "/server"
    assert status["permission_mode"] == "acceptEdits"
    assert status["command_acceptance_mode"] == "acceptEdits"
    assert status["context_window"] == 128_000
    assert status["provider"]["model"] == "configured-model"
