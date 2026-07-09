from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from mozilcode.daemon.serialize import serialize_event

PENDING_PROMPT_EVENT_TYPES = {"PermissionRequest", "AskUserRequest"}


@dataclass(frozen=True)
class SerializedTaskEvent:
    message: dict[str, Any]
    future: asyncio.Future | None = None
    request_id: str = ""
    pending_request_id: str = ""


def user_message_event(task_id: str, content: str) -> dict[str, Any]:
    return {"type": "UserMessage", "task_id": task_id, "data": {"content": content}}


def loop_complete_event(task_id: str) -> dict[str, Any]:
    return {"type": "LoopComplete", "task_id": task_id, "data": {}}


def task_cancelled_event(task_id: str) -> dict[str, Any]:
    return {
        "type": "TaskCancelled",
        "task_id": task_id,
        "data": {"message": "Task cancelled"},
    }


def task_error_event(task_id: str, message: str) -> dict[str, Any]:
    return {"type": "ErrorEvent", "task_id": task_id, "data": {"message": message}}


def pending_prompt_request_id(message: dict[str, Any]) -> str:
    if message.get("type") not in PENDING_PROMPT_EVENT_TYPES:
        return ""
    data = message.get("data") or {}
    if not isinstance(data, dict):
        return ""
    return str(data.get("request_id") or "")


def serialize_task_event(event: Any, task_id: str) -> SerializedTaskEvent:
    future = _event_future(event)
    request_id = str(id(future)) if future is not None else ""
    message = serialize_event(event, task_id=task_id)
    return SerializedTaskEvent(
        message=message,
        future=future,
        request_id=request_id,
        pending_request_id=pending_prompt_request_id(message),
    )


def _event_future(event: Any) -> asyncio.Future | None:
    future = getattr(event, "future", None)
    return future if isinstance(future, asyncio.Future) else None
