from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mozilcode.tools.base import Tool

if TYPE_CHECKING:
    from mozilcode.cache import FileCache


class ToolRegistryError(ValueError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set()
        self._discovered: set[str] = set()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolRegistryError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


    def is_enabled(self, name: str) -> bool:
        return name in self._tools and name not in self._disabled

    def enable(self, name: str) -> None:
        self._disabled.discard(name)


    def disable(self, name: str) -> None:
        if name in self._tools:
            self._disabled.add(name)

    def enable_all(self) -> None:
        self._disabled.clear()


    def mark_discovered(self, name: str) -> None:
        self._discovered.add(name)

    def is_discovered(self, name: str) -> bool:
        return name in self._discovered

    @staticmethod
    def _is_deferred(tool: Tool) -> bool:
        return bool(getattr(tool, "should_defer", False))

    def get_deferred_tool_names(self) -> list[str]:
        return [
            name
            for name, tool in self._tools.items()
            if self._is_deferred(tool)
            and name not in self._discovered
            and name not in self._disabled
        ]

    def _is_deferred_searchable(self, name: str, tool: Tool) -> bool:
        return self._is_deferred(tool) and name not in self._disabled

    @staticmethod
    def _schema_for_protocol(tool: Tool, protocol: str) -> dict[str, Any]:
        base = tool.get_schema()
        if protocol in ("openai", "openai-compat"):
            return {
                "type": "function",
                "name": base["name"],
                "description": base["description"],
                "parameters": base["input_schema"],
            }
        return base

    def search_deferred(
        self, query: str, max_results: int, protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        query_lower = query.lower()
        scored: list[tuple[int, str, Tool]] = []
        for name, tool in self._tools.items():
            if not self._is_deferred_searchable(name, tool):
                continue
            score = 0
            name_lower = name.lower()
            desc_lower = (tool.description or "").lower()
            if query_lower in name_lower:
                score += 10
            if query_lower in desc_lower:
                score += 5
            for word in query_lower.split():
                if word in name_lower:
                    score += 3
                if word in desc_lower:
                    score += 1
            if score > 0:
                scored.append((score, name, tool))
        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for _, _name, tool in scored[:max_results]:
            results.append(self._schema_for_protocol(tool, protocol))
        return results

    def find_deferred_by_names(
        self, names: list[str], protocol: str = "anthropic"
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                continue
            if not self._is_deferred_searchable(name, tool):
                continue
            results.append(self._schema_for_protocol(tool, protocol))
        return results

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())


    def get_all_schemas(self, protocol: str = "anthropic") -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for name, tool in self._tools.items():
            if name in self._disabled:
                continue
            if self._is_deferred(tool) and name not in self._discovered:
                continue
            schemas.append(self._schema_for_protocol(tool, protocol))
        return schemas


def create_default_registry(
    file_cache: FileCache | None = None,
    file_history: Any = None,
    base_dir: str | Path | None = None,
) -> ToolRegistry:
    from mozilcode.tools.bash import Bash
    from mozilcode.tools.edit_file import EditFile
    from mozilcode.tools.file_state_cache import FileStateCache
    from mozilcode.tools.glob import Glob
    from mozilcode.tools.grep import Grep
    from mozilcode.tools.read_file import ReadFile
    from mozilcode.tools.write_file import WriteFile

    file_state_cache = FileStateCache()

    registry = ToolRegistry()
    registry.register(
        ReadFile(
            file_cache=file_cache,
            file_state_cache=file_state_cache,
            base_dir=base_dir,
        )
    )
    registry.register(
        WriteFile(
            file_cache=file_cache,
            file_history=file_history,
            file_state_cache=file_state_cache,
            base_dir=base_dir,
        )
    )
    registry.register(
        EditFile(
            file_cache=file_cache,
            file_history=file_history,
            file_state_cache=file_state_cache,
            base_dir=base_dir,
        )
    )
    registry.register(Bash())
    registry.register(Glob(base_dir=base_dir))
    registry.register(Grep(base_dir=base_dir))
    return registry
