from __future__ import annotations

from types import SimpleNamespace

from mozilcode.permissions import PermissionMode
from mozilcode.tools.agent_tool_support import (
    create_subagent_permission_checker,
    parent_has_full_registry,
    resolve_parent_registry,
    resolve_parent_trace_id,
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


def test_resolve_parent_registry_prefers_full_registry() -> None:
    registry = object()
    full_registry = object()
    parent = SimpleNamespace(registry=registry, _full_registry=full_registry)

    assert parent_has_full_registry(parent) is True
    assert resolve_parent_registry(parent) is full_registry


def test_resolve_parent_registry_falls_back_to_visible_registry() -> None:
    registry = object()
    parent = SimpleNamespace(registry=registry, _full_registry=None)

    assert parent_has_full_registry(parent) is False
    assert resolve_parent_registry(parent) is registry


def test_resolve_parent_trace_id_prefers_existing_trace_id() -> None:
    parent = SimpleNamespace(agent_id="agent-1", trace_id="trace-1")

    assert resolve_parent_trace_id(parent) == "trace-1"


def test_resolve_parent_trace_id_falls_back_to_agent_id() -> None:
    parent = SimpleNamespace(agent_id="agent-1", trace_id=None)

    assert resolve_parent_trace_id(parent) == "agent-1"
