from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.client import OpenAIClient, OpenAICompatClient
from mozilcode.config import ProviderConfig
from mozilcode.conversation import ConversationManager
from mozilcode.tools.base import StreamEnd, TextDelta, ThinkingComplete, ThinkingDelta


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
