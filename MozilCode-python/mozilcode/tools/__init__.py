from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mozilcode.tools.base import Tool
from mozilcode.tools.registry import ToolRegistry, ToolRegistryError

if TYPE_CHECKING:
    from mozilcode.cache import FileCache


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


def rebase_file_tools(registry: ToolRegistry, base_dir: str | Path) -> ToolRegistry:
    """Clone built-in file tools so relative paths resolve from ``base_dir``.

    Tool filtering can produce a registry that still points at a parent agent's
    file tool instances. Sub-agents and worktree agents need the same filtered
    tool surface, but with file reads/writes/searches rooted at their own
    working directory.
    """
    from mozilcode.tools.edit_file import EditFile
    from mozilcode.tools.file_state_cache import FileStateCache
    from mozilcode.tools.glob import Glob
    from mozilcode.tools.grep import Grep
    from mozilcode.tools.read_file import ReadFile
    from mozilcode.tools.write_file import WriteFile

    state_cache = FileStateCache()
    replacements: dict[str, Tool] = {}
    for tool in registry.list_tools():
        if isinstance(tool, ReadFile):
            replacements[tool.name] = ReadFile(
                file_cache=getattr(tool, "_cache", None),
                file_state_cache=state_cache,
                base_dir=base_dir,
            )
        elif isinstance(tool, WriteFile):
            replacements[tool.name] = WriteFile(
                file_cache=getattr(tool, "_cache", None),
                file_history=getattr(tool, "file_history", None),
                file_state_cache=state_cache,
                base_dir=base_dir,
            )
        elif isinstance(tool, EditFile):
            replacements[tool.name] = EditFile(
                file_cache=getattr(tool, "_cache", None),
                file_history=getattr(tool, "file_history", None),
                file_state_cache=state_cache,
                base_dir=base_dir,
            )
        elif isinstance(tool, Glob):
            replacements[tool.name] = Glob(base_dir=base_dir)
        elif isinstance(tool, Grep):
            replacements[tool.name] = Grep(base_dir=base_dir)

    rebased = ToolRegistry()
    for tool in registry.list_tools():
        replacement = replacements.get(tool.name, tool)
        rebased.register(replacement)
        if not registry.is_enabled(tool.name):
            rebased.disable(tool.name)
        if registry.is_discovered(tool.name):
            rebased.mark_discovered(tool.name)
    return rebased
