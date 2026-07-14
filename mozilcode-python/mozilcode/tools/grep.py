"""Grep 工具：内容搜索。"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from mozilcode.tools.base import SKIP_DIRS, Tool, ToolResult
from mozilcode.tools.paths import resolve_tool_path


class Params(BaseModel):
    pattern: str = Field(min_length=1, description="Regex pattern to search for")
    path: str = Field(default=".", description="Base directory to search from")
    include: str = Field(default="", description="Glob filter for filenames (e.g. '*.py')")


class Grep(Tool):
    name = "Grep"
    description = "Search file contents using a regex pattern, returning file:line:content matches."
    params_model = Params
    category = "read"
    is_concurrency_safe = True

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir


    async def execute(self, params: Params) -> ToolResult:
        if not params.pattern:
            return ToolResult(output="Error: pattern must not be empty", is_error=True)

        base = resolve_tool_path(params.path, self._base_dir)
        if not base.exists():
            return ToolResult(output=f"Error: path not found: {params.path}", is_error=True)
        if not base.is_dir():
            return ToolResult(output=f"Error: path is not a directory: {params.path}", is_error=True)

        try:
            regex = re.compile(params.pattern)
        except re.error as e:
            return ToolResult(output=f"Error: invalid regex: {e}", is_error=True)

        glob_pattern = params.include if params.include else "**/*"
        if not glob_pattern.startswith("**/"):
            glob_pattern = "**/" + glob_pattern

        results: list[str] = []
        for file_path in sorted(base.glob(glob_pattern)):
            if not file_path.is_file():
                continue
            if any(part in SKIP_DIRS for part in file_path.parts):
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for line_num, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = file_path.relative_to(base)
                    results.append(f"{rel}:{line_num}:{line}")

        if not results:
            return ToolResult(output="No matches found.")
        return ToolResult(output="\n".join(results))
