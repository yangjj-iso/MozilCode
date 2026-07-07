from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mozilcode.conversation import ConversationManager
from mozilcode.memory.providers import (
    MEMORY_EVENT_TURN_COMMITTED,
    MemoryEvent,
    MemoryHub,
    MemoryScope,
)

log = logging.getLogger(__name__)


@dataclass
class AgentMemoryBridge:
    """Adapter between the Agent loop and pluggable memory providers."""

    memory_hub: MemoryHub | None
    client: Any
    protocol: str
    project_root: str
    source: str = "agent"
    _extracting: bool = False

    @property
    def enabled(self) -> bool:
        return self.memory_hub is not None

    async def load_context(self, query: str = "", session_id: str = "") -> str:
        if not self.memory_hub:
            return ""
        scope = MemoryScope(
            query=query,
            session_id=session_id,
            project_root=self.project_root,
            source=self.source,
        )
        return await self.memory_hub.load_context(query, scope)

    async def observe(
        self,
        conversation: ConversationManager,
        event_type: str,
        *,
        session_id: str,
        agent_id: str,
        query: str,
    ) -> None:
        if not self.memory_hub:
            return
        try:
            await self.memory_hub.observe(
                MemoryEvent(
                    type=event_type,
                    source=self.source,
                    session_id=session_id,
                    query=query,
                    conversation=conversation,
                    client=self.client,
                    protocol=self.protocol,
                    metadata={"agent_id": agent_id},
                )
            )
        except Exception as e:
            log.debug("Memory observe failed for %s: %s", event_type, e)

    async def extract_memories(
        self,
        conversation: ConversationManager,
        *,
        session_id: str,
        agent_id: str,
        query: str,
    ) -> None:
        if self._extracting or not self.memory_hub:
            return
        self._extracting = True
        try:
            await self.observe(
                conversation,
                MEMORY_EVENT_TURN_COMMITTED,
                session_id=session_id,
                agent_id=agent_id,
                query=query,
            )
        except Exception as e:
            log.debug("Memory extraction failed: %s", e)
        finally:
            self._extracting = False
