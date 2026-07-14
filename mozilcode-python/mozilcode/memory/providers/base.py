"""记忆 Provider 协议与基类。

定义了可插拔记忆后端的接口协议（MemoryProvider）和默认空实现基类
（BaseMemoryProvider）。

数据结构：
- MemoryScope: 记忆操作的上下文范围（查询 / 会话 / 用户 / 项目根目录）
- MemoryEvent: Agent 循环中发生的事件（turn_completed / turn_committed / session_end）
- MemoryItem: 单条记忆项

自定义 Provider 继承 BaseMemoryProvider 后，只需实现需要的方法。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

MEMORY_EVENT_TURN_COMPLETED = "turn_completed"
MEMORY_EVENT_TURN_COMMITTED = "turn_committed"
MEMORY_EVENT_SESSION_END = "session_end"


@dataclass
class MemoryScope:
    """记忆操作的上下文范围信息（查询内容 / 会话 / 用户 / 项目根目录等）。"""
    query: str = ""
    session_id: str = ""
    user_id: str = ""
    project_root: str = ""
    source: str = ""  # 来源标识（如 "agent"）
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryEvent:
    """记忆事件：Agent 循环中发生的事件（如轮次完成 / 轮次提交 / 会话结束），
    传递给 Provider 的 observe() 方法进行观察处理。"""
    type: str       # 事件类型（对应上面的 3 个常量）
    source: str = ""
    session_id: str = ""
    query: str = ""
    conversation: Any = None  # ConversationManager 引用
    client: Any = None         # LLM 客户端引用（提取记忆时需要）
    protocol: str = ""         # LLM 协议名
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryItem:
    """单条记忆项（内容 + 作用域 + 元数据）。"""
    content: str
    scope: str = "project"  # 作用域："user" / "project"
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryProvider(Protocol):
    """记忆 Provider 协议：定义可插拔记忆后端的接口。

    所有方法都是 async 的，Hub 会通过 asyncio.wait_for 加超时保护。
    内置实现：MarkdownMemoryProvider。可扩展为向量数据库等后端。
    """
    name: str      # Provider 名称
    kind: str       # Provider 类型标识
    version: str   # 版本号

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
    """Provider 基类：所有方法默认空实现，子类按需覆盖。

    自定义 Provider 继承此类后，只需实现需要的方法（如 load_context / observe），
    其余方法保持空实现即可。
    """
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
