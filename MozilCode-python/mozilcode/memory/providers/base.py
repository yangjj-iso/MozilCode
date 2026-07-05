from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

MEMORY_EVENT_TURN_COMPLETED = "turn_completed"
MEMORY_EVENT_TURN_COMMITTED = "turn_committed"
MEMORY_EVENT_SESSION_END = "session_end"


@dataclass
class MemoryScope:
    query: str = ""
    session_id: str = ""
    user_id: str = ""
    project_root: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryEvent:
    type: str
    source: str = ""
    session_id: str = ""
    query: str = ""
    conversation: Any = None
    client: Any = None
    protocol: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryItem:
    content: str
    scope: str = "project"
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryProvider(Protocol):
    name: str
    kind: str
    version: str

    async def initialize(self) -> None:
        ...

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        ...

    async def observe(self, event: MemoryEvent) -> None:
        ...

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        ...

    async def write(self, item: MemoryItem) -> None:
        ...

    async def clear(self, scope: MemoryScope | None = None) -> None:
        ...

    async def shutdown(self) -> None:
        ...


class BaseMemoryProvider:
    name = "base"
    kind = "base"
    version = "1.0"

    async def initialize(self) -> None:
        return None

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        return ""

    async def observe(self, event: MemoryEvent) -> None:
        return None

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        return []

    async def write(self, item: MemoryItem) -> None:
        return None

    async def clear(self, scope: MemoryScope | None = None) -> None:
        return None

    async def shutdown(self) -> None:
        return None
