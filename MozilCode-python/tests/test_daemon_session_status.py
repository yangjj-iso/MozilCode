from __future__ import annotations

from mozilcode.daemon.session_status import (
    build_session_status,
    command_acceptance_mode,
    resolve_mode_transition,
)
from mozilcode.permissions import PermissionMode


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class _Registry:
    def list_tools(self):
        return [_Tool("ReadFile"), _Tool("WriteFile")]

    def is_enabled(self, name):
        return name == "ReadFile"


class _Agent:
    permission_mode = PermissionMode.PLAN
    context_window = 200_000
    total_input_tokens = 10
    total_output_tokens = 20
    plan_mode = True
    registry = _Registry()


class _Provider:
    name = "local"
    protocol = "openai-compat"
    model = "smoke-model"

    def get_context_window(self):
        return 128_000


class _Conversation:
    def current_tokens(self):
        return 50_000


def test_command_acceptance_mode_excludes_plan_mode() -> None:
    assert (
        command_acceptance_mode(PermissionMode.ACCEPT_EDITS)
        == PermissionMode.ACCEPT_EDITS
    )
    assert (
        command_acceptance_mode(PermissionMode.PLAN, PermissionMode.BYPASS)
        == PermissionMode.BYPASS
    )
    assert command_acceptance_mode(PermissionMode.PLAN) == PermissionMode.DEFAULT
    assert command_acceptance_mode(PermissionMode.CUSTOM) == PermissionMode.DEFAULT
    assert (
        command_acceptance_mode(None, configured_mode=PermissionMode.ACCEPT_EDITS)
        == PermissionMode.ACCEPT_EDITS
    )


def test_resolve_mode_transition_enters_plan_with_previous_acceptance() -> None:
    transition = resolve_mode_transition(PermissionMode.ACCEPT_EDITS, "plan")

    assert transition.next_mode == PermissionMode.PLAN
    assert transition.pre_plan_mode == PermissionMode.ACCEPT_EDITS


def test_resolve_mode_transition_updates_acceptance_while_in_plan() -> None:
    transition = resolve_mode_transition(
        PermissionMode.PLAN,
        "bypassPermissions",
        PermissionMode.ACCEPT_EDITS,
    )

    assert transition.next_mode == PermissionMode.PLAN
    assert transition.pre_plan_mode == PermissionMode.BYPASS


def test_resolve_mode_transition_do_restores_previous_acceptance() -> None:
    transition = resolve_mode_transition(
        PermissionMode.PLAN,
        "do",
        PermissionMode.BYPASS,
    )

    assert transition.next_mode == PermissionMode.BYPASS
    assert transition.pre_plan_mode is None


def test_resolve_mode_transition_exits_plan_for_non_acceptance_mode() -> None:
    transition = resolve_mode_transition(
        PermissionMode.PLAN,
        "dontAsk",
        PermissionMode.BYPASS,
    )

    assert transition.next_mode == PermissionMode.DONT_ASK
    assert transition.pre_plan_mode is None


def test_build_session_status_uses_agent_runtime_values() -> None:
    status = build_session_status(
        sid="sid-1",
        server_work_dir="/repo",
        meta={"work_dir": "/work", "title": "Task"},
        agent=_Agent(),
        provider=_Provider(),
        conversation=_Conversation(),
        command_mode=PermissionMode.BYPASS,
        active_task_id="task-1",
        active_task_running=True,
    )

    assert status["id"] == "sid-1"
    assert status["work_dir"] == "/work"
    assert status["title"] == "Task"
    assert status["permission_mode"] == "plan"
    assert status["command_acceptance_mode"] == "bypassPermissions"
    assert status["plan_mode"] is True
    assert status["input_tokens"] == 50_000
    assert status["output_tokens"] == 20
    assert status["context_window"] == 200_000
    assert status["token_percent"] == 25
    assert status["tools"] == ["ReadFile"]
    assert status["tool_count"] == 1
    assert status["active_task"] == {"id": "task-1", "running": True}
    assert status["provider"]["model"] == "smoke-model"


def test_build_session_status_falls_back_to_provider_without_agent() -> None:
    status = build_session_status(
        sid="sid-2",
        server_work_dir="/repo",
        meta={},
        agent=None,
        provider=_Provider(),
        conversation=None,
        configured_permission_mode="acceptEdits",
    )

    assert status["work_dir"] == "/repo"
    assert status["permission_mode"] == "acceptEdits"
    assert status["plan_mode"] is False
    assert status["input_tokens"] == 0
    assert status["output_tokens"] == 0
    assert status["context_window"] == 128_000
    assert status["tools"] == []
