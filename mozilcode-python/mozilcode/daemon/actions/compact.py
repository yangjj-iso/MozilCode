"""Daemon 侧手动上下文压缩动作。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mozilcode.agent.events import CompactStarted, ErrorEvent, UsageEvent
from mozilcode.context import compute_compact_threshold
from mozilcode.daemon.responses import DaemonActionResult
from mozilcode.daemon.serialize import serialize_event

EmitEvent = Callable[[str, dict | None], None]
PersistEvents = Callable[[str], None]
StatusProvider = Callable[[str], dict]


async def run_manual_compact(
    *,
    sid: str,
    agent: Any,
    conversation: Any,
    emit_event: EmitEvent,
    persist_events: PersistEvents,
    status_provider: StatusProvider,
) -> DaemonActionResult:
    """Run manual context compaction and persist the resulting event stream."""
    before_tokens = conversation.current_tokens()
    emit_event(
        sid,
        serialize_event(
            CompactStarted(
                current_tokens=before_tokens,
                threshold=max(
                    0,
                    compute_compact_threshold(
                        agent.context_window,
                        manual=True,
                    ),
                ),
                context_window=agent.context_window,
                message="正在压缩上下文",
            )
        ),
    )

    result = await agent.manual_compact(conversation)
    event = serialize_event(result)
    emit_event(sid, event)
    if not isinstance(result, ErrorEvent):
        emit_event(
            sid,
            serialize_event(
                UsageEvent(
                    input_tokens=agent.total_input_tokens,
                    output_tokens=agent.total_output_tokens,
                    context_tokens=conversation.current_tokens(),
                )
            ),
        )
    persist_events(sid)

    if isinstance(result, ErrorEvent):
        return DaemonActionResult(
            {"error": result.message},
            status_code=400,
        )
    return DaemonActionResult(
        {
            "type": type(result).__name__,
            "data": event.get("data", {}),
            "status": status_provider(sid),
        }
    )
