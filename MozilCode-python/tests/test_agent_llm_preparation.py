from __future__ import annotations

from pathlib import Path

from mozilcode.agent.llm_preparation import (
    build_deferred_tool_reminder,
    inject_deferred_tool_reminder,
    prepare_api_conversation,
)
from mozilcode.context import (
    create_replacement_state,
    load_replacement_records,
)
from mozilcode.context.tool_results import PERSISTED_TAG, SINGLE_RESULT_CHAR_LIMIT
from mozilcode.conversation import ConversationManager, Message, ToolResultBlock


def test_build_deferred_tool_reminder_returns_none_without_tools() -> None:
    assert build_deferred_tool_reminder([]) is None


def test_inject_deferred_tool_reminder_adds_system_reminder() -> None:
    conversation = ConversationManager()

    inserted = inject_deferred_tool_reminder(
        conversation,
        ["DeferredAlpha", "DeferredBeta"],
    )

    assert inserted is True
    assert len(conversation.history) == 1
    reminder = conversation.history[0].content
    assert "ToolSearch" in reminder
    assert "DeferredAlpha" in reminder
    assert "DeferredBeta" in reminder


def test_inject_deferred_tool_reminder_skips_empty_tool_list() -> None:
    conversation = ConversationManager()

    inserted = inject_deferred_tool_reminder(conversation, [])

    assert inserted is False
    assert conversation.history == []


def test_prepare_api_conversation_applies_budget_and_persists_records(
    tmp_path: Path,
) -> None:
    big_output = "x" * (SINGLE_RESULT_CHAR_LIMIT + 1)
    conversation = ConversationManager()
    conversation.history.append(
        Message(
            role="user",
            content="",
            tool_results=[ToolResultBlock("tool-1", big_output)],
        )
    )
    state = create_replacement_state()

    api_conversation, records = prepare_api_conversation(
        conversation,
        tmp_path,
        state,
    )

    original_result = conversation.history[0].tool_results[0]
    api_result = api_conversation.history[0].tool_results[0]
    stored_records = load_replacement_records(tmp_path)

    assert original_result.content == big_output
    assert api_result.content.startswith(PERSISTED_TAG)
    assert [record.tool_use_id for record in records] == ["tool-1"]
    assert [record.tool_use_id for record in stored_records] == ["tool-1"]
    assert state.seen_ids == {"tool-1"}
    assert "tool-1" in state.replacements
