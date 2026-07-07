from __future__ import annotations

import pytest

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session_runtime import create_daemon_session_runtime
from mozilcode.permissions import PermissionMode


class _FakeAgent:
    session_id = ""


class _FakeDeps:
    pass


@pytest.mark.asyncio
async def test_create_daemon_session_runtime_registers_agent_session(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    config = AppConfig(providers=[provider])
    session_mgr = SessionManager()
    captured = {}

    async def fake_agent_factory(config_arg, work_dir, mode, hook_engine):
        captured.update(
            {
                "config": config_arg,
                "work_dir": work_dir,
                "mode": mode,
                "hook_engine": hook_engine,
            }
        )
        return _FakeAgent(), _FakeDeps()

    runtime = await create_daemon_session_runtime(
        sid="sid-runtime",
        config=config,
        work_dir=str(tmp_path),
        permission_mode=PermissionMode.ACCEPT_EDITS,
        hook_engine=None,
        session_mgr=session_mgr,
        agent_factory=fake_agent_factory,
    )

    session = await session_mgr.get_session("sid-runtime")
    assert runtime.agent.session_id == "sid-runtime"
    assert session is not None
    assert session.agent is runtime.agent
    assert session.conversation is runtime.conversation
    assert captured == {
        "config": config,
        "work_dir": str(tmp_path),
        "mode": PermissionMode.ACCEPT_EDITS,
        "hook_engine": None,
    }
