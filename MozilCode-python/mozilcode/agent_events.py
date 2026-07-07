from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mozilcode.context import CompactBoundary


@dataclass
class StreamText:
    text: str


@dataclass
class ThinkingText:
    text: str


@dataclass
class RetryEvent:
    reason: str
    wait: float = 0.0


@dataclass
class ToolUseEvent:
    tool_name: str
    tool_id: str
    arguments: dict[str, Any]


@dataclass
class ToolResultEvent:
    tool_id: str
    tool_name: str
    output: str
    is_error: bool
    elapsed: float


@dataclass
class TurnComplete:
    turn: int


@dataclass
class LoopComplete:
    total_turns: int


@dataclass
class UsageEvent:
    input_tokens: int
    output_tokens: int
    context_tokens: int = 0


@dataclass
class ErrorEvent:
    message: str


@dataclass
class CompactNotification:
    before_tokens: int
    message: str
    after_tokens: int = 0
    boundary: CompactBoundary | None = None


@dataclass
class CompactStarted:
    current_tokens: int
    threshold: int
    context_window: int
    message: str = "正在自动压缩上下文"


@dataclass
class HookEvent:
    hook_id: str
    event: str
    output: str
    success: bool


class PermissionResponse(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"


@dataclass
class PermissionRequest:
    tool_name: str
    description: str
    future: asyncio.Future[PermissionResponse]


@dataclass
class AskUserRequest:
    """Yielded when AskUserQuestion tool needs user input."""

    questions: list[dict[str, Any]]
    future: asyncio.Future[dict[str, str]]


AgentEvent = (
    StreamText
    | ThinkingText
    | RetryEvent
    | ToolUseEvent
    | ToolResultEvent
    | TurnComplete
    | LoopComplete
    | UsageEvent
    | ErrorEvent
    | PermissionRequest
    | AskUserRequest
    | CompactNotification
    | CompactStarted
    | HookEvent
)


__all__ = [
    "AgentEvent",
    "AskUserRequest",
    "CompactNotification",
    "CompactStarted",
    "ErrorEvent",
    "HookEvent",
    "LoopComplete",
    "PermissionRequest",
    "PermissionResponse",
    "RetryEvent",
    "StreamText",
    "ThinkingText",
    "ToolResultEvent",
    "ToolUseEvent",
    "TurnComplete",
    "UsageEvent",
]
