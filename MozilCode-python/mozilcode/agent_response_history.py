from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mozilcode.agent_stream import LLMResponse
from mozilcode.conversation import ConversationManager, ToolUseBlock
from mozilcode.conversation import ThinkingBlock as ConvThinkingBlock
from mozilcode.tools.base import ToolCallComplete


def response_thinking_blocks(response: LLMResponse) -> list[ConvThinkingBlock]:
    return [
        ConvThinkingBlock(thinking=block.thinking, signature=block.signature)
        for block in response.thinking_blocks
    ]


def tool_use_blocks(tool_calls: Iterable[ToolCallComplete]) -> list[ToolUseBlock]:
    return [
        ToolUseBlock(
            tool_use_id=tool_call.tool_id,
            tool_name=tool_call.tool_name,
            arguments=tool_call.arguments,
        )
        for tool_call in tool_calls
    ]


def add_final_response(
    conversation: ConversationManager,
    response: LLMResponse,
    *,
    thinking_blocks: list[ConvThinkingBlock] | None = None,
) -> None:
    conversation.add_assistant_message(
        response.text,
        thinking_blocks=(
            response_thinking_blocks(response)
            if thinking_blocks is None
            else thinking_blocks
        ),
    )


def add_tool_call_response(
    conversation: ConversationManager,
    response: LLMResponse,
    *,
    thinking_blocks: list[ConvThinkingBlock] | None = None,
) -> list[ToolUseBlock]:
    tool_uses = tool_use_blocks(response.tool_calls)
    conversation.add_assistant_message(
        response.text,
        tool_uses,
        thinking_blocks=(
            response_thinking_blocks(response)
            if thinking_blocks is None
            else thinking_blocks
        ),
    )
    conversation.record_usage_anchor(
        response.input_tokens,
        response.output_tokens,
        response.cache_read,
        response.cache_creation,
    )
    return tool_uses


def response_snapshot_summary(text: str, limit: int = 60) -> str:
    return text[:limit] + "..." if len(text) > limit else text


def snapshot_file_history(
    file_history: Any,
    conversation: ConversationManager,
    response_text: str,
) -> None:
    if file_history is None:
        return
    file_history.make_snapshot(
        len(conversation.history),
        response_snapshot_summary(response_text),
    )
