"""会话状态与权限/Plan 模式切换语义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mozilcode.context import compute_compact_threshold
from mozilcode.permissions import PermissionMode


COMMAND_ACCEPTANCE_MODES = {
    PermissionMode.DEFAULT,
    PermissionMode.ACCEPT_EDITS,
    PermissionMode.BYPASS,
}


@dataclass(frozen=True)
class ModeTransition:
    next_mode: PermissionMode
    pre_plan_mode: PermissionMode | None


def command_acceptance_mode(
    agent_mode: PermissionMode | None,
    pre_plan_mode: PermissionMode | None = None,
    configured_mode: PermissionMode | None = None,
) -> PermissionMode:
    """Return the command acceptance state, excluding plan mode."""
    if agent_mode is not None:
        if agent_mode == PermissionMode.PLAN:
            if pre_plan_mode in COMMAND_ACCEPTANCE_MODES:
                return pre_plan_mode
            return PermissionMode.DEFAULT
        if agent_mode in COMMAND_ACCEPTANCE_MODES:
            return agent_mode
        return PermissionMode.DEFAULT

    if configured_mode in COMMAND_ACCEPTANCE_MODES:
        return configured_mode
    return PermissionMode.DEFAULT


def resolve_mode_transition(
    current_mode: PermissionMode,
    requested: str,
    pre_plan_mode: PermissionMode | None = None,
) -> ModeTransition:
    """Resolve mode changes while keeping plan mode separate from command acceptance."""
    if requested == "do":
        return ModeTransition(
            next_mode=pre_plan_mode or PermissionMode.DEFAULT,
            pre_plan_mode=None,
        )

    requested_mode = PermissionMode(requested)
    if requested_mode == PermissionMode.PLAN:
        next_pre_plan_mode = pre_plan_mode
        if current_mode != PermissionMode.PLAN:
            next_pre_plan_mode = command_acceptance_mode(current_mode)
        return ModeTransition(
            next_mode=PermissionMode.PLAN,
            pre_plan_mode=next_pre_plan_mode,
        )

    if (
        requested_mode in COMMAND_ACCEPTANCE_MODES
        and current_mode == PermissionMode.PLAN
    ):
        return ModeTransition(
            next_mode=PermissionMode.PLAN,
            pre_plan_mode=requested_mode,
        )

    return ModeTransition(next_mode=requested_mode, pre_plan_mode=None)


def build_session_status(
    *,
    sid: str,
    server_work_dir: str,
    meta: dict[str, Any],
    agent: Any | None,
    provider: Any | None,
    conversation: Any | None,
    configured_permission_mode: str = "default",
    command_mode: PermissionMode = PermissionMode.DEFAULT,
    active_task_id: str = "",
    active_task_running: bool = False,
) -> dict[str, Any]:
    enabled_tools: list[str] = []
    if agent is not None:
        enabled_tools = [
            tool.name
            for tool in agent.registry.list_tools()
            if agent.registry.is_enabled(tool.name)
        ]

    context_window = 0
    if agent is not None:
        context_window = agent.context_window
    elif provider is not None:
        context_window = provider.get_context_window()

    auto_compact_threshold = (
        max(0, compute_compact_threshold(context_window))
        if context_window
        else 0
    )
    if conversation is not None and hasattr(conversation, "current_tokens"):
        input_tokens = conversation.current_tokens()
    else:
        input_tokens = agent.total_input_tokens if agent is not None else 0
    output_tokens = agent.total_output_tokens if agent is not None else 0

    return {
        "id": sid,
        "work_dir": meta.get("work_dir", server_work_dir),
        "title": meta.get("title", ""),
        "permission_mode": (
            agent.permission_mode.value
            if agent is not None
            else configured_permission_mode
        ),
        "command_acceptance_mode": command_mode.value,
        "plan_mode": bool(agent.plan_mode) if agent is not None else False,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "context_window": context_window,
        "auto_compact_threshold": auto_compact_threshold,
        "token_percent": (
            int(input_tokens / context_window * 100)
            if context_window
            else 0
        ),
        "tool_count": len(enabled_tools),
        "tools": enabled_tools,
        "active_task": {
            "id": active_task_id,
            "running": active_task_running,
        },
        "provider": {
            "name": provider.name if provider else "",
            "protocol": provider.protocol if provider else "",
            "model": provider.model if provider else "",
            "thinking": provider.thinking if provider else False,
        },
    }
