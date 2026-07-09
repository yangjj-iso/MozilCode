from __future__ import annotations

from typing import Any

import pytest

from mozilcode.daemon.permission_mode_actions import set_session_permission_mode
from mozilcode.daemon.session.status import command_acceptance_mode
from mozilcode.permissions import PermissionMode


class _Agent:
    def __init__(self, mode: PermissionMode) -> None:
        self.permission_mode = mode

    @property
    def plan_mode(self) -> bool:
        return self.permission_mode == PermissionMode.PLAN

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode


def _status(
    sid: str,
    agent: _Agent,
    pre_plan_modes: dict[str, PermissionMode],
) -> dict[str, Any]:
    return {
        "permission_mode": agent.permission_mode.value,
        "command_acceptance_mode": command_acceptance_mode(
            agent.permission_mode,
            pre_plan_modes.get(sid),
        ).value,
        "plan_mode": agent.plan_mode,
    }


@pytest.mark.asyncio
async def test_set_session_permission_mode_enters_plan_and_emits_status() -> None:
    sid = "sid"
    agent = _Agent(PermissionMode.ACCEPT_EDITS)
    pre_plan_modes: dict[str, PermissionMode] = {}
    events: list[tuple[str, dict | None]] = []

    async def ensure_agent(_sid: str) -> bool:
        return True

    result = await set_session_permission_mode(
        sid,
        "plan",
        ensure_agent=ensure_agent,
        get_agent=lambda _sid: agent,
        pre_plan_modes=pre_plan_modes,
        status_provider=lambda _sid: _status(sid, agent, pre_plan_modes),
        emit_event=lambda sid, event: events.append((sid, event)),
    )

    assert agent.permission_mode == PermissionMode.PLAN
    assert pre_plan_modes == {sid: PermissionMode.ACCEPT_EDITS}
    assert result["command_acceptance_mode"] == "acceptEdits"
    assert events == [
        (
            sid,
            {
                "type": "ModeChanged",
                "data": {
                    "mode": "plan",
                    "permission_mode": "plan",
                    "command_acceptance_mode": "acceptEdits",
                    "plan_mode": True,
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_set_session_permission_mode_updates_acceptance_while_in_plan() -> None:
    sid = "sid"
    agent = _Agent(PermissionMode.PLAN)
    pre_plan_modes = {sid: PermissionMode.ACCEPT_EDITS}

    async def ensure_agent(_sid: str) -> bool:
        return True

    result = await set_session_permission_mode(
        sid,
        "bypassPermissions",
        ensure_agent=ensure_agent,
        get_agent=lambda _sid: agent,
        pre_plan_modes=pre_plan_modes,
        status_provider=lambda _sid: _status(sid, agent, pre_plan_modes),
        emit_event=lambda _sid, _event: None,
    )

    assert agent.permission_mode == PermissionMode.PLAN
    assert pre_plan_modes == {sid: PermissionMode.BYPASS}
    assert result["command_acceptance_mode"] == "bypassPermissions"
    assert result["plan_mode"] is True


@pytest.mark.asyncio
async def test_set_session_permission_mode_do_restores_pre_plan_mode() -> None:
    sid = "sid"
    agent = _Agent(PermissionMode.PLAN)
    pre_plan_modes = {sid: PermissionMode.BYPASS}

    async def ensure_agent(_sid: str) -> bool:
        return True

    result = await set_session_permission_mode(
        sid,
        "do",
        ensure_agent=ensure_agent,
        get_agent=lambda _sid: agent,
        pre_plan_modes=pre_plan_modes,
        status_provider=lambda _sid: _status(sid, agent, pre_plan_modes),
        emit_event=lambda _sid, _event: None,
    )

    assert agent.permission_mode == PermissionMode.BYPASS
    assert pre_plan_modes == {}
    assert result["permission_mode"] == "bypassPermissions"
    assert result["plan_mode"] is False


@pytest.mark.asyncio
async def test_set_session_permission_mode_rejects_missing_agent() -> None:
    async def ensure_agent(_sid: str) -> bool:
        return False

    with pytest.raises(ValueError, match="Session missing not found"):
        await set_session_permission_mode(
            "missing",
            "plan",
            ensure_agent=ensure_agent,
            get_agent=lambda _sid: None,
            pre_plan_modes={},
            status_provider=lambda _sid: {},
            emit_event=lambda _sid, _event: None,
        )
