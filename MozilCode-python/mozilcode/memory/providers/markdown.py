from __future__ import annotations

from typing import Any

from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.providers.base import BaseMemoryProvider, MemoryEvent, MemoryScope


class MarkdownMemoryProvider(BaseMemoryProvider):
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
        return self.manager.load()

    async def observe(self, event: MemoryEvent) -> None:
        if event.type != "turn_committed":
            return
        if event.client is None or event.conversation is None or not event.protocol:
            return
        await self.manager.extract(event.client, event.conversation, event.protocol)

    async def clear(self, scope: MemoryScope | None = None) -> None:
        self.manager.clear()
