from __future__ import annotations

import pytest

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.agent import factory as agent_factory
from mozilcode.agent.factory import create_agent_from_config
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


@pytest.mark.asyncio
async def test_created_agent_file_tools_are_rooted_at_work_dir(tmp_path, monkeypatch):
    async def fake_resolve_context_window(_provider):
        return None

    monkeypatch.setattr(
        agent_factory,
        "resolve_context_window",
        fake_resolve_context_window,
    )
    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir()
    monkeypatch.chdir(outside_cwd)
    (tmp_path / "README.md").write_text("project readme\n", encoding="utf-8")
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
        api_key="test-key",
    )

    agent, _deps = await create_agent_from_config(
        AppConfig(providers=[provider]),
        str(tmp_path),
        PermissionMode.DEFAULT,
    )

    read_file = agent.registry.get("ReadFile")
    assert read_file is not None
    params = read_file.params_model(file_path="README.md")
    result = await read_file.execute(params)

    assert not result.is_error
    assert result.output == "1\tproject readme"


@pytest.mark.asyncio
async def test_create_agent_from_config_passes_team_mode_to_team_create_tool(
    tmp_path,
    monkeypatch,
):
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

    agent, _deps = await create_agent_from_config(
        AppConfig(providers=[provider], teammate_mode="in-process"),
        str(tmp_path),
        PermissionMode.DEFAULT,
    )

    team_create = agent.registry.get("TeamCreate")
    assert team_create is not None
    assert team_create._teammate_mode == "in-process"
