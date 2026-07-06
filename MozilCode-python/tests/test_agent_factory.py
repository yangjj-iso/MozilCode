from __future__ import annotations

import pytest

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode import agent_factory
from mozilcode.agent_factory import create_agent_from_config
from mozilcode.permissions import PermissionMode


@pytest.mark.asyncio
async def test_create_agent_from_config_wires_core_tools_and_deps(tmp_path, monkeypatch):
    async def fake_resolve_context_window(_provider):
        return None

    monkeypatch.setattr(
        agent_factory,
        "resolve_context_window",
        fake_resolve_context_window,
    )
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
        api_key="test-key",
    )

    agent, deps = await create_agent_from_config(
        AppConfig(providers=[provider]),
        str(tmp_path),
        PermissionMode.DEFAULT,
    )

    tool_names = {tool.name for tool in agent.registry.list_tools()}
    assert deps.provider is provider
    assert agent.work_dir == str(tmp_path)
    assert agent.permission_checker.mode == PermissionMode.DEFAULT
    assert {
        "ReadFile",
        "WriteFile",
        "ToolSearch",
        "AskUserQuestion",
        "Agent",
    }.issubset(tool_names)
    assert deps.worktree_manager.repo_root == str(tmp_path)
