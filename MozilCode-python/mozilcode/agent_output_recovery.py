from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mozilcode.agent_events import RetryEvent
from mozilcode.agent_stream import LLMResponse
from mozilcode.conversation import ConversationManager
from mozilcode.conversation import ThinkingBlock as ConvThinkingBlock


MAX_TOKENS_CEILING = 64000
MAX_OUTPUT_TOKENS_RECOVERIES = 3
MAX_TOKENS_ESCALATION_PROMPT = (
    "Output token limit hit. Resume directly from where you stopped. "
    "Do not apologize or repeat previous content. Pick up mid-thought if needed."
)
MAX_TOKENS_RECOVERY_PROMPT = (
    "Output token limit hit. Resume directly from where you stopped. "
    "Break remaining work into smaller pieces."
)


class MaxOutputTokenClient(Protocol):
    def set_max_output_tokens(self, tokens: int) -> None: ...


@dataclass(frozen=True)
class OutputRecoveryState:
    max_tokens_escalated: bool = False
    output_recoveries: int = 0


@dataclass(frozen=True)
class OutputRecoveryDecision:
    state: OutputRecoveryState
    retry_event: RetryEvent | None = None


def handle_output_token_limit(
    *,
    response: LLMResponse,
    conversation: ConversationManager,
    client: MaxOutputTokenClient,
    thinking_blocks: list[ConvThinkingBlock],
    state: OutputRecoveryState,
    max_tokens_ceiling: int = MAX_TOKENS_CEILING,
    max_recoveries: int = MAX_OUTPUT_TOKENS_RECOVERIES,
) -> OutputRecoveryDecision:
    if response.stop_reason != "max_tokens":
        return OutputRecoveryDecision(
            OutputRecoveryState(
                max_tokens_escalated=state.max_tokens_escalated,
                output_recoveries=0,
            )
        )

    if not state.max_tokens_escalated:
        client.set_max_output_tokens(max_tokens_ceiling)
        if response.text:
            conversation.add_assistant_message(
                response.text,
                thinking_blocks=thinking_blocks,
            )
            conversation.add_user_message(MAX_TOKENS_ESCALATION_PROMPT)
        return OutputRecoveryDecision(
            OutputRecoveryState(max_tokens_escalated=True, output_recoveries=0),
            RetryEvent(reason="max_tokens escalation"),
        )

    if state.output_recoveries < max_recoveries:
        output_recoveries = state.output_recoveries + 1
        conversation.add_assistant_message(
            response.text,
            thinking_blocks=thinking_blocks,
        )
        conversation.add_user_message(MAX_TOKENS_RECOVERY_PROMPT)
        return OutputRecoveryDecision(
            OutputRecoveryState(
                max_tokens_escalated=True,
                output_recoveries=output_recoveries,
            ),
            RetryEvent(
                reason=f"max_tokens recovery {output_recoveries}/{max_recoveries}"
            ),
        )

    return OutputRecoveryDecision(state)
