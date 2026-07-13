from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

from mozilcode.memory.providers.base import (
    MemoryEvent,
    MemoryItem,
    MemoryProvider,
    MemoryScope,
)

log = logging.getLogger(__name__)


@dataclass
class MemoryProviderStatus:
    """Provider 状态信息（用于 status() 报告）。"""
    name: str
    kind: str
    version: str
    enabled: bool = True
    last_error: str = ""


@dataclass
class MemoryHub:
    """记忆中心：管理多个 Provider，提供统一的记忆操作接口。

    核心职责：
    1. 初始化所有 Provider（initialize）
    2. 加载记忆上下文（load_context）：汇总所有 Provider 的返回
    3. 观察事件（observe）：将事件分发给所有 Provider
    4. 搜索记忆（search）：跨 Provider 搜索，合并结果
    5. 写入 / 清除记忆

    错误隔离：单个 Provider 失败不会影响其他 Provider，错误记录在 _errors 中。
    超时保护：load_timeout=3s / observe_timeout=10s，防止 Provider 卡死。
    """
    providers: list[MemoryProvider] = field(default_factory=list)
    load_timeout: float = 3.0    # 加载上下文的超时时间
    observe_timeout: float = 10.0 # 观察事件的超时时间
    _errors: dict[str, str] = field(default_factory=dict)  # Provider 错误记录
    _initialized: bool = False

    async def initialize(self) -> None:
        """初始化所有 Provider。"""
        for provider in self.providers:
            await self._run_provider(provider, "initialize", timeout=self.observe_timeout)
        self._initialized = True

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        """从所有 Provider 加载记忆上下文，汇总拼接返回。
        每个 Provider 的返回以 ## Provider名 为标题分节。"""
        await self._ensure_initialized()
        parts: list[str] = []
        for provider in self.providers:
            result = await self._run_provider(
                provider,
                "load_context",
                query,
                scope,
                timeout=self.load_timeout,
            )
            if isinstance(result, str) and result.strip():
                name = getattr(provider, "name", provider.__class__.__name__)
                parts.append(f"## {name}\n{result.strip()}")
        return "\n\n".join(parts)

    async def observe(self, event: MemoryEvent) -> None:
        """将记忆事件分发给所有 Provider 的 observe 方法。"""
        await self._ensure_initialized()
        for provider in self.providers:
            await self._run_provider(
                provider,
                "observe",
                event,
                timeout=self.observe_timeout,
            )

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """跨所有 Provider 搜索记忆，合并结果，最多返回 limit 条。"""
        await self._ensure_initialized()
        items: list[MemoryItem] = []
        for provider in self.providers:
            result = await self._run_provider(
                provider,
                "search",
                query,
                limit,
                timeout=self.load_timeout,
            )
            if isinstance(result, list):
                items.extend(item for item in result if isinstance(item, MemoryItem))
            if len(items) >= limit:
                return items[:limit]
        return items

    async def write(self, item: MemoryItem) -> None:
        """向所有 Provider 写入一条记忆。"""
        await self._ensure_initialized()
        for provider in self.providers:
            await self._run_provider(
                provider,
                "write",
                item,
                timeout=self.observe_timeout,
            )

    async def clear(self, scope: MemoryScope | None = None) -> None:
        """清除所有 Provider 的记忆（可指定作用域）。"""
        await self._ensure_initialized()
        for provider in self.providers:
            await self._run_provider(
                provider,
                "clear",
                scope,
                timeout=self.observe_timeout,
            )

    async def shutdown(self) -> None:
        """关闭所有 Provider（释放资源）。"""
        for provider in self.providers:
            await self._run_provider(provider, "shutdown", timeout=self.observe_timeout)

    def status(self) -> dict[str, Any]:
        """返回记忆系统状态（是否启用 + 各 Provider 信息）。"""
        return {
            "enabled": bool(self.providers),
            "providers": [
                {
                    "name": getattr(provider, "name", provider.__class__.__name__),
                    "kind": getattr(provider, "kind", provider.__class__.__name__),
                    "version": getattr(provider, "version", ""),
                    "enabled": True,
                    "last_error": self._errors.get(self._provider_key(provider), ""),
                }
                for provider in self.providers
            ],
        }

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    async def _run_provider(
        self,
        provider: MemoryProvider,
        method_name: str,
        *args: Any,
        timeout: float,
    ) -> Any:
        """安全调用 Provider 方法：带超时保护和错误隔离。

        - 支持同步和异步方法（inspect.isawaitable 检测）
        - 异步方法用 asyncio.wait_for 加超时
        - 任何异常被捕获并记录，返回 None（不影响其他 Provider）
        """
        key = self._provider_key(provider)
        try:
            method = getattr(provider, method_name)
            result = method(*args)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=timeout)
            self._errors.pop(key, None)
            return result
        except Exception as e:
            self._errors[key] = f"{type(e).__name__}: {e}".strip()
            log.debug("Memory provider %s.%s failed: %s", key, method_name, e)
            return None

    @staticmethod
    def _provider_key(provider: MemoryProvider) -> str:
        return getattr(provider, "name", provider.__class__.__name__)
