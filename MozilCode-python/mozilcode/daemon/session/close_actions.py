from __future__ import annotations

import asyncio
from collections.abc import Callable, MutableMapping
from typing import Any

from mozilcode.daemon.tasks.active import ActiveTaskRegistry
from mozilcode.daemon.tasks.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session.store import validate_session_id
from mozilcode.permissions import PermissionMode

ValidateSessionId = Callable[[str], str]


async def close_daemon_session(
    sid: str,
    *,
    active_tasks: ActiveTaskRegistry,
    session_mgr: SessionManager,
    runtimes: MutableMapping[str, Any],
    records: Any,
    pre_plan_modes: MutableMapping[str, PermissionMode],
    pending_prompts: PendingPromptRegistry,
    validate_sid: ValidateSessionId = validate_session_id,
) -> None:
    """Close a daemon session and clear all runtime-only state."""
    validate_sid(sid)

    task = active_tasks.pop_task(sid)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await session_mgr.close_session(sid)
    runtime = runtimes.pop(sid, None)
    hub = getattr(runtime.agent, "memory_hub", None) if runtime is not None else None
    if hub is not None:
        await hub.shutdown()

    records.close(sid)
    pre_plan_modes.pop(sid, None)
    pending_prompts.discard_session(sid)
