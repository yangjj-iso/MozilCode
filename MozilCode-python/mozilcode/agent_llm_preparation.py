from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from mozilcode.context import (
    ContentReplacementRecord,
    ContentReplacementState,
    append_replacement_records,
    apply_tool_result_budget,
)
from mozilcode.conversation import ConversationManager


DEFERRED_TOOL_REMINDER_PREFIX = (
    "The following deferred tools are available via ToolSearch. "
    "Their schemas are NOT loaded - use ToolSearch with "
    'query "select:<name>[,<name>...]" to load tool schemas before calling them:\n'
)


def build_deferred_tool_reminder(deferred_names: Iterable[str]) -> str | None:
    names = list(deferred_names)
    if not names:
        return None
    return DEFERRED_TOOL_REMINDER_PREFIX + "\n".join(names)


def inject_deferred_tool_reminder(
    conversation: ConversationManager,
    deferred_names: Iterable[str],
) -> bool:
    reminder = build_deferred_tool_reminder(deferred_names)
    if reminder is None:
        return False
    conversation.add_system_reminder(reminder)
    return True


def prepare_api_conversation(
    conversation: ConversationManager,
    session_dir: Path,
    replacement_state: ContentReplacementState,
) -> tuple[ConversationManager, list[ContentReplacementRecord]]:
    api_conversation, new_records = apply_tool_result_budget(
        conversation,
        session_dir,
        replacement_state,
    )
    if new_records:
        append_replacement_records(session_dir, new_records)
    return api_conversation, new_records
