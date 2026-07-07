from __future__ import annotations

from typing import Any


class PendingPromptRegistry:
    """Track unresolved permission and ask-user prompt events by session."""

    def __init__(self) -> None:
        self._events: dict[str, dict[str, dict[str, Any]]] = {}

    def record(self, sid: str, request_id: str, event: dict[str, Any]) -> None:
        if not request_id:
            return
        self._events.setdefault(sid, {})[request_id] = event

    def events(self, sid: str) -> list[dict[str, Any]]:
        return list(self._events.get(sid, {}).values())

    def discard(self, sid: str, request_id: str) -> bool:
        events = self._events.get(sid)
        if events is None:
            return False
        removed = events.pop(request_id, None) is not None
        if not events:
            self._events.pop(sid, None)
        return removed

    def discard_session(self, sid: str) -> None:
        self._events.pop(sid, None)

    def __contains__(self, sid: str) -> bool:
        return sid in self._events
