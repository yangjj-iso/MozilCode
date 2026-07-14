"""Daemon 任务事件序列化测试。"""

from __future__ import annotations

import asyncio

from mozilcode.agent import AskUserRequest, PermissionRequest, StreamText
from mozilcode.daemon.tasks.events import (
    loop_complete_event,
    pending_prompt_request_id,
    serialize_task_event,
    task_cancelled_event,
    task_error_event,
    user_message_event,
)


def _future() -> tuple[asyncio.AbstractEventLoop, asyncio.Future]:
    loop = asyncio.new_event_loop()
    return loop, loop.create_future()


def test_static_task_events_include_task_id_and_data() -> None:
    assert user_message_event("task-1", "hello") == {
        "type": "UserMessage",
        "task_id": "task-1",
        "data": {"content": "hello"},
    }
    assert loop_complete_event("task-1") == {
        "type": "LoopComplete",
        "task_id": "task-1",
        "data": {},
    }
    assert task_cancelled_event("task-1") == {
        "type": "TaskCancelled",
        "task_id": "task-1",
        "data": {"message": "Task cancelled"},
    }
    assert task_error_event("task-1", "boom") == {
        "type": "ErrorEvent",
        "task_id": "task-1",
        "data": {"message": "boom"},
    }


def test_serialize_task_event_marks_permission_request_pending() -> None:
    loop, future = _future()
    try:
        event = PermissionRequest(
            tool_name="WriteFile",
            description="write file",
            future=future,
        )

        payload = serialize_task_event(event, "task-2")

        assert payload.future is future
        assert payload.request_id == str(id(future))
        assert payload.pending_request_id == str(id(future))
        assert payload.message == {
            "type": "PermissionRequest",
            "task_id": "task-2",
            "data": {
                "tool_name": "WriteFile",
                "description": "write file",
                "request_id": str(id(future)),
                "resolved": False,
            },
        }
    finally:
        loop.close()


def test_serialize_task_event_marks_askuser_request_pending() -> None:
    loop, future = _future()
    try:
        event = AskUserRequest(
            questions=[
                {"name": "language", "message": "Language?", "options": ["Python"]}
            ],
            future=future,
        )

        payload = serialize_task_event(event, "task-3")

        assert payload.future is future
        assert payload.pending_request_id == str(id(future))
        assert payload.message["type"] == "AskUserRequest"
        assert payload.message["data"]["request_id"] == str(id(future))
        assert payload.message["data"]["questions"][0]["name"] == "language"
    finally:
        loop.close()


def test_serialize_task_event_leaves_plain_events_non_pending() -> None:
    payload = serialize_task_event(StreamText("hello"), "task-4")

    assert payload.future is None
    assert payload.request_id == ""
    assert payload.pending_request_id == ""
    assert payload.message == {
        "type": "StreamText",
        "task_id": "task-4",
        "data": {"text": "hello"},
    }


def test_pending_prompt_request_id_ignores_non_prompt_events() -> None:
    assert pending_prompt_request_id({"type": "StreamText", "data": {}}) == ""
    assert pending_prompt_request_id({"type": "PermissionRequest", "data": {}}) == ""
    assert (
        pending_prompt_request_id(
            {"type": "AskUserRequest", "data": {"request_id": "req-1"}}
        )
        == "req-1"
    )
