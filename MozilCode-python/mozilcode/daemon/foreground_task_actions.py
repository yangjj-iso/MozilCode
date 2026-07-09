from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from mozilcode.daemon.active_tasks import ActiveTaskRegistry
from mozilcode.daemon.session.runtime_requirements import SessionRuntimeRequirements

GetEventLog = Callable[[str], list[dict | None] | None]


class ForegroundTaskRunner(Protocol):
    def start(
        self,
        sid: str,
        prompt: str,
        agent: Any,
        conversation: Any,
    ) -> str:
        ...


async def start_session_task(
    *,
    sid: str,
    prompt: str,
    active_tasks: ActiveTaskRegistry,
    runtime_requirements: SessionRuntimeRequirements,
    get_event_log: GetEventLog,
    task_runner: ForegroundTaskRunner,
) -> str:
    """Validate and start one foreground agent task for a daemon session."""
    active_tasks.ensure_available(sid)
    runtime = await runtime_requirements.ensure_runtime(sid)
    if runtime is None or get_event_log(sid) is None:
        raise ValueError(f"Session {sid} not found")

    return task_runner.start(
        sid,
        prompt,
        runtime.agent,
        runtime.conversation,
    )
