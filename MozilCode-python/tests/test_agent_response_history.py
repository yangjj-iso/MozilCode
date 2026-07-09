from __future__ import annotations

from mozilcode.agent.response_history import (
    add_final_response,
    add_tool_call_response,
    response_snapshot_summary,
    response_thinking_blocks,
    snapshot_file_history,
    tool_use_blocks,
)
from mozilcode.agent.stream import LLMResponse, ThinkingBlock
from mozilcode.conversation import ConversationManager
from mozilcode.tools.base import ToolCallComplete


def _response() -> LLMResponse:
    return LLMResponse(
        text="hello",
        tool_calls=[
            ToolCallComplete(
                tool_id="tool-1",
                tool_name="ReadFile",
                arguments={"file_path": "README.md"},
            )
        ],
        thinking_blocks=[ThinkingBlock("thought", "sig")],
        input_tokens=10,
        output_tokens=3,
        cache_read=2,
        cache_creation=1,
    )


def test_response_thinking_blocks_converts_stream_blocks() -> None:
    blocks = response_thinking_blocks(_response())

    assert len(blocks) == 1
    assert blocks[0].thinking == "thought"
    assert blocks[0].signature == "sig"


def test_tool_use_blocks_converts_tool_calls() -> None:
    blocks = tool_use_blocks(_response().tool_calls)

    assert len(blocks) == 1
    assert blocks[0].tool_use_id == "tool-1"
    assert blocks[0].tool_name == "ReadFile"
    assert blocks[0].arguments == {"file_path": "README.md"}


def test_add_final_response_records_assistant_message_with_thinking() -> None:
    conversation = ConversationManager()

    add_final_response(conversation, _response())

    assert len(conversation.history) == 1
    message = conversation.history[0]
    assert message.role == "assistant"
    assert message.content == "hello"
    assert message.tool_uses == []
    assert message.thinking_blocks[0].thinking == "thought"


def test_add_tool_call_response_records_tool_uses_and_usage_anchor() -> None:
    conversation = ConversationManager()

    tool_uses = add_tool_call_response(conversation, _response())

    assert len(tool_uses) == 1
    assert len(conversation.history) == 1
    assert conversation.history[0].tool_uses[0].tool_name == "ReadFile"
    assert conversation.baseline_tokens == 16
    assert conversation.anchor_count == 1
    assert conversation.last_input_tokens == 16


def test_add_tool_call_response_can_preserve_empty_thinking_blocks() -> None:
    conversation = ConversationManager()

    add_tool_call_response(conversation, _response(), thinking_blocks=[])

    assert conversation.history[0].thinking_blocks == []


def test_response_snapshot_summary_truncates_long_text() -> None:
    assert response_snapshot_summary("abcdef", limit=4) == "abcd..."
    assert response_snapshot_summary("abc", limit=4) == "abc"


class RecordingFileHistory:
    def __init__(self) -> None:
        self.snapshots: list[tuple[int, str]] = []

    def make_snapshot(self, msg_index: int, user_text: str) -> None:
        self.snapshots.append((msg_index, user_text))


def test_snapshot_file_history_records_current_message_count() -> None:
    conversation = ConversationManager()
    conversation.add_user_message("hello")
    file_history = RecordingFileHistory()

    snapshot_file_history(file_history, conversation, "x" * 65)

    assert file_history.snapshots == [(1, "x" * 60 + "...")]


def test_snapshot_file_history_ignores_missing_file_history() -> None:
    conversation = ConversationManager()

    snapshot_file_history(None, conversation, "ignored")

    assert conversation.history == []
