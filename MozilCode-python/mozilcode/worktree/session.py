from __future__ import annotations

import json
import logging
from pathlib import Path

from mozilcode.worktree.models import WorktreeSession

log = logging.getLogger(__name__)

SESSION_FILENAME = "worktree_session.json"
REQUIRED_STRING_FIELDS = (
    "original_cwd",
    "worktree_path",
    "worktree_name",
    "original_branch",
    "original_head_commit",
)


def _session_path(mozilcode_dir: Path) -> Path:
    return mozilcode_dir / SESSION_FILENAME


def _required_string(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def save_worktree_session(
    mozilcode_dir: Path,
    session: WorktreeSession | None,
) -> None:
    path = _session_path(mozilcode_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if session is None:
        path.write_text("{}", encoding="utf-8")
        return
    data = {
        "original_cwd": session.original_cwd,
        "worktree_path": session.worktree_path,
        "worktree_name": session.worktree_name,
        "original_branch": session.original_branch,
        "original_head_commit": session.original_head_commit,
        "session_id": session.session_id,
        "hook_based": session.hook_based,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_worktree_session(mozilcode_dir: Path) -> WorktreeSession | None:
    path = _session_path(mozilcode_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data:
            return None
        if not isinstance(data, dict):
            raise ValueError("worktree session must be an object")
        for field in REQUIRED_STRING_FIELDS:
            _required_string(data, field)
        session_id = data.get("session_id", "")
        if not isinstance(session_id, str):
            raise ValueError("session_id must be a string")
        hook_based = data.get("hook_based", False)
        if not isinstance(hook_based, bool):
            raise ValueError("hook_based must be a boolean")
        return WorktreeSession(
            original_cwd=data["original_cwd"],
            worktree_path=data["worktree_path"],
            worktree_name=data["worktree_name"],
            original_branch=data["original_branch"],
            original_head_commit=data["original_head_commit"],
            session_id=session_id,
            hook_based=hook_based,
        )
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Failed to load worktree session: %s", e)
        return None
    except OSError as e:
        log.warning("Failed to read worktree session: %s", e)
        return None
