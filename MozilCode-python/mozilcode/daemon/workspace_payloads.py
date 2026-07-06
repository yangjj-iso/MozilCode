from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable


class WorkspacePathError(ValueError):
    """Raised when a requested workspace path cannot be listed safely."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def task_to_dict(task: Any, *, clock: Callable[[], float] = time.monotonic) -> dict:
    elapsed = (task.end_time or clock()) - task.start_time
    return {
        "id": task.id,
        "name": task.name,
        "task": task.task,
        "status": task.status,
        "result": task.result,
        "elapsed": elapsed,
        "input_tokens": task.progress.input_tokens,
        "output_tokens": task.progress.output_tokens,
        "tool_call_count": task.progress.tool_call_count,
        "last_activity": task.progress.last_activity,
    }


def worktree_to_dict(worktree: Any, current_name: str | None = None) -> dict:
    created = getattr(worktree, "created", None)
    return {
        "name": worktree.name,
        "path": worktree.path,
        "branch": worktree.branch,
        "based_on": worktree.based_on,
        "head_commit": worktree.head_commit,
        "created": created.isoformat() if created else "",
        "current": worktree.name == current_name,
    }


def list_workspace_directory(root: Path, relative_path: str = "") -> dict:
    resolved_root = root.resolve()
    target = (resolved_root / (relative_path or "")).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as e:
        raise WorkspacePathError("path outside workspace") from e

    if not target.is_dir():
        raise WorkspacePathError("not a directory")

    try:
        entries = [
            {"name": path.name, "is_dir": path.is_dir()}
            for path in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        ]
    except OSError as e:
        raise WorkspacePathError(str(e), status_code=500) from e

    return {"root": str(resolved_root), "entries": entries}
