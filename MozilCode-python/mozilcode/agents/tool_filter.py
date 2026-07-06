from __future__ import annotations

from typing import TYPE_CHECKING

from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import Tool

if TYPE_CHECKING:
    from mozilcode.agents.parser import AgentDef
    from mozilcode.teams.manager import TeamManager

ALL_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "TaskOutput",
    "ExitPlanMode",
    "EnterPlanMode",
    "Agent",
    "AskUserQuestion",
    "TaskStop",
    "Workflow",
})

CUSTOM_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({
    "TaskOutput",
    "ExitPlanMode",
    "EnterPlanMode",
    "Agent",
    "AskUserQuestion",
    "TaskStop",
    "Workflow",
})

ASYNC_AGENT_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "ReadFile",
    "WebSearch",
    "TodoWrite",
    "Grep",
    "WebFetch",
    "Glob",
    "Bash",
    "EditFile",
    "WriteFile",
    "NotebookEdit",
    "Skill",
    "LoadSkill",
    "SyntheticOutput",
    "ToolSearch",
    "EnterWorktree",
    "ExitWorktree",
})

TEAMMATE_COORDINATION_TOOLS: frozenset[str] = frozenset({
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
})

IN_PROCESS_TEAMMATE_ALLOWED_TOOLS: frozenset[str] = (
    ASYNC_AGENT_ALLOWED_TOOLS | TEAMMATE_COORDINATION_TOOLS | frozenset({
        "CronCreate",
        "CronDelete",
        "CronList",
    })
)

COORDINATOR_MODE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "Agent",
    "TaskStop",
    "SendMessage",
    "SyntheticOutput",
    "TeamCreate",
    "TeamDelete",
})


def _is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp_")


def _tools_by_name(registry: ToolRegistry) -> dict[str, Tool]:
    return {tool.name: tool for tool in registry.list_tools()}


def _registry_from_tools(tools: dict[str, Tool]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools.values():
        registry.register(tool)
    return registry


def _remove_tools(tools: dict[str, Tool], names: set[str] | frozenset[str]) -> None:
    for name in names:
        tools.pop(name, None)


def _only_tools(
    tools: dict[str, Tool],
    names: set[str] | frozenset[str],
) -> dict[str, Tool]:
    return {name: tool for name, tool in tools.items() if name in names}


def _apply_definition_filters(
    tools: dict[str, Tool],
    definition: AgentDef | None,
    *,
    always_allowed: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Tool]:
    if definition is None:
        return tools
    if definition.disallowed_tools:
        _remove_tools(tools, set(definition.disallowed_tools))
    if definition.tools:
        allowed_set = set(definition.tools) | set(always_allowed)
        return _only_tools(tools, allowed_set)
    return tools


def resolve_agent_tools(
    parent_registry: ToolRegistry,
    definition: AgentDef,
    is_background: bool = False,
) -> ToolRegistry:
    all_tools = _tools_by_name(parent_registry)

    # 第 0 层：MCP 工具始终放行，先分离出来再做后续过滤
    mcp_tools = {name: tool for name, tool in all_tools.items() if _is_mcp_tool(name)}
    all_tools = {name: tool for name, tool in all_tools.items() if not _is_mcp_tool(name)}

    # 第 1 层：全局禁用工具
    _remove_tools(all_tools, ALL_AGENT_DISALLOWED_TOOLS)

    # 第 2 层：自定义 agent 额外限制
    if definition.source in ("project", "user", "plugin"):
        _remove_tools(all_tools, CUSTOM_AGENT_DISALLOWED_TOOLS)

    # 第 3 层：后台任务白名单
    if is_background:
        all_tools = _only_tools(all_tools, ASYNC_AGENT_ALLOWED_TOOLS)

    # 第 4 层：按 agent 定义中的禁用/允许列表过滤
    all_tools = _apply_definition_filters(all_tools, definition)
    return _registry_from_tools({**mcp_tools, **all_tools})


def build_teammate_tools(
    parent_registry: ToolRegistry,
    team_manager: TeamManager,
    team_name: str,
    agent_id: str,
    agent_name: str,
    backend_type: str,
    definition: AgentDef | None = None,
) -> ToolRegistry:
    from mozilcode.teams.models import BackendType
    from mozilcode.tools.send_message import SendMessageTool
    from mozilcode.tools.task_create import TaskCreateTool
    from mozilcode.tools.task_get import TaskGetTool
    from mozilcode.tools.task_list import TaskListTool
    from mozilcode.tools.task_update import TaskUpdateTool

    if backend_type == BackendType.IN_PROCESS.value:
        filtered = _only_tools(
            _tools_by_name(parent_registry),
            IN_PROCESS_TEAMMATE_ALLOWED_TOOLS,
        )
    else:
        filtered = _tools_by_name(parent_registry)
        filtered.pop("TeamCreate", None)
        filtered.pop("TeamDelete", None)

    # 应用 agent 定义中的工具限制
    filtered = _apply_definition_filters(
        filtered,
        definition,
        always_allowed=TEAMMATE_COORDINATION_TOOLS,
    )

    coordination_tools = [
        TaskCreateTool(team_manager, team_name, agent_name),
        TaskGetTool(team_manager, team_name),
        TaskListTool(team_manager, team_name),
        TaskUpdateTool(team_manager, team_name),
        SendMessageTool(team_manager, team_name, agent_id, agent_name),
    ]

    registry = _registry_from_tools(filtered)
    for tool in coordination_tools:
        registry.register(tool)

    return registry


def apply_coordinator_filter(registry: ToolRegistry) -> ToolRegistry:
    return _registry_from_tools(
        _only_tools(_tools_by_name(registry), COORDINATOR_MODE_ALLOWED_TOOLS)
    )
