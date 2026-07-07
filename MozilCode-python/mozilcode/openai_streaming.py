"""Helpers for translating OpenAI streaming payloads into MozilCode events."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from mozilcode.tools.base import (
    StreamEnd,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)

RESPONSE_REASONING_DELTA_EVENTS = {
    "response.reasoning_summary_text.delta",
    "response.reasoning_text.delta",
    "response.reasoning.delta",
}

RESPONSE_REASONING_DONE_EVENTS = {
    "response.reasoning_summary_text.done",
    "response.reasoning_text.done",
    "response.reasoning.done",
}


def as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            data = value.model_dump(exclude_none=True)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def get_text(value: Any, *names: str) -> str:
    for name in names:
        item = getattr(value, name, None)
        if isinstance(item, str) and item:
            return item
    data = as_dict(value)
    for name in names:
        item = data.get(name)
        if isinstance(item, str) and item:
            return item
    return ""


def parse_tool_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@dataclass
class OpenAIResponseToolCallState:
    tool_name: str = ""
    call_id: str = ""
    arguments_json: str = ""

    def _update_identity(self, source: Any) -> None:
        if not self.tool_name:
            self.tool_name = getattr(source, "name", "") or ""
        if not self.call_id:
            self.call_id = getattr(source, "call_id", "") or ""

    def add_output_item(self, item: Any) -> ToolCallStart | None:
        if not item or getattr(item, "type", "") != "function_call":
            return None
        self.tool_name = getattr(item, "name", "") or ""
        self.call_id = getattr(item, "call_id", "") or ""
        self.arguments_json = ""
        return ToolCallStart(tool_name=self.tool_name, tool_id=self.call_id)

    def add_arguments_delta(
        self,
        event: Any,
    ) -> list[ToolCallStart | ToolCallDelta]:
        events: list[ToolCallStart | ToolCallDelta] = []
        if not self.tool_name:
            self._update_identity(event)
            if self.tool_name:
                events.append(
                    ToolCallStart(tool_name=self.tool_name, tool_id=self.call_id)
                )
        delta = getattr(event, "delta", "") or ""
        self.arguments_json += delta
        events.append(ToolCallDelta(text=delta))
        return events

    def complete(self, event: Any) -> ToolCallComplete:
        if not self.tool_name:
            self._update_identity(event)
        complete = ToolCallComplete(
            tool_id=self.call_id,
            tool_name=self.tool_name,
            arguments=parse_tool_arguments(self.arguments_json),
        )
        self.tool_name = ""
        self.call_id = ""
        self.arguments_json = ""
        return complete


def extract_response_reasoning_summary(response: Any) -> str:
    data = as_dict(response)
    output = data.get("output")
    if not isinstance(output, list):
        output = getattr(response, "output", [])
    parts: list[str] = []
    for item in output or []:
        item_data = as_dict(item)
        if item_data.get("type") != "reasoning":
            continue
        summary = item_data.get("summary") or getattr(item, "summary", [])
        for summary_item in summary or []:
            text = get_text(summary_item, "text")
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def extract_chat_reasoning_delta(delta: Any) -> str:
    text = get_text(
        delta,
        "reasoning_content",
        "reasoning_delta",
        "reasoning",
        "thinking",
    )
    if text:
        return text
    data = as_dict(delta)
    reasoning = data.get("reasoning")
    if isinstance(reasoning, dict):
        for key in ("content", "text", "summary"):
            item = reasoning.get(key)
            if isinstance(item, str) and item:
                return item
    return ""


def token_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def cached_tokens(details: Any) -> int:
    if details is None:
        return 0
    return token_count(getattr(details, "cached_tokens", 0))


def openai_usage_stream_end(
    *,
    total_input_tokens: Any,
    output_tokens: Any,
    cache_details: Any,
) -> StreamEnd:
    # OpenAI includes cached tokens in total input tokens. StreamEnd reports
    # uncached input plus cache_read so the complete prompt size is recoverable.
    cache_read = cached_tokens(cache_details)
    input_tokens = token_count(total_input_tokens)
    return StreamEnd(
        stop_reason="end_turn",
        input_tokens=max(input_tokens - cache_read, 0),
        output_tokens=token_count(output_tokens),
        cache_read=cache_read,
        cache_creation=0,
    )


def stream_end_from_openai_response_usage(usage: Any) -> StreamEnd:
    return openai_usage_stream_end(
        total_input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
        cache_details=getattr(usage, "input_tokens_details", None),
    )


def stream_end_from_openai_chat_usage(usage: Any) -> StreamEnd:
    return openai_usage_stream_end(
        total_input_tokens=getattr(usage, "prompt_tokens", 0),
        output_tokens=getattr(usage, "completion_tokens", 0),
        cache_details=getattr(usage, "prompt_tokens_details", None),
    )
