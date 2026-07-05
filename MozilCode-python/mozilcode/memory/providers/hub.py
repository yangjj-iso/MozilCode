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
    name: str
    kind: str
    version: str
    enabled: bool = True
    last_error: str = ""


@dataclass
class MemoryHub:
    providers: list[MemoryProvider] = field(default_factory=list)
    load_timeout: float = 3.0
    observe_timeout: float = 10.0
    _errors: dict[str, str] = field(default_factory=dict)
    _initialized: bool = False

    async def initialize(self) -> None:
        for provider in self.providers:
            await self._run_provider(provider, "initialize", timeout=self.observe_timeout)
        self._initialized = True

    async def load_context(self, query: str, scope: MemoryScope) -> str:
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
        await self._ensure_initialized()
        for provider in self.providers:
            await self._run_provider(
                provider,
                "observe",
                event,
                timeout=self.observe_timeout,
            )

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
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
        await self._ensure_initialized()
        for provider in self.providers:
            await self._run_provider(
                provider,
                "write",
                item,
                timeout=self.observe_timeout,
            )

    async def clear(self, scope: MemoryScope | None = None) -> None:
        await self._ensure_initialized()
        for provider in self.providers:
            await self._run_provider(
                provider,
                "clear",
                scope,
                timeout=self.observe_timeout,
            )

    async def shutdown(self) -> None:
        for provider in self.providers:
            await self._run_provider(provider, "shutdown", timeout=self.observe_timeout)

    def status(self) -> dict[str, Any]:
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
