from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.daemon.background_task_actions import (
    cancel_session_background_task,
    list_session_background_tasks,
)
from mozilcode.daemon.responses import DaemonActionResult


class _TaskManager:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def list_tasks(self):
        return [
            SimpleNamespace(
                id="task-1",
                name="lint",
                task="run lint",
                status="running",
                result="",
                start_time=10.0,
                end_time=12.5,
                progress=SimpleNamespace(
                    input_tokens=13,
                    output_tokens=5,
                    tool_call_count=2,
                    last_activity="Bash",
                ),
            )
        ]

    def cancel(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return task_id == "task-1"


@pytest.mark.asyncio
async def test_list_session_background_tasks_serializes_manager_tasks() -> None:
    task_manager = _TaskManager()

    async def require_deps(_sid: str):
        return SimpleNamespace(task_manager=task_manager), None

    result = await list_session_background_tasks("sid", require_deps)

    assert result == DaemonActionResult(
        {
            "tasks": [
                {
                    "id": "task-1",
                    "name": "lint",
                    "task": "run lint",
                    "status": "running",
                    "result": "",
                    "elapsed": 2.5,
                    "input_tokens": 13,
                    "output_tokens": 5,
                    "tool_call_count": 2,
                    "last_activity": "Bash",
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_cancel_session_background_task_delegates_to_manager() -> None:
    task_manager = _TaskManager()

    async def require_deps(_sid: str):
        return SimpleNamespace(task_manager=task_manager), None

    result = await cancel_session_background_task("sid", "task-1", require_deps)

    assert result == DaemonActionResult({"cancelled": True})
    assert task_manager.cancelled == ["task-1"]


@pytest.mark.asyncio
async def test_background_task_actions_return_dependency_error() -> None:
    error = DaemonActionResult({"error": "session not found"}, status_code=404)

    async def require_deps(_sid: str):
        return None, error

    listed = await list_session_background_tasks("missing", require_deps)
    cancelled = await cancel_session_background_task(
        "missing",
        "task-1",
        require_deps,
    )

    assert listed == error
    assert cancelled == error
