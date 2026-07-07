from __future__ import annotations

from mozilcode.permissions import PermissionMode
from mozilcode.tools.agent_tool_support import (
    create_subagent_permission_checker,
    resolve_permission_mode,
    unique_agent_name,
)


def test_resolve_permission_mode_maps_known_agent_values() -> None:
    assert resolve_permission_mode("default") is PermissionMode.DEFAULT
    assert resolve_permission_mode("acceptEdits") is PermissionMode.ACCEPT_EDITS
    assert resolve_permission_mode("dontAsk") is PermissionMode.DONT_ASK


def test_resolve_permission_mode_falls_back_to_default() -> None:
    assert resolve_permission_mode(None) is PermissionMode.DEFAULT
    assert resolve_permission_mode("unknown") is PermissionMode.DEFAULT


def test_create_subagent_permission_checker_uses_project_sandbox_and_mode(tmp_path) -> None:
    checker = create_subagent_permission_checker(str(tmp_path), "dontAsk")

    assert checker.mode is PermissionMode.DONT_ASK
    assert checker.sandbox.project_root == tmp_path.resolve()


def test_create_subagent_permission_checker_accepts_permission_mode(tmp_path) -> None:
    checker = create_subagent_permission_checker(
        str(tmp_path),
        PermissionMode.ACCEPT_EDITS,
    )

    assert checker.mode is PermissionMode.ACCEPT_EDITS


def test_unique_agent_name_keeps_unused_base_name() -> None:
    assert unique_agent_name("worker", {"reviewer"}) == "worker"


def test_unique_agent_name_adds_next_available_suffix() -> None:
    assert unique_agent_name("worker", {"worker", "worker-2", "worker-4"}) == "worker-3"
