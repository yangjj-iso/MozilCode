"""Daemon pending prompt 注册表测试。"""

from __future__ import annotations

from mozilcode.daemon.tasks.pending_prompts import PendingPromptRegistry


def test_pending_prompt_registry_records_events_in_order() -> None:
    registry = PendingPromptRegistry()

    registry.record("sid", "req-1", {"type": "PermissionRequest"})
    registry.record("sid", "req-2", {"type": "AskUserRequest"})

    assert registry.events("sid") == [
        {"type": "PermissionRequest"},
        {"type": "AskUserRequest"},
    ]
    assert "sid" in registry


def test_pending_prompt_registry_replaces_duplicate_request() -> None:
    registry = PendingPromptRegistry()

    registry.record("sid", "req-1", {"type": "PermissionRequest"})
    registry.record("sid", "req-1", {"type": "AskUserRequest"})

    assert registry.events("sid") == [{"type": "AskUserRequest"}]


def test_pending_prompt_registry_discards_request_and_session() -> None:
    registry = PendingPromptRegistry()
    registry.record("sid", "req-1", {"type": "PermissionRequest"})
    registry.record("sid", "req-2", {"type": "AskUserRequest"})

    assert registry.discard("sid", "req-1") is True
    assert registry.events("sid") == [{"type": "AskUserRequest"}]
    assert registry.discard("sid", "missing") is False

    registry.discard_session("sid")

    assert registry.events("sid") == []
    assert "sid" not in registry


def test_pending_prompt_registry_ignores_empty_request_id() -> None:
    registry = PendingPromptRegistry()

    registry.record("sid", "", {"type": "PermissionRequest"})

    assert registry.events("sid") == []
    assert "sid" not in registry
