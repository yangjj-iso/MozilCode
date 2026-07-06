from __future__ import annotations

from mozilcode.daemon.session_status import (
    command_acceptance_mode,
    resolve_mode_transition,
)
from mozilcode.permissions import PermissionMode


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
