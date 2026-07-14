"""Agent 上下文注入与 Layer2 压缩后重建测试。"""

from __future__ import annotations

from mozilcode.agent.compaction import (
    compact_noop_notification,
    compact_success_notification,
    inject_agent_context,
    reinject_after_compact,
)
from mozilcode.context import CompactEvent
from mozilcode.conversation import ConversationManager, Message


def test_inject_agent_context_adds_environment_before_memory() -> None:
    conversation = ConversationManager()

    inject_agent_context(
        conversation,
        environment_context="Current working directory: D:/repo",
        instructions_content="Prefer focused changes.",
        memory_content="User likes tests.",
    )

    messages = conversation.get_messages()
    assert messages[0].content == "Current working directory: D:/repo"
    assert "# mozilcodeMd" in messages[1].content
    assert "# autoMemory" in messages[1].content
    assert conversation.env_injected is True
    assert conversation.ltm_injected is True


def test_reinject_after_compact_resets_context_after_history_replacement() -> None:
    conversation = ConversationManager()
    inject_agent_context(
        conversation,
        environment_context="old env",
        instructions_content="old instructions",
        memory_content="old memory",
    )
    conversation.replace_history([Message(role="user", content="summary")])

    after_tokens = reinject_after_compact(
        conversation,
        environment_context="new env",
        instructions_content="new instructions",
        memory_content="new memory",
    )

    messages = conversation.get_messages()
    assert messages[0].content == "new env"
    assert "new instructions" in messages[1].content
    assert "new memory" in messages[1].content
    assert messages[2].content == "summary"
    assert after_tokens == conversation.current_tokens()


def test_compact_success_notification_uses_event_boundary_and_token_counts() -> None:
    event = CompactEvent(before_tokens=12000)

    notification = compact_success_notification(event, after_tokens=3400)

    assert notification.before_tokens == 12000
    assert notification.after_tokens == 3400
    assert notification.boundary is event.boundary
    assert "12,000" in notification.message
    assert "3,400" in notification.message


def test_compact_noop_notification_uses_default_message() -> None:
    notification = compact_noop_notification(before_tokens=42, message=None)

    assert notification.before_tokens == 42
    assert notification.after_tokens == 42
    assert "暂未压缩" in notification.message


def test_compact_noop_notification_uses_explicit_message() -> None:
    notification = compact_noop_notification(
        before_tokens=42,
        message="compact skipped",
    )

    assert notification.message == "compact skipped"
