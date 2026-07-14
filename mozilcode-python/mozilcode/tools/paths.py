"""工具路径解析（相对工作目录）。"""

from __future__ import annotations

from pathlib import Path


def resolve_tool_path(path: str, base_dir: str | Path | None = None) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or base_dir is None:
        return candidate
    return Path(base_dir) / candidate
