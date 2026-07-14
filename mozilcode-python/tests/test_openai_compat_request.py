"""OpenAI 兼容 Chat Completions 请求构造测试。"""

from __future__ import annotations

from mozilcode.providers.openai_compat_request import (
    build_chat_completion_request_kwargs,
    convert_tools_for_chat_completions,
)


def test_convert_tools_prefers_parameters_shape() -> None:
    tools = [
        {
            "type": "function",
            "name": "ReadFile",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        }
    ]

    assert convert_tools_for_chat_completions(tools) == [
        {
            "type": "function",
            "function": {
                "name": "ReadFile",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
    ]


def test_convert_tools_accepts_input_schema_shape() -> None:
    tools = [
        {
            "name": "MCPTool",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        }
    ]

    converted = convert_tools_for_chat_completions(tools)

    assert converted[0]["function"] == {
        "name": "MCPTool",
        "description": "",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    }


def test_build_chat_completion_request_kwargs_keeps_messages_immutable() -> None:
    messages = [{"role": "user", "content": "hello"}]

    kwargs = build_chat_completion_request_kwargs(
        model="gpt-local",
        max_output_tokens=512,
        messages=messages,
        system="system prompt",
        tools=[{"name": "Noop", "parameters": {"type": "object"}}],
    )

    assert messages == [{"role": "user", "content": "hello"}]
    assert kwargs["model"] == "gpt-local"
    assert kwargs["max_tokens"] == 512
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
    assert kwargs["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hello"},
    ]
    assert kwargs["tools"][0]["function"]["name"] == "Noop"


def test_build_chat_completion_request_kwargs_omits_empty_tools() -> None:
    kwargs = build_chat_completion_request_kwargs(
        model="gpt-local",
        max_output_tokens=512,
        messages=[],
        tools=[],
    )

    assert "tools" not in kwargs


def test_build_chat_completion_request_kwargs_enables_thinking_with_extra_body() -> None:
    kwargs = build_chat_completion_request_kwargs(
        model="thinking-model",
        max_output_tokens=512,
        messages=[],
        thinking=True,
    )

    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
