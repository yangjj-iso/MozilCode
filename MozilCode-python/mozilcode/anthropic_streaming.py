"""Helpers for translating Anthropic streaming payloads into MozilCode events."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from mozilcode.tools.base import (
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
)


def parse_tool_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@dataclass
class AnthropicStreamState:
    tool_name: str = ""
    tool_id: str = ""
    arguments_json: str = ""
    in_thinking: bool = False
    thinking: str = ""
    thinking_signature: str = ""

    def start_block(self, block: Any) -> ToolCallStart | None:
        block_type = getattr(block, "type", "")
        if block_type == "thinking":
            self.in_thinking = True
            self.thinking = ""
            self.thinking_signature = ""
            return None
        if block_type == "tool_use":
            self.tool_name = getattr(block, "name", "") or ""
            self.tool_id = getattr(block, "id", "") or ""
            self.arguments_json = ""
            return ToolCallStart(tool_name=self.tool_name, tool_id=self.tool_id)
        return None

    def add_delta(self, delta: Any) -> list[ThinkingDelta | ToolCallDelta]:
        delta_type = getattr(delta, "type", "")
        if delta_type == "thinking_delta":
            text = getattr(delta, "thinking", "") or ""
            self.thinking += text
            return [ThinkingDelta(text=text)]
        if delta_type == "signature_delta":
            self.thinking_signature = getattr(delta, "signature", "") or ""
            return []
        if delta_type == "input_json_delta":
            text = getattr(delta, "partial_json", "") or ""
            self.arguments_json += text
            return [ToolCallDelta(text=text)]
        return []

    def stop_block(self) -> list[ThinkingComplete | ToolCallComplete]:
        events: list[ThinkingComplete | ToolCallComplete] = []
        if self.in_thinking:
            events.append(
                ThinkingComplete(
                    thinking=self.thinking,
                    signature=self.thinking_signature,
                )
            )
            self.in_thinking = False
            self.thinking = ""
            self.thinking_signature = ""
        if self.tool_name:
            events.append(
                ToolCallComplete(
                    tool_id=self.tool_id,
                    tool_name=self.tool_name,
                    arguments=parse_tool_arguments(self.arguments_json),
                )
            )
            self.tool_name = ""
            self.tool_id = ""
            self.arguments_json = ""
        return events
