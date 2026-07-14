"""内置/默认子 Agent 定义工厂测试。"""

from __future__ import annotations

from mozilcode.agents.defaults import (
    fork_agent_def,
    teammate_agent_def,
    worktree_agent_def,
)


def test_fork_agent_def_uses_safe_defaults() -> None:
    definition = fork_agent_def(12)

    assert definition.agent_type == "fork"
    assert definition.when_to_use == "Forked from parent agent"
    assert definition.max_turns == 12
    assert definition.model == "inherit"
    assert definition.permission_mode == "dontAsk"
    assert definition.source == "builtin"


def test_teammate_agent_def_uses_safe_defaults() -> None:
    definition = teammate_agent_def(8)

    assert definition.agent_type == "teammate"
    assert definition.when_to_use == "Team member"
    assert definition.max_turns == 8
    assert definition.model == "inherit"
    assert definition.permission_mode == "dontAsk"
    assert definition.source == "builtin"


def test_worktree_agent_def_uses_safe_defaults() -> None:
    definition = worktree_agent_def(5)

    assert definition.agent_type == "worktree-agent"
    assert definition.when_to_use == "Isolated worktree agent"
    assert definition.max_turns == 5
    assert definition.model == "inherit"
    assert definition.permission_mode == "dontAsk"
    assert definition.source == "builtin"
