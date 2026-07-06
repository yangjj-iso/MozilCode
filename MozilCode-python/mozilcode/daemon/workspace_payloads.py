from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mozilcode.daemon.request_body import (
    bool_field,
    required_string_field,
    string_field,
)


@dataclass(frozen=True)
class CreateWorktreeBody:
    name: str
    base_branch: str


@dataclass(frozen=True)
class ExitWorktreeBody:
    remove: bool
    discard: bool


class WorkspacePathError(ValueError):
    """Raised when a requested workspace path cannot be listed safely."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def parse_create_worktree_body(body: dict[str, Any]) -> CreateWorktreeBody:
    return CreateWorktreeBody(
        name=required_string_field(body, "name"),
        base_branch=string_field(body, "base_branch", "HEAD").strip(),
    )


def parse_exit_worktree_body(body: dict[str, Any]) -> ExitWorktreeBody:
    return ExitWorktreeBody(
        remove=bool_field(body, "remove"),
        discard=bool_field(body, "discard"),
    )


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


def _entry_is_workspace_dir(path: Path, resolved_root: Path) -> bool:
    if not path.is_dir():
        return False
    if not path.is_symlink():
        return True
    try:
        path.resolve().relative_to(resolved_root)
    except (OSError, ValueError):
        return False
    return True


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
        entries = []
        for path in target.iterdir():
            entries.append(
                {
                    "name": path.name,
                    "is_dir": _entry_is_workspace_dir(path, resolved_root),
                }
            )
        entries.sort(key=lambda entry: (not entry["is_dir"], entry["name"].lower()))
    except OSError as e:
        raise WorkspacePathError(str(e), status_code=500) from e

    return {"root": str(resolved_root), "entries": entries}
