"""会话与会话管理器。

Session / SessionManager 跟踪 Agent 实例与连接。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from mozilcode.agent import Agent
from mozilcode.conversation import ConversationManager

log = logging.getLogger(__name__)


@dataclass
class Session:
    """A single conversation session backed by an Agent instance."""

    session_id: str
    agent: Agent
    conversation: ConversationManager
    # Pending permission/askuser futures, keyed by request_id (str(id(future)))
    _pending_futures: dict[str, asyncio.Future] = field(default_factory=dict)

    def register_future(self, request_id: str, future: asyncio.Future) -> None:
        self._pending_futures[request_id] = future

    def resolve_future(self, request_id: str, result: Any) -> bool:
        """Resolve a pending permission or askuser future. Returns True if found."""
        future = self._pending_futures.pop(request_id, None)
        if future is None:
            return False
        if not future.done():
            future.set_result(result)
            return True
        return False

    def cancel_pending(self) -> None:
        """Cancel all pending futures (e.g. on session close)."""
        for request_id, future in list(self._pending_futures.items()):
            if not future.done():
                future.cancel()
        self._pending_futures.clear()


class SessionManager:
    """Manages multiple concurrent Agent sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        session_id: str,
        agent: Agent,
        conversation: ConversationManager,
    ) -> Session:
        async with self._lock:
            session = Session(
                session_id=session_id,
                agent=agent,
                conversation=conversation,
            )
            self._sessions[session_id] = session
            log.info("Created session %s", session_id)
            return session

    async def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                session.cancel_pending()
                log.info("Closed session %s", session_id)

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())
