"""子 Agent 创建与 trace 补全运行时测试。"""

from __future__ import annotations

from types import SimpleNamespace

from mozilcode.agents.parser import AgentDef
from mozilcode.agents.trace import TraceManager
from mozilcode.permissions import PermissionMode
from mozilcode.tools import ToolRegistry
from mozilcode.tools.agent.runtime import (
    complete_trace_from_agent,
    create_child_agent,
)


def _parent_agent(tmp_path, *, trace_id: str | None = "trace-1") -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="parent-1",
        trace_id=trace_id,
        protocol="anthropic",
        work_dir=str(tmp_path),
        context_window=123_000,
        hook_engine=object(),
    )


def _agent_def(**overrides) -> AgentDef:
    values = {
        "agent_type": "worker",
        "when_to_use": "test worker",
        "system_prompt": "system prompt",
        "max_turns": 7,
        "permission_mode": "acceptEdits",
        "source": "builtin",
    }
    values.update(overrides)
    return AgentDef(**values)


def test_create_child_agent_inherits_parent_context_and_definition(tmp_path) -> None:
    parent = _parent_agent(tmp_path)
    client = object()
    registry = ToolRegistry()

    agent = create_child_agent(
        parent_agent=parent,
        client=client,
        registry=registry,
        work_dir=str(tmp_path),
        definition=_agent_def(),
    )

    assert agent.client is client
    assert agent.registry is registry
    assert agent.protocol == "anthropic"
    assert agent.work_dir == str(tmp_path)
    assert agent.max_iterations == 7
    assert agent.context_window == 123_000
    assert agent.instructions_content == "system prompt"
    assert agent.parent_id == "parent-1"
    assert agent.trace_id == "trace-1"
    assert agent.permission_checker.mode is PermissionMode.ACCEPT_EDITS
    assert agent.hook_engine is parent.hook_engine


def test_create_child_agent_applies_runtime_overrides(tmp_path) -> None:
    team_manager = object()

    agent = create_child_agent(
        parent_agent=_parent_agent(tmp_path, trace_id=None),
        client=object(),
        registry=ToolRegistry(),
        work_dir=str(tmp_path),
        definition=_agent_def(),
        permission_mode="dontAsk",
        instructions_content="team instructions",
        agent_id="child-1",
        team_name="core",
        team_manager=team_manager,
    )

    assert agent.agent_id == "child-1"
    assert agent.trace_id == "parent-1"
    assert agent.instructions_content == "team instructions"
    assert agent.permission_checker.mode is PermissionMode.DONT_ASK
    assert agent.team_name == "core"
    assert agent._team_manager is team_manager


def test_complete_trace_from_agent_records_usage_and_status() -> None:
    trace_manager = TraceManager()
    trace_node = trace_manager.create(
        agent_type="worker",
        parent_id="parent-1",
        trace_id="trace-1",
    )
    agent = SimpleNamespace(total_input_tokens=11, total_output_tokens=22)

    complete_trace_from_agent(trace_manager, trace_node, agent)

    updated = trace_manager.get(trace_node.agent_id)
    assert updated is not None
    assert updated.input_tokens == 11
    assert updated.output_tokens == 22
    assert updated.status == "completed"
    assert updated.end_time is not None
