from __future__ import annotations

from mozilcode.providers.anthropic_request import (
    EPHEMERAL_CACHE_CONTROL,
    build_anthropic_request_kwargs,
    mark_last_tool_for_cache,
    mark_last_user_tail_for_cache,
    supports_adaptive_thinking,
    thinking_config,
)
from mozilcode.client import (
    _mark_last_tool_for_cache,
    _mark_last_user_tail_for_cache,
    _supports_adaptive_thinking,
)


def test_marks_last_user_string_content_for_cache() -> None:
    messages = [
        {"role": "assistant", "content": "old"},
        {"role": "user", "content": "hello"},
    ]

    mark_last_user_tail_for_cache(messages)

    assert messages[-1]["content"] == [
        {
            "type": "text",
            "text": "hello",
            "cache_control": EPHEMERAL_CACHE_CONTROL,
        }
    ]


def test_marks_last_user_block_not_trailing_assistant() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "tail"},
            ],
        },
        {"role": "assistant", "content": "answer"},
    ]

    mark_last_user_tail_for_cache(messages)

    assert "cache_control" not in messages[0]["content"][0]
    assert messages[0]["content"][1]["cache_control"] == EPHEMERAL_CACHE_CONTROL


def test_marks_last_tool_without_mutating_registered_schema() -> None:
    tools = [
        {"name": "Read", "parameters": {}},
        {"name": "Write", "parameters": {"type": "object"}},
    ]

    marked = mark_last_tool_for_cache(tools)

    assert marked is not tools
    assert marked[0] is tools[0]
    assert marked[1] is not tools[1]
    assert "cache_control" not in tools[1]
    assert marked[1]["cache_control"] == EPHEMERAL_CACHE_CONTROL


def test_thinking_config_uses_adaptive_budget_only_for_supported_models() -> None:
    assert supports_adaptive_thinking("claude-sonnet-4-6") is True
    assert supports_adaptive_thinking("claude-sonnet-4-5") is False
    assert thinking_config("claude-sonnet-4-6", 8192) == {
        "type": "enabled",
        "budget_tokens": 0,
    }
    assert thinking_config("claude-sonnet-4-5", 8192) == {
        "type": "enabled",
        "budget_tokens": 8191,
    }


def test_build_anthropic_request_kwargs_applies_cache_and_thinking_policy() -> None:
    tools = [{"name": "Read", "parameters": {}}]
    messages = [{"role": "user", "content": "hello"}]

    kwargs = build_anthropic_request_kwargs(
        model="claude-sonnet-4-6",
        max_output_tokens=4096,
        messages=messages,
        system="be concise",
        tools=tools,
        thinking=True,
    )

    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 4096
    assert kwargs["messages"] is messages
    assert (
        kwargs["messages"][0]["content"][0]["cache_control"]
        == EPHEMERAL_CACHE_CONTROL
    )
    assert kwargs["system"][0]["cache_control"] == EPHEMERAL_CACHE_CONTROL
    assert kwargs["tools"][0]["cache_control"] == EPHEMERAL_CACHE_CONTROL
    assert "cache_control" not in tools[0]
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 0}


def test_client_keeps_anthropic_request_helper_exports() -> None:
    assert _mark_last_tool_for_cache is mark_last_tool_for_cache
    assert _mark_last_user_tail_for_cache is mark_last_user_tail_for_cache
    assert _supports_adaptive_thinking is supports_adaptive_thinking
