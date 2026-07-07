from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mozilcode.daemon.workspace_payloads import worktree_to_dict


@dataclass(frozen=True)
class WorktreeEntry:
    work_dir: str
    worktree: Any | None = None


def normalize_create_worktree_request(name: str, base_branch: str) -> tuple[str, str]:
    name = name.strip()
    base_branch = (base_branch or "").strip() or "HEAD"
    if not name:
        raise ValueError("name is required")
    return name, base_branch


def list_worktrees_payload(manager: Any) -> dict:
    session = manager.get_current_session()
    current_name = session.worktree_name if session else None
    return {
        "current": current_name,
        "worktrees": [
            worktree_to_dict(worktree, current_name)
            for worktree in manager.list_worktrees()
        ],
    }


async def create_and_enter_worktree(
    manager: Any,
    name: str,
    base_branch: str,
) -> WorktreeEntry:
    worktree = await manager.create(name, base_branch)
    session = await manager.enter(name)
    return WorktreeEntry(work_dir=session.worktree_path, worktree=worktree)


async def enter_worktree(manager: Any, name: str) -> WorktreeEntry:
    session = await manager.enter(name)
    return WorktreeEntry(work_dir=session.worktree_path)


async def exit_worktree(
    manager: Any,
    *,
    remove: bool = False,
    discard: bool = False,
) -> WorktreeEntry:
    session = manager.get_current_session()
    if session is None:
        raise ValueError("not in a worktree")
    await manager.exit(
        session.worktree_name,
        action="remove" if remove else "keep",
        discard_changes=discard,
    )
    return WorktreeEntry(work_dir=session.original_cwd)
