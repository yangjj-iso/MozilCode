"""每会话仅允许一个前台任务的注册表。"""

from __future__ import annotations

import asyncio


ACTIVE_TASK_RUNNING_ERROR = "task already running"


class ActiveTaskRegistry:
    """Track the one foreground daemon task allowed per session."""

    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task] = {}
        self.task_ids: dict[str, str] = {}

    def ensure_available(self, sid: str) -> None:
        task = self.tasks.get(sid)
        if task is None:
            return
        if not task.done():
            raise ValueError(ACTIVE_TASK_RUNNING_ERROR)
        self.discard(sid)

    def register(self, sid: str, task_id: str, task: asyncio.Task) -> None:
        self.tasks[sid] = task
        self.task_ids[sid] = task_id

    def discard(self, sid: str) -> None:
        self.tasks.pop(sid, None)
        self.task_ids.pop(sid, None)

    def pop_task(self, sid: str) -> asyncio.Task | None:
        task = self.tasks.pop(sid, None)
        self.task_ids.pop(sid, None)
        return task

    def clear_if_current(self, sid: str, task: asyncio.Task | None) -> None:
        if task is not None and self.tasks.get(sid) is task:
            self.discard(sid)

    def cancel(self, sid: str) -> bool:
        task = self.tasks.get(sid)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def is_running(self, sid: str) -> bool:
        task = self.tasks.get(sid)
        return bool(task and not task.done())

    def task_id(self, sid: str) -> str:
        return self.task_ids.get(sid, "")
