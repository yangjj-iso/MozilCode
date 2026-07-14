"""AgentEvent → WebSocket JSON 序列化。

Future 字段替换为 request_id，供权限/提问回传。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from typing import Any

from mozilcode.agent.events import (
    AskUserRequest,
    CompactNotification,
    CompactStarted,
    ErrorEvent,
    HookEvent,
    LoopComplete,
    PermissionRequest,
    RetryEvent,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    UsageEvent,
)

# Events that carry an asyncio.Future cannot be serialized directly.
# We strip the future and replace it with a request_id that the client
# uses to resolve the permission via a separate HTTP endpoint.
_FUTURE_FIELDS = {"future"}


def serialize_event(event: Any, task_id: str = "") -> dict[str, Any]:
    """Convert an AgentEvent dataclass into a JSON-serializable dict.

    For PermissionRequest, the asyncio.Future is stripped and replaced
    with a ``request_id`` (the id() of the future object). The client
    must POST the resolution back to ``/api/permission/{request_id}``.
    """
    if not is_dataclass(event):
        return {"type": "unknown", "data": str(event)}

    type_name = type(event).__name__
    data: dict[str, Any] = {}

    for field_name in event.__dataclass_fields__:
        value = getattr(event, field_name)

        if field_name in _FUTURE_FIELDS and isinstance(value, asyncio.Future):
            # Replace future with a stable request_id
            data["request_id"] = str(id(value))
            data["resolved"] = value.done()
            continue

        # CompactBoundary is a dataclass too — let asdict handle it
        if is_dataclass(value) and not isinstance(value, type):
            data[field_name] = asdict(value)
        else:
            data[field_name] = value

    return {"type": type_name, "task_id": task_id, "data": data}
