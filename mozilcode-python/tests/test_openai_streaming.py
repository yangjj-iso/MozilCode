"""OpenAI 流式载荷转内部事件/用量测试。"""

from __future__ import annotations

from types import SimpleNamespace

from mozilcode.providers.openai_streaming import (
    OpenAIChatToolCallState,
    OpenAIReasoningState,
    OpenAIResponseToolCallState,
    parse_tool_arguments,
)
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


def test_response_tool_call_state_starts_from_output_item() -> None:
    state = OpenAIResponseToolCallState()

    event = state.add_output_item(
        SimpleNamespace(type="function_call", name="ReadFile", call_id="call-1")
    )

    assert event == ToolCallStart(tool_name="ReadFile", tool_id="call-1")
    assert state.tool_name == "ReadFile"
    assert state.call_id == "call-1"
    assert state.arguments_json == ""


def test_response_tool_call_state_accumulates_delta_and_completes() -> None:
    state = OpenAIResponseToolCallState()

    events = state.add_arguments_delta(
        SimpleNamespace(name="ReadFile", call_id="call-1", delta='{"path":')
    )
    events += state.add_arguments_delta(SimpleNamespace(delta='"README.md"}'))
    complete = state.complete(SimpleNamespace())

    assert events == [
        ToolCallStart(tool_name="ReadFile", tool_id="call-1"),
        ToolCallDelta(text='{"path":'),
        ToolCallDelta(text='"README.md"}'),
    ]
    assert complete == ToolCallComplete(
        tool_id="call-1",
        tool_name="ReadFile",
        arguments={"path": "README.md"},
    )
    assert state == OpenAIResponseToolCallState()


def test_response_tool_call_state_allows_identity_on_done_event() -> None:
    state = OpenAIResponseToolCallState()

    events = state.add_arguments_delta(SimpleNamespace(delta='{"query":"x"}'))
    complete = state.complete(SimpleNamespace(name="Search", call_id="call-2"))

    assert events == [ToolCallDelta(text='{"query":"x"}')]
    assert complete == ToolCallComplete(
        tool_id="call-2",
        tool_name="Search",
        arguments={"query": "x"},
    )


def test_chat_tool_call_state_accumulates_by_index_and_completes_sorted() -> None:
    state = OpenAIChatToolCallState()

    events = state.add_tool_call_deltas([
        SimpleNamespace(
            index=1,
            id="call-b",
            function=SimpleNamespace(name="Grep", arguments='{"pattern":"x"}'),
        ),
        SimpleNamespace(
            index=0,
            id="call-a",
            function=SimpleNamespace(name="ReadFile", arguments='{"path":'),
        ),
    ])
    events += state.add_tool_call_deltas([
        SimpleNamespace(
            index=0,
            id="",
            function=SimpleNamespace(name="", arguments='"README.md"}'),
        )
    ])
    completed = state.complete()

    assert events == [
        ToolCallStart(tool_name="Grep", tool_id="call-b"),
        ToolCallDelta(text='{"pattern":"x"}'),
        ToolCallStart(tool_name="ReadFile", tool_id="call-a"),
        ToolCallDelta(text='{"path":'),
        ToolCallDelta(text='"README.md"}'),
    ]
    assert completed == [
        ToolCallComplete(
            tool_id="call-a",
            tool_name="ReadFile",
            arguments={"path": "README.md"},
        ),
        ToolCallComplete(
            tool_id="call-b",
            tool_name="Grep",
            arguments={"pattern": "x"},
        ),
    ]
    assert state.active_calls == {}


def test_chat_tool_call_state_uses_empty_args_for_invalid_json() -> None:
    state = OpenAIChatToolCallState()

    state.add_tool_call_deltas([
        SimpleNamespace(
            index=0,
            id="call-1",
            function=SimpleNamespace(name="Bash", arguments="{bad"),
        )
    ])

    assert state.complete() == [
        ToolCallComplete(tool_id="call-1", tool_name="Bash", arguments={})
    ]


def test_openai_reasoning_state_accumulates_and_completes() -> None:
    state = OpenAIReasoningState()

    events = state.add_delta("think")
    events += state.complete_from_done_text("")

    assert events == [
        ThinkingDelta(text="think"),
        ThinkingComplete(thinking="think", signature=""),
    ]
    assert state == OpenAIReasoningState(text="think", completed=True)


def test_openai_reasoning_state_avoids_duplicate_done_text() -> None:
    state = OpenAIReasoningState()

    events = state.add_delta("think")
    events += state.complete_from_done_text("think")

    assert events == [
        ThinkingDelta(text="think"),
        ThinkingComplete(thinking="think", signature=""),
    ]


def test_openai_reasoning_state_completes_from_summary_once() -> None:
    state = OpenAIReasoningState()

    events = state.complete_from_summary("summary")
    events += state.complete_from_summary("ignored")

    assert events == [
        ThinkingDelta(text="summary"),
        ThinkingComplete(thinking="summary", signature=""),
    ]
    assert state == OpenAIReasoningState(text="summary", completed=True)
