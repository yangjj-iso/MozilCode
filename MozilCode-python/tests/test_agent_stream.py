from __future__ import annotations

import asyncio

import mozilcode.agent as agent_module
from mozilcode.agent.events import StreamText, ThinkingText, ToolUseEvent
from mozilcode.agent.stream import LLMResponse, StreamCollector, ThinkingBlock
from mozilcode.tools.base import (
    StreamEnd,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
)


def test_agent_reexports_stream_collector_types_for_compatibility() -> None:
    assert agent_module.StreamCollector is StreamCollector
    assert agent_module.LLMResponse is LLMResponse
    assert agent_module.ThinkingBlock is ThinkingBlock


def test_stream_collector_yields_agent_events_and_collects_response() -> None:
    async def stream():
        yield TextDelta("hello ")
        yield ThinkingDelta("thinking")
        yield ThinkingComplete("full thought", "sig-1")
        yield ToolCallComplete("tool-1", "ReadFile", {"file_path": "README.md"})
        yield StreamEnd(
            stop_reason="tool_use",
            input_tokens=11,
            output_tokens=7,
            cache_read=3,
            cache_creation=5,
        )

    async def collect():
        collector = StreamCollector()
        events = [event async for event in collector.consume(stream())]
        return collector.response, events

    response, events = asyncio.run(collect())

    assert events == [
        StreamText("hello "),
        ThinkingText("thinking"),
        ToolUseEvent("ReadFile", "tool-1", {"file_path": "README.md"}),
    ]
    assert response.text == "hello "
    assert response.thinking_blocks == [ThinkingBlock("full thought", "sig-1")]
    assert response.tool_calls == [
        ToolCallComplete("tool-1", "ReadFile", {"file_path": "README.md"})
    ]
    assert response.stop_reason == "tool_use"
    assert response.input_tokens == 11
    assert response.output_tokens == 7
    assert response.cache_read == 3
    assert response.cache_creation == 5
