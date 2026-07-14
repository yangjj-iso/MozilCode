"""Token 用量累计与 UsageEvent。

根据 LLMResponse 累加会话 input/output tokens，
生成 UsageEvent 与子 Agent event_callback 用的 payload。
"""

from __future__ import annotations

from dataclasses import dataclass

from mozilcode.agent.events import UsageEvent
from mozilcode.agent.stream import LLMResponse


@dataclass(frozen=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class UsageUpdate:
    totals: UsageTotals
    event: UsageEvent


def response_context_tokens(response: LLMResponse) -> int:
    return (
        response.input_tokens
        + response.output_tokens
        + response.cache_read
        + response.cache_creation
    )


def accumulate_response_usage(
    totals: UsageTotals,
    response: LLMResponse,
) -> UsageUpdate:
    updated = UsageTotals(
        input_tokens=totals.input_tokens + response.input_tokens,
        output_tokens=totals.output_tokens + response.output_tokens,
    )
    return UsageUpdate(
        totals=updated,
        event=UsageEvent(
            input_tokens=updated.input_tokens,
            output_tokens=updated.output_tokens,
            context_tokens=response_context_tokens(response),
        ),
    )


def usage_callback_payload(totals: UsageTotals) -> dict[str, dict[str, int] | str]:
    return {
        "type": "usage",
        "usage": {
            "inputTokens": totals.input_tokens,
            "outputTokens": totals.output_tokens,
        },
    }
