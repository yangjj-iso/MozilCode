from __future__ import annotations

from types import SimpleNamespace

from mozilcode.providers.anthropic_streaming import AnthropicStreamState, parse_tool_arguments
from mozilcode.tools.base import (
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)


def test_parse_tool_arguments_returns_empty_for_invalid_json() -> None:
    assert parse_tool_arguments("{bad") == {}
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments("[]") == {}


def test_anthropic_stream_state_accumulates_thinking() -> None:
    state = AnthropicStreamState()

    assert state.start_block(SimpleNamespace(type="thinking")) is None
    events = state.add_delta(SimpleNamespace(type="thinking_delta", thinking="think"))
    events += state.add_delta(
        SimpleNamespace(type="signature_delta", signature="sig-1")
    )
    events += state.stop_block()

    assert events == [
        ThinkingDelta(text="think"),
        ThinkingComplete(thinking="think", signature="sig-1"),
    ]
    assert state == AnthropicStreamState()


def test_anthropic_stream_state_accumulates_tool_arguments() -> None:
    state = AnthropicStreamState()

    start = state.start_block(
        SimpleNamespace(type="tool_use", name="Bash", id="tool-1")
    )
    events = state.add_delta(
        SimpleNamespace(type="input_json_delta", partial_json='{"command":"git')
    )
    events += state.add_delta(
        SimpleNamespace(type="input_json_delta", partial_json=' status"}')
    )
    events += state.stop_block()

    assert start == ToolCallStart(tool_name="Bash", tool_id="tool-1")
    assert events == [
        ToolCallDelta(text='{"command":"git'),
        ToolCallDelta(text=' status"}'),
        ToolCallComplete(
            tool_id="tool-1",
            tool_name="Bash",
            arguments={"command": "git status"},
        ),
    ]
    assert state == AnthropicStreamState()
