from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.client import (
    LLMError,
    OpenAIClient,
    OpenAICompatClient,
    RateLimitError as CLIENT_RATE_LIMIT_ERROR,
    _rate_limit_error,
    _stream_end_from_openai_chat_usage,
    _stream_end_from_openai_response_usage,
)
from mozilcode.config import ProviderConfig
from mozilcode.conversation import ConversationManager
from mozilcode.llm_errors import (
    LLMError as BASE_LLM_ERROR,
    RateLimitError,
    rate_limit_error,
)
from mozilcode.openai_streaming import (
    stream_end_from_openai_chat_usage,
    stream_end_from_openai_response_usage,
)
from mozilcode.tools.base import (
    StreamEnd,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)


class _AsyncStream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


async def _collect(stream):
    result = []
    async for event in stream:
        result.append(event)
    return result


def test_client_keeps_openai_streaming_helper_exports():
    assert _stream_end_from_openai_chat_usage is stream_end_from_openai_chat_usage
    assert (
        _stream_end_from_openai_response_usage
        is stream_end_from_openai_response_usage
    )


def test_client_keeps_llm_error_exports():
    assert LLMError is BASE_LLM_ERROR
    assert CLIENT_RATE_LIMIT_ERROR is RateLimitError
    assert _rate_limit_error is rate_limit_error


@pytest.mark.asyncio
async def test_openai_responses_streams_reasoning_summary():
    captured = {}

    class Responses:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _AsyncStream([
                SimpleNamespace(type="response.reasoning_summary_text.delta", delta="先分析"),
                SimpleNamespace(type="response.output_text.delta", delta="答案"),
                SimpleNamespace(type="response.reasoning_summary_text.done", text=""),
                SimpleNamespace(type="response.completed", response=SimpleNamespace(usage=None)),
            ])

    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-test"
    client.thinking = True
    client.max_output_tokens = 1024
    client._client = SimpleNamespace(responses=Responses())

    events = await _collect(client.stream(ConversationManager()))

    assert captured["reasoning"] == {"summary": "auto"}
    assert any(isinstance(e, ThinkingDelta) and e.text == "先分析" for e in events)
    assert any(isinstance(e, ThinkingComplete) and e.thinking == "先分析" for e in events)
    assert any(isinstance(e, TextDelta) and e.text == "答案" for e in events)
    assert any(isinstance(e, StreamEnd) for e in events)


@pytest.mark.asyncio
async def test_openai_responses_streams_function_call_arguments():
    class Responses:
        async def create(self, **_kwargs):
            return _AsyncStream([
                SimpleNamespace(
                    type="response.output_item.added",
                    item=SimpleNamespace(
                        type="function_call",
                        name="Bash",
                        call_id="call-1",
                    ),
                ),
                SimpleNamespace(
                    type="response.function_call_arguments.delta",
                    delta='{"command":"git',
                ),
                SimpleNamespace(
                    type="response.function_call_arguments.delta",
                    delta=' status"}',
                ),
                SimpleNamespace(type="response.function_call_arguments.done"),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(usage=None),
                ),
            ])

    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-test"
    client.thinking = False
    client.max_output_tokens = 1024
    client._client = SimpleNamespace(responses=Responses())

    events = await _collect(client.stream(ConversationManager()))

    assert events[:4] == [
        ToolCallStart(tool_name="Bash", tool_id="call-1"),
        ToolCallDelta(text='{"command":"git'),
        ToolCallDelta(text=' status"}'),
        ToolCallComplete(
            tool_id="call-1",
            tool_name="Bash",
            arguments={"command": "git status"},
        ),
    ]
    assert any(isinstance(e, StreamEnd) for e in events)


@pytest.mark.asyncio
async def test_openai_compat_streams_reasoning_content():
    class Completions:
        async def create(self, **_kwargs):
            return _AsyncStream([
                SimpleNamespace(
                    choices=[SimpleNamespace(
                        delta=SimpleNamespace(
                            reasoning_content="先想",
                            content=None,
                            tool_calls=None,
                        ),
                        finish_reason=None,
                    )],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(
                        delta=SimpleNamespace(content="回答", tool_calls=None),
                        finish_reason="stop",
                    )],
                    usage=None,
                ),
            ])

    client = OpenAICompatClient.__new__(OpenAICompatClient)
    client.model = "compat-test"
    client.thinking = True
    client.max_output_tokens = 1024
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )

    events = await _collect(client.stream(ConversationManager()))

    assert any(isinstance(e, ThinkingDelta) and e.text == "先想" for e in events)
    assert any(isinstance(e, ThinkingComplete) and e.thinking == "先想" for e in events)
    assert any(isinstance(e, TextDelta) and e.text == "回答" for e in events)


def test_local_openai_base_url_allows_empty_api_key():
    config = ProviderConfig(
        name="local",
        protocol="openai",
        base_url="http://127.0.0.1:8080",
        model="local-model",
        api_key="",
    )

    client = OpenAIClient(config)

    assert client.model == "local-model"


def test_openai_response_usage_excludes_cached_tokens_from_input():
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=250,
        input_tokens_details=SimpleNamespace(cached_tokens=700),
    )

    event = _stream_end_from_openai_response_usage(usage)

    assert event == StreamEnd(
        stop_reason="end_turn",
        input_tokens=300,
        output_tokens=250,
        cache_read=700,
        cache_creation=0,
    )


def test_openai_chat_usage_excludes_cached_tokens_from_prompt():
    usage = SimpleNamespace(
        prompt_tokens=1200,
        completion_tokens=180,
        prompt_tokens_details=SimpleNamespace(cached_tokens=500),
    )

    event = _stream_end_from_openai_chat_usage(usage)

    assert event == StreamEnd(
        stop_reason="end_turn",
        input_tokens=700,
        output_tokens=180,
        cache_read=500,
        cache_creation=0,
    )


def test_openai_usage_never_reports_negative_uncached_input():
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=10,
        input_tokens_details=SimpleNamespace(cached_tokens=300),
    )

    event = _stream_end_from_openai_response_usage(usage)

    assert event.input_tokens == 0
    assert event.cache_read == 300


def test_rate_limit_error_extracts_numeric_retry_after():
    source = RuntimeError("rate limited")
    source.response = SimpleNamespace(headers={"retry-after": "2.5"})

    error = _rate_limit_error(source)

    assert isinstance(error, RateLimitError)
    assert error.retry_after == 2.5
    assert str(error) == "Rate limited. Retry after 2.5s."


def test_rate_limit_error_ignores_missing_retry_after():
    source = RuntimeError("rate limited")

    error = _rate_limit_error(source)

    assert error.retry_after is None
    assert str(error) == "Rate limited. Please wait."


def test_rate_limit_error_ignores_non_numeric_retry_after():
    source = RuntimeError("rate limited")
    source.response = SimpleNamespace(headers={"retry-after": "soon"})

    error = _rate_limit_error(source)

    assert error.retry_after is None
    assert str(error) == "Rate limited. Please wait."
