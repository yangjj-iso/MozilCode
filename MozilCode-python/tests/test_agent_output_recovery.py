from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from mozilcode.agent import Agent
from mozilcode.agent_events import LoopComplete, RetryEvent
from mozilcode.agent_output_recovery import (
    MAX_TOKENS_CEILING,
    MAX_TOKENS_ESCALATION_PROMPT,
    MAX_TOKENS_RECOVERY_PROMPT,
    OutputRecoveryState,
    handle_output_token_limit,
)
from mozilcode.agent_stream import LLMResponse
from mozilcode.client import LLMClient
from mozilcode.conversation import ConversationManager
from mozilcode.conversation import ThinkingBlock as ConvThinkingBlock
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import StreamEnd, StreamEvent, TextDelta


class FakeClient:
    def __init__(self) -> None:
        self.max_output_tokens: int | None = None

    def set_max_output_tokens(self, tokens: int) -> None:
        self.max_output_tokens = tokens


class ScriptedClient(LLMClient):
    def __init__(self, responses: list[list[StreamEvent]]) -> None:
        self.responses = list(responses)
        self.max_output_tokens: int | None = None

    def set_max_output_tokens(self, tokens: int) -> None:
        self.max_output_tokens = tokens

    async def stream(
        self,
        conversation: ConversationManager,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        del conversation, system, tools
        for event in self.responses.pop(0):
            yield event


def _response(
    *,
    stop_reason: str = "max_tokens",
    text: str = "partial",
) -> LLMResponse:
    return LLMResponse(text=text, stop_reason=stop_reason)


def test_non_max_tokens_resets_recovery_count_without_retry() -> None:
    client = FakeClient()
    conversation = ConversationManager()

    decision = handle_output_token_limit(
        response=_response(stop_reason="end_turn"),
        conversation=conversation,
        client=client,
        thinking_blocks=[],
        state=OutputRecoveryState(max_tokens_escalated=True, output_recoveries=2),
    )

    assert decision.retry_event is None
    assert decision.state == OutputRecoveryState(
        max_tokens_escalated=True,
        output_recoveries=0,
    )
    assert conversation.history == []
    assert client.max_output_tokens is None


def test_first_max_tokens_escalates_client_and_adds_resume_prompt() -> None:
    client = FakeClient()
    conversation = ConversationManager()
    thinking = [ConvThinkingBlock("thought", "sig")]

    decision = handle_output_token_limit(
        response=_response(text="partial answer"),
        conversation=conversation,
        client=client,
        thinking_blocks=thinking,
        state=OutputRecoveryState(),
    )

    assert client.max_output_tokens == MAX_TOKENS_CEILING
    assert decision.retry_event is not None
    assert decision.retry_event.reason == "max_tokens escalation"
    assert decision.state == OutputRecoveryState(
        max_tokens_escalated=True,
        output_recoveries=0,
    )
    assert [message.role for message in conversation.history] == ["assistant", "user"]
    assert conversation.history[0].content == "partial answer"
    assert conversation.history[0].thinking_blocks == thinking
    assert conversation.history[1].content == MAX_TOKENS_ESCALATION_PROMPT


def test_first_escalation_without_text_does_not_add_empty_messages() -> None:
    client = FakeClient()
    conversation = ConversationManager()

    decision = handle_output_token_limit(
        response=_response(text=""),
        conversation=conversation,
        client=client,
        thinking_blocks=[],
        state=OutputRecoveryState(),
    )

    assert decision.retry_event is not None
    assert conversation.history == []


def test_subsequent_max_tokens_adds_recovery_prompt() -> None:
    client = FakeClient()
    conversation = ConversationManager()

    decision = handle_output_token_limit(
        response=_response(text="more partial"),
        conversation=conversation,
        client=client,
        thinking_blocks=[],
        state=OutputRecoveryState(max_tokens_escalated=True, output_recoveries=1),
    )

    assert decision.retry_event is not None
    assert decision.retry_event.reason == "max_tokens recovery 2/3"
    assert decision.state == OutputRecoveryState(
        max_tokens_escalated=True,
        output_recoveries=2,
    )
    assert [message.content for message in conversation.history] == [
        "more partial",
        MAX_TOKENS_RECOVERY_PROMPT,
    ]
    assert client.max_output_tokens is None


def test_max_tokens_stops_retry_after_recovery_limit() -> None:
    client = FakeClient()
    conversation = ConversationManager()
    state = OutputRecoveryState(max_tokens_escalated=True, output_recoveries=3)

    decision = handle_output_token_limit(
        response=_response(text="final partial"),
        conversation=conversation,
        client=client,
        thinking_blocks=[],
        state=state,
    )

    assert decision.retry_event is None
    assert decision.state is state
    assert conversation.history == []


@pytest.mark.asyncio
async def test_agent_run_retries_after_output_token_escalation() -> None:
    client = ScriptedClient(
        [
            [
                TextDelta("partial"),
                StreamEnd("max_tokens", input_tokens=10, output_tokens=20),
            ],
            [
                TextDelta(" done"),
                StreamEnd("end_turn", input_tokens=12, output_tokens=5),
            ],
        ]
    )
    agent = Agent(client, ToolRegistry(), "anthropic")
    conversation = ConversationManager()
    conversation.add_user_message("write a long answer")

    events = [event async for event in agent.run(conversation)]

    retry_events = [event for event in events if isinstance(event, RetryEvent)]
    loop_events = [event for event in events if isinstance(event, LoopComplete)]
    assert client.max_output_tokens == MAX_TOKENS_CEILING
    assert [event.reason for event in retry_events] == ["max_tokens escalation"]
    assert loop_events[-1].total_turns == 2
    assert any(
        message.role == "user" and message.content == MAX_TOKENS_ESCALATION_PROMPT
        for message in conversation.history
    )
