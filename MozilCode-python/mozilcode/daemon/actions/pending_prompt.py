from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mozilcode.daemon.tasks.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.session import SessionManager

EmitEvent = Callable[[str, dict[str, Any] | None], None]


async def resolve_session_pending_prompt(
    sid: str,
    request_id: str,
    result: object,
    resolved_event_type: str,
    *,
    session_mgr: SessionManager,
    pending_prompts: PendingPromptRegistry,
    emit_event: EmitEvent,
) -> bool:
    session = await session_mgr.get_session(sid)
    if session is None:
        return False

    ok = session.resolve_future(request_id, result)
    if not ok:
        return False

    pending_prompts.discard(sid, request_id)
    emit_event(
        sid,
        {
            "type": resolved_event_type,
            "data": {"request_id": request_id},
        },
    )
    return True
