"""Daemon 会话创建/初始化生命周期测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session.lifecycle_actions import (
    create_session_runtime,
    ensure_session_runtime,
    init_daemon_session,
    switch_session_provider,
)
from mozilcode.daemon.session.runtime import DaemonSessionRuntime
from mozilcode.permissions import PermissionMode


class _Agent:
    session_id = ""

    def __init__(self, mode: PermissionMode) -> None:
        self.permission_mode = mode


class _Deps:
    def __init__(self, provider: ProviderConfig) -> None:
        self.provider = provider


class _Records:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []
        self.event_logs: list[str] = []
        self._existing: set[str] = set()
        self.session_meta: dict[str, dict] = {}
        self.persisted: list[str] = []

    def has(self, sid: str) -> bool:
        return sid in self._existing

    def create(self, sid: str, work_dir: str, provider_name: str = "") -> None:
        self._existing.add(sid)
        self.created.append((sid, work_dir))
        meta = {"work_dir": work_dir}
        if provider_name:
            meta["provider_name"] = provider_name
        self.session_meta[sid] = meta

    def ensure_event_log(self, sid: str) -> None:
        self.event_logs.append(sid)

    def meta(self, sid: str) -> dict:
        return self.session_meta.get(sid, {})

    def persist_meta(self, sid: str) -> None:
        self.persisted.append(sid)


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )


async def _factory(config, work_dir, mode, hook_engine):
    return _Agent(mode), _Deps(config.providers[0])


@pytest.mark.asyncio
async def test_create_session_runtime_registers_runtime_and_session(tmp_path: Path) -> None:
    config = AppConfig(providers=[_provider()], permission_mode="acceptEdits")
    session_mgr = SessionManager()
    runtimes: dict[str, DaemonSessionRuntime] = {}

    runtime = await create_session_runtime(
        sid="sid-runtime",
        config=config,
        work_dir=str(tmp_path),
        hook_engine=None,
        session_mgr=session_mgr,
        runtimes=runtimes,
        agent_factory=_factory,
    )

    session = await session_mgr.get_session("sid-runtime")
    assert runtimes["sid-runtime"] is runtime
    assert runtime.agent.session_id == "sid-runtime"
    assert runtime.agent.permission_mode == PermissionMode.ACCEPT_EDITS
    assert session is not None
    assert session.agent is runtime.agent
    assert session.conversation is runtime.conversation


@pytest.mark.asyncio
async def test_init_daemon_session_creates_record_after_runtime(tmp_path: Path) -> None:
    config = AppConfig(providers=[_provider()])
    records = _Records()
    runtimes: dict[str, DaemonSessionRuntime] = {}

    sid = await init_daemon_session(
        session_id="sid-init",
        work_dir=None,
        config=config,
        default_work_dir=str(tmp_path),
        hook_engine=None,
        session_mgr=SessionManager(),
        runtimes=runtimes,
        records=records,
        agent_factory=_factory,
    )

    assert sid == "sid-init"
    assert records.created == [("sid-init", str(tmp_path))]
    assert "sid-init" in runtimes


@pytest.mark.asyncio
async def test_init_daemon_session_rejects_duplicate_before_runtime(
    tmp_path: Path,
) -> None:
    config = AppConfig(providers=[_provider()])
    records = _Records()
    records._existing.add("sid-init")
    runtimes: dict[str, DaemonSessionRuntime] = {}

    with pytest.raises(ValueError, match="session already exists: sid-init"):
        await init_daemon_session(
            session_id="sid-init",
            work_dir=None,
            config=config,
            default_work_dir=str(tmp_path),
            hook_engine=None,
            session_mgr=SessionManager(),
            runtimes=runtimes,
            records=records,
            agent_factory=_factory,
        )

    assert runtimes == {}
    assert records.created == []


@pytest.mark.asyncio
async def test_ensure_session_runtime_recreates_from_persisted_meta(
    tmp_path: Path,
) -> None:
    config = AppConfig(providers=[_provider()])
    records = _Records()
    runtimes: dict[str, DaemonSessionRuntime] = {}

    ok = await ensure_session_runtime(
        sid="sid-persisted",
        config=config,
        default_work_dir=str(tmp_path / "fallback"),
        hook_engine=None,
        session_mgr=SessionManager(),
        runtimes=runtimes,
        session_meta={"sid-persisted": {"work_dir": str(tmp_path)}},
        records=records,
        agent_factory=_factory,
    )

    assert ok is True
    assert "sid-persisted" in runtimes
    assert records.event_logs == ["sid-persisted"]


@pytest.mark.asyncio
async def test_ensure_session_runtime_falls_back_when_saved_work_dir_is_missing(
    tmp_path: Path,
) -> None:
    config = AppConfig(providers=[_provider()])
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    captured: dict[str, str] = {}

    async def factory(config, work_dir, mode, hook_engine):
        captured["work_dir"] = work_dir
        return _Agent(mode), _Deps(config.providers[0])

    ok = await ensure_session_runtime(
        sid="sid-persisted",
        config=config,
        default_work_dir=str(fallback),
        hook_engine=None,
        session_mgr=SessionManager(),
        runtimes={},
        session_meta={"sid-persisted": {"work_dir": str(tmp_path / "missing")}},
        records=_Records(),
        agent_factory=factory,
    )

    assert ok is True
    assert captured["work_dir"] == str(fallback)


@pytest.mark.asyncio
async def test_ensure_session_runtime_returns_false_without_config_or_meta(
    tmp_path: Path,
) -> None:
    records = _Records()

    assert (
        await ensure_session_runtime(
            sid="sid",
            config=None,
            default_work_dir=str(tmp_path),
            hook_engine=None,
            session_mgr=SessionManager(),
            runtimes={},
            session_meta={"sid": {"work_dir": str(tmp_path)}},
            records=records,
        )
        is False
    )

    assert (
        await ensure_session_runtime(
            sid="sid",
            config=AppConfig(providers=[_provider()]),
            default_work_dir=str(tmp_path),
            hook_engine=None,
            session_mgr=SessionManager(),
            runtimes={},
            session_meta={},
            records=records,
        )
        is False
    )


class _ActiveTasks:
    def __init__(self, running: bool = False) -> None:
        self._running = running

    def is_running(self, sid: str) -> bool:
        return self._running


@pytest.mark.asyncio
async def test_switch_session_provider_rebuilds_runtime_and_keeps_history(
    tmp_path: Path,
) -> None:
    first = ProviderConfig(
        name="p1",
        protocol="openai-compat",
        base_url="http://127.0.0.1:1/v1",
        model="model-1",
    )
    second = ProviderConfig(
        name="p2",
        protocol="openai-compat",
        base_url="http://127.0.0.1:2/v1",
        model="model-2",
    )
    config = AppConfig(providers=[first, second], permission_mode="default")
    records = _Records()
    runtimes: dict[str, DaemonSessionRuntime] = {}
    session_mgr = SessionManager()

    await init_daemon_session(
        session_id="sid-switch",
        work_dir=None,
        config=config,
        default_work_dir=str(tmp_path),
        hook_engine=None,
        session_mgr=session_mgr,
        runtimes=runtimes,
        records=records,
        agent_factory=_factory,
        provider_name="p1",
    )
    old = runtimes["sid-switch"]
    old.conversation.add_user_message("hello")
    old.conversation.env_injected = True

    result = await switch_session_provider(
        sid="sid-switch",
        provider_name="p2",
        config=config,
        default_work_dir=str(tmp_path),
        hook_engine=None,
        session_mgr=session_mgr,
        runtimes=runtimes,
        records=records,
        active_tasks=_ActiveTasks(False),
        agent_factory=_factory,
    )

    new = runtimes["sid-switch"]
    assert result["changed"] is True
    assert result["provider_name"] == "p2"
    assert new is not old
    assert new.deps.provider.name == "p2"
    assert new.deps.provider.model == "model-2"
    assert [m.content for m in new.conversation.get_messages()] == ["hello"]
    assert new.conversation.env_injected is True
    assert records.meta("sid-switch")["provider_name"] == "p2"
    assert "sid-switch" in records.persisted


@pytest.mark.asyncio
async def test_switch_session_provider_rejects_running_task(tmp_path: Path) -> None:
    config = AppConfig(providers=[_provider()])
    records = _Records()
    records.create("sid-busy", str(tmp_path), provider_name="local")
    with pytest.raises(ValueError, match="task already running"):
        await switch_session_provider(
            sid="sid-busy",
            provider_name="local",
            config=config,
            default_work_dir=str(tmp_path),
            hook_engine=None,
            session_mgr=SessionManager(),
            runtimes={},
            records=records,
            active_tasks=_ActiveTasks(True),
            agent_factory=_factory,
        )


@pytest.mark.asyncio
async def test_switch_session_provider_keeps_old_runtime_when_replacement_fails(
    tmp_path: Path,
) -> None:
    first = _provider()
    second = ProviderConfig(
        name="broken",
        protocol="openai-compat",
        base_url="http://127.0.0.1:2/v1",
        model="broken-model",
    )
    config = AppConfig(providers=[first, second])
    records = _Records()
    runtimes: dict[str, DaemonSessionRuntime] = {}
    session_mgr = SessionManager()

    await init_daemon_session(
        session_id="sid-rollback",
        work_dir=None,
        config=config,
        default_work_dir=str(tmp_path),
        hook_engine=None,
        session_mgr=session_mgr,
        runtimes=runtimes,
        records=records,
        agent_factory=_factory,
        provider_name="local",
    )
    old = runtimes["sid-rollback"]

    async def failing_factory(config, work_dir, mode, hook_engine):
        if config.providers[0].name == "broken":
            raise RuntimeError("replacement setup failed")
        return await _factory(config, work_dir, mode, hook_engine)

    with pytest.raises(RuntimeError, match="replacement setup failed"):
        await switch_session_provider(
            sid="sid-rollback",
            provider_name="broken",
            config=config,
            default_work_dir=str(tmp_path),
            hook_engine=None,
            session_mgr=session_mgr,
            runtimes=runtimes,
            records=records,
            active_tasks=_ActiveTasks(False),
            agent_factory=failing_factory,
        )

    assert runtimes["sid-rollback"] is old
    assert (await session_mgr.get_session("sid-rollback")).agent is old.agent
    assert records.meta("sid-rollback")["provider_name"] == "local"
