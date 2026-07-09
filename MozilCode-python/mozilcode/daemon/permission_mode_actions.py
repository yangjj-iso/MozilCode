from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mozilcode.daemon.session.status import resolve_mode_transition
from mozilcode.permissions import PermissionMode

EnsureAgent = Callable[[str], Awaitable[bool]]
GetAgent = Callable[[str], Any | None]
StatusProvider = Callable[[str], dict[str, Any]]
EmitEvent = Callable[[str, dict[str, Any] | None], None]


async def set_session_permission_mode(
    sid: str,
    requested_mode: str,
    *,
    ensure_agent: EnsureAgent,
    get_agent: GetAgent,
    pre_plan_modes: dict[str, PermissionMode],
    status_provider: StatusProvider,
    emit_event: EmitEvent,
) -> dict[str, Any]:
    """Switch a session permission mode and emit a normalized status event."""
    await ensure_agent(sid)
    agent = get_agent(sid)
    if agent is None:
        raise ValueError(f"Session {sid} not found")

    transition = resolve_mode_transition(
        agent.permission_mode,
        requested_mode,
        pre_plan_modes.get(sid),
    )
    if transition.pre_plan_mode is None:
        pre_plan_modes.pop(sid, None)
    else:
        pre_plan_modes[sid] = transition.pre_plan_mode

    agent.set_permission_mode(transition.next_mode)
    status = status_provider(sid)
    emit_event(
        sid,
        {
            "type": "ModeChanged",
            "data": {
                "mode": status["permission_mode"],
                "permission_mode": status["permission_mode"],
                "command_acceptance_mode": status["command_acceptance_mode"],
                "plan_mode": status["plan_mode"],
            },
        },
    )
    return status
