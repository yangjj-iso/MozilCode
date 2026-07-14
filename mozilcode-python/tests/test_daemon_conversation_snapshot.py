from mozilcode.conversation import ConversationManager, ThinkingBlock, ToolResultBlock, ToolUseBlock
from mozilcode.daemon.session.conversation_snapshot import (
    restore_conversation,
    restore_conversation_from_events,
    serialize_conversation,
)


def test_snapshot_round_trip_preserves_model_visible_blocks() -> None:
    conversation = ConversationManager()
    conversation.add_user_message("inspect this")
    conversation.add_assistant_message(
        "I will inspect it",
        tool_uses=[ToolUseBlock("call-1", "ReadFile", {"file_path": "a.py"})],
        thinking_blocks=[ThinkingBlock("checking", "signature")],
    )
    conversation.add_tool_results_message([ToolResultBlock("call-1", "contents")])

    restored = restore_conversation(serialize_conversation(conversation))

    assert restored.get_messages() == conversation.get_messages()


def test_legacy_events_migrate_to_a_continuable_conversation() -> None:
    restored = restore_conversation_from_events([
        {"type": "UserMessage", "data": {"content": "inspect this"}},
        {"type": "StreamText", "data": {"text": "I will inspect it"}},
        {"type": "ToolUseEvent", "data": {"tool_id": "call-1", "tool_name": "ReadFile", "arguments": {"file_path": "a.py"}}},
        {"type": "ToolResultEvent", "data": {"tool_id": "call-1", "output": "contents", "is_error": False}},
        {"type": "LoopComplete", "data": {}},
    ])

    assert [(message.role, message.content) for message in restored.history] == [
        ("user", "inspect this"),
        ("assistant", "I will inspect it"),
        ("user", ""),
    ]
    assert restored.history[1].tool_uses[0].tool_use_id == "call-1"
    assert restored.history[2].tool_results[0].content == "contents"
