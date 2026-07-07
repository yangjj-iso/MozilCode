from __future__ import annotations

from mozilcode.agent_events import CompactNotification
from mozilcode.context import CompactEvent
from mozilcode.conversation import ConversationManager


def inject_agent_context(
    conversation: ConversationManager,
    *,
    environment_context: str,
    instructions_content: str,
    memory_content: str,
) -> None:
    conversation.inject_environment(environment_context)
    conversation.inject_long_term_memory(instructions_content, memory_content)


def reinject_after_compact(
    conversation: ConversationManager,
    *,
    environment_context: str,
    instructions_content: str,
    memory_content: str,
) -> int:
    inject_agent_context(
        conversation,
        environment_context=environment_context,
        instructions_content=instructions_content,
        memory_content=memory_content,
    )
    return conversation.current_tokens()


def compact_success_notification(
    compact_event: CompactEvent,
    after_tokens: int,
) -> CompactNotification:
    return CompactNotification(
        before_tokens=compact_event.before_tokens,
        message=(
            f"上下文已压缩（{compact_event.before_tokens:,} → "
            f"{after_tokens:,} tokens）"
        ),
        after_tokens=after_tokens,
        boundary=compact_event.boundary,
    )


def compact_noop_notification(
    *,
    before_tokens: int,
    message: str | None,
) -> CompactNotification:
    return CompactNotification(
        before_tokens=before_tokens,
        message=message or "上下文暂未压缩（对话历史为空或未达到压缩条件）",
        after_tokens=before_tokens,
    )
