from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.client import AnthropicClient
from mozilcode.conversation import ConversationManager
from mozilcode.tools.base import (
    StreamEnd,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)


class _FakeAnthropicStream:
    def __init__(self, events, final_message):
        self._events = list(events)
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def get_final_message(self):
        return self._final_message


@pytest.mark.asyncio
async def test_anthropic_streams_thinking_tool_and_usage_events():
    class Messages:
        def stream(self, **_kwargs):
            return _FakeAnthropicStream(
                [
                    SimpleNamespace(
                        type="content_block_start",
                        content_block=SimpleNamespace(type="thinking"),
                    ),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="thinking_delta",
                            thinking="thinking",
                        ),
                    ),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="signature_delta",
                            signature="sig-1",
                        ),
                    ),
                    SimpleNamespace(type="content_block_stop"),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(type="text_delta", text="answer"),
                    ),
                    SimpleNamespace(
                        type="content_block_start",
                        content_block=SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            id="tool-1",
                        ),
                    ),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="input_json_delta",
                            partial_json='{"command":"git',
                        ),
                    ),
                    SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="input_json_delta",
                            partial_json=' status"}',
                        ),
                    ),
                    SimpleNamespace(type="content_block_stop"),
                ],
                SimpleNamespace(
                    stop_reason="end_turn",
                    usage=SimpleNamespace(input_tokens=11, output_tokens=7),
                ),
            )

    client = AnthropicClient.__new__(AnthropicClient)
    client.model = "claude-test"
    client.thinking = True
    client.max_output_tokens = 1024
    client._client = SimpleNamespace(messages=Messages())

    events = []
    async for event in client.stream(ConversationManager()):
        events.append(event)

    assert events == [
        ThinkingDelta(text="thinking"),
        ThinkingComplete(thinking="thinking", signature="sig-1"),
        TextDelta(text="answer"),
        ToolCallStart(tool_name="Bash", tool_id="tool-1"),
        ToolCallDelta(text='{"command":"git'),
        ToolCallDelta(text=' status"}'),
        ToolCallComplete(
            tool_id="tool-1",
            tool_name="Bash",
            arguments={"command": "git status"},
        ),
        StreamEnd(stop_reason="end_turn", input_tokens=11, output_tokens=7),
    ]
