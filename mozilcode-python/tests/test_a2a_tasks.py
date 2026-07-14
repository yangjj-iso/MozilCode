"""A2A 任务状态、事件刷新与 payload 序列化测试。"""

from __future__ import annotations

from mozilcode.a2a.tasks import (
    A2ATask,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_WORKING,
    refresh_task_from_log,
    task_to_a2a_payload,
)


def _task(**overrides) -> A2ATask:
    values = {
        "id": "task-1",
        "context_id": "ctx-1",
        "session_id": "session-1",
        "internal_task_id": "internal-1",
        "prompt": "hello",
        "state": TASK_WORKING,
    }
    values.update(overrides)
    return A2ATask(**values)


def test_refresh_task_from_log_applies_only_new_matching_events() -> None:
    task = _task(cursor=1)
    log = [
        {"type": "StreamText", "task_id": "internal-1", "data": {"text": "old"}},
        {"type": "StreamText", "task_id": "other", "data": {"text": "ignored"}},
        {"type": "StreamText", "task_id": "internal-1", "data": {"text": "ok"}},
        {"type": "LoopComplete", "task_id": "internal-1", "data": {}},
    ]

    refresh_task_from_log(task, log)

    assert task.output == "ok"
    assert task.state == TASK_COMPLETED
    assert task.cursor == len(log)


def test_refresh_task_from_log_clamps_oversized_cursor() -> None:
    task = _task(cursor=10)

    refresh_task_from_log(task, [{"type": "StreamText", "data": {"text": "late"}}])

    assert task.cursor == 1
    assert task.output == ""
    assert task.state == TASK_WORKING


def test_refresh_task_from_log_marks_missing_session_failed() -> None:
    task = _task()

    refresh_task_from_log(task, None)

    assert task.state == TASK_FAILED
    assert task.error == "Session disappeared."


def test_task_to_a2a_payload_uses_internal_metadata_last() -> None:
    task = _task(
        source="unit",
        metadata={
            "source": "external",
            "session_id": "fake",
            "internal_task_id": "fake",
            "ticket": "T-1",
        },
    )
    task.output_parts.append("answer")

    payload = task_to_a2a_payload(task)

    assert payload["artifacts"][0]["parts"][0]["text"] == "answer"
    assert payload["metadata"]["source"] == "unit"
    assert payload["metadata"]["session_id"] == "session-1"
    assert payload["metadata"]["internal_task_id"] == "internal-1"
    assert payload["metadata"]["ticket"] == "T-1"
