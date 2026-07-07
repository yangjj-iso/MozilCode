from __future__ import annotations

from mozilcode.openai_responses_request import build_openai_response_request_kwargs


def test_build_openai_response_request_kwargs_keeps_required_shape() -> None:
    input_messages = [{"role": "user", "content": "hello"}]

    kwargs = build_openai_response_request_kwargs(
        model="gpt-test",
        input_messages=input_messages,
    )

    assert kwargs == {
        "model": "gpt-test",
        "input": input_messages,
        "stream": True,
    }


def test_build_openai_response_request_kwargs_adds_optional_fields() -> None:
    tools = [
        {
            "type": "function",
            "name": "ReadFile",
            "description": "Read a file",
            "parameters": {"type": "object"},
        }
    ]

    kwargs = build_openai_response_request_kwargs(
        model="gpt-test",
        input_messages=[],
        system="system prompt",
        tools=tools,
        thinking=True,
    )

    assert kwargs["instructions"] == "system prompt"
    assert kwargs["tools"] is tools
    assert kwargs["reasoning"] == {"summary": "auto"}


def test_build_openai_response_request_kwargs_omits_empty_optionals() -> None:
    kwargs = build_openai_response_request_kwargs(
        model="gpt-test",
        input_messages=[],
        system="",
        tools=[],
        thinking=False,
    )

    assert "instructions" not in kwargs
    assert "tools" not in kwargs
    assert "reasoning" not in kwargs
