"""会话后台任务列表与取消。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mozilcode.daemon.responses import DaemonActionResult
from mozilcode.daemon.workspace_payloads import task_to_dict

RequireDeps = Callable[[str], Awaitable[tuple[Any | None, DaemonActionResult | None]]]


async def list_session_background_tasks(
    sid: str,
    require_deps: RequireDeps,
) -> DaemonActionResult:
    deps, error = await require_deps(sid)
    if error is not None:
        return error
    assert deps is not None
    return DaemonActionResult(
        {
            "tasks": [
                task_to_dict(task)
                for task in deps.task_manager.list_tasks()
            ]
        }
    )


async def cancel_session_background_task(
    sid: str,
    task_id: str,
    require_deps: RequireDeps,
) -> DaemonActionResult:
    deps, error = await require_deps(sid)
    if error is not None:
        return error
    assert deps is not None
    return DaemonActionResult({"cancelled": deps.task_manager.cancel(task_id)})
