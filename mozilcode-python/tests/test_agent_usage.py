"""Token 用量累计与 UsageEvent 测试。"""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from mozilcode.agent import Agent
from mozilcode.agent.stream import LLMResponse
from mozilcode.agent.usage import (
    UsageTotals,
    accumulate_response_usage,
    response_context_tokens,
    usage_callback_payload,
)
from mozilcode.client import LLMClient
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import StreamEnd, StreamEvent, TextDelta


class ScriptedClient(LLMClient):
    def __init__(self, responses: list[list[StreamEvent]]) -> None:
        self.responses = list(responses)

    async def stream(
        self,
        conversation,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        del conversation, system, tools
        for event in self.responses.pop(0):
            yield event


def _response() -> LLMResponse:
    return LLMResponse(
        input_tokens=10,
        output_tokens=5,
        cache_read=3,
        cache_creation=2,
    )


def test_response_context_tokens_includes_cache_components() -> None:
    assert response_context_tokens(_response()) == 20


def test_accumulate_response_usage_adds_to_existing_totals() -> None:
    update = accumulate_response_usage(
        UsageTotals(input_tokens=100, output_tokens=50),
        _response(),
    )

    assert update.totals == UsageTotals(input_tokens=110, output_tokens=55)
    assert update.event.input_tokens == 110
    assert update.event.output_tokens == 55
    assert update.event.context_tokens == 20


def test_usage_callback_payload_uses_frontend_field_names() -> None:
    assert usage_callback_payload(UsageTotals(input_tokens=7, output_tokens=4)) == {
        "type": "usage",
        "usage": {
            "inputTokens": 7,
            "outputTokens": 4,
        },
    }


@pytest.mark.asyncio
async def test_run_to_completion_emits_usage_callback_from_totals() -> None:
    client = ScriptedClient(
        [
            [
                TextDelta("done"),
                StreamEnd("end_turn", input_tokens=11, output_tokens=6),
            ],
        ]
    )
    agent = Agent(client, ToolRegistry(), "anthropic")
    callbacks: list[dict[str, Any]] = []

    result = await agent.run_to_completion(
        "finish",
        event_callback=callbacks.append,
    )

    usage_events = [event for event in callbacks if event["type"] == "usage"]
    assert result == "done"
    assert agent.total_input_tokens == 11
    assert agent.total_output_tokens == 6
    assert usage_events == [
        {
            "type": "usage",
            "usage": {
                "inputTokens": 11,
                "outputTokens": 6,
            },
        }
    ]
