from __future__ import annotations

from dataclasses import dataclass

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
