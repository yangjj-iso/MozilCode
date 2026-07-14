"""Agent 记忆适配器。

定义了 AgentMemoryBridge 类，作为 Agent 循环与 MemoryHub 之间的适配层。
职责：
- load_context(): 加载记忆上下文（会话开始时注入对话）
- observe(): 观察对话事件（如 turn_completed，轻量级）
- extract_memories(): 触发记忆提取（turn_committed，重量级，用 LLM 提取）

通过 _extracting 标记防止重入。
"""

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
    """Agent 循环与 MemoryHub 之间的适配器。

    职责：
    1. load_context(): 加载记忆上下文（会话开始时注入对话）
    2. observe(): 观察对话事件（如 turn_completed，轻量级）
    3. extract_memories(): 触发记忆提取（turn_committed，重量级，用 LLM 提取）

    通过 _extracting 标记防止重入（提取过程中不会再次触发提取）。
    """

    memory_hub: MemoryHub | None  # 记忆中心（None 表示未启用记忆）
    client: Any                   # LLM 客户端（提取记忆时使用）
    protocol: str                 # LLM 协议名
    project_root: str
    source: str = "agent"         # 来源标识
    _extracting: bool = False     # 防重入标记

    @property
    def enabled(self) -> bool:
        return self.memory_hub is not None

    async def load_context(self, query: str = "", session_id: str = "") -> str:
        """加载记忆上下文。如果未启用记忆，返回空字符串。"""
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
        """观察对话事件，分发给 MemoryHub 的所有 Provider。
        失败时静默处理（只记录 debug 日志），不阻断 Agent 循环。
        """
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
        """触发记忆提取（turn_committed 事件）。

        通过 _extracting 标记防止重入：如果上一次提取还在进行中，直接返回。
        提取失败时静默处理，不阻断 Agent 循环。
        """
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
