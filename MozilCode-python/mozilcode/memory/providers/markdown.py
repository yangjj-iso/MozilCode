from __future__ import annotations

from typing import Any

from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.providers.base import (
    MEMORY_EVENT_TURN_COMMITTED,
    BaseMemoryProvider,
    MemoryEvent,
    MemoryScope,
)


class MarkdownMemoryProvider(BaseMemoryProvider):
    """内置记忆 Provider：基于 memories.md 文件存储记忆。

    实现 MemoryProvider 协议的 3 个核心方法：
    - load_context: 加载 memories.md 内容
    - observe: 只处理 turn_committed 事件（触发 LLM 提取记忆）
    - clear: 清空 memories.md
    """
    name = "markdown"
    kind = "builtin.markdown"
    version = "1.0"

    def __init__(
        self,
        project_root: str,
        config: dict[str, Any] | None = None,
        manager: MemoryManager | None = None,
    ) -> None:
        self.config = config or {}
        self.manager = manager or MemoryManager(project_root)

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        """加载 memories.md 内容（用户级 + 项目级拼接）。"""
        return self.manager.load()

    async def observe(self, event: MemoryEvent) -> None:
        """观察记忆事件。只处理 turn_committed（轮次提交），触发 LLM 提取记忆。
        其他事件忽略。"""
        if event.type != MEMORY_EVENT_TURN_COMMITTED:
            return
        if event.client is None or event.conversation is None or not event.protocol:
            return
        await self.manager.extract(event.client, event.conversation, event.protocol)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        """清空 memories.md 文件。"""
        self.manager.clear()
