from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from mozilcode.daemon.workspace_payloads import WorkspacePathError
from mozilcode.daemon.workspace_payloads import list_workspace_directory
from mozilcode.daemon.workspace_payloads import task_to_dict
from mozilcode.daemon.workspace_payloads import worktree_to_dict
from mozilcode.worktree.models import Worktree


def test_task_to_dict_uses_running_clock_for_elapsed():
    task = SimpleNamespace(
        id="task-1",
        name="lint",
        task="run lint",
        status="running",
        result="",
        start_time=10.0,
        end_time=None,
        progress=SimpleNamespace(
            input_tokens=11,
            output_tokens=7,
            tool_call_count=3,
            last_activity="Bash",
        ),
    )

    payload = task_to_dict(task, clock=lambda: 15.5)

    assert payload == {
        "id": "task-1",
        "name": "lint",
        "task": "run lint",
        "status": "running",
        "result": "",
        "elapsed": 5.5,
        "input_tokens": 11,
        "output_tokens": 7,
        "tool_call_count": 3,
        "last_activity": "Bash",
    }


def test_worktree_to_dict_marks_current_worktree():
    created = datetime(2026, 1, 2, 3, 4, 5)
    worktree = Worktree(
        name="feature",
        path="D:/repo/.worktrees/feature",
        branch="feature",
        based_on="main",
        head_commit="abc123",
        created=created,
    )

    payload = worktree_to_dict(worktree, current_name="feature")

    assert payload == {
        "name": "feature",
        "path": "D:/repo/.worktrees/feature",
        "branch": "feature",
        "based_on": "main",
        "head_commit": "abc123",
        "created": "2026-01-02T03:04:05",
        "current": True,
    }


def test_list_workspace_directory_sorts_directories_before_files(tmp_path):
    (tmp_path / "z-file.txt").write_text("x", encoding="utf-8")
    (tmp_path / "A-dir").mkdir()
    (tmp_path / "b-file.txt").write_text("x", encoding="utf-8")

    payload = list_workspace_directory(tmp_path)

    assert payload["root"] == str(tmp_path.resolve())
    assert payload["entries"] == [
        {"name": "A-dir", "is_dir": True},
        {"name": "b-file.txt", "is_dir": False},
        {"name": "z-file.txt", "is_dir": False},
    ]


def test_list_workspace_directory_rejects_path_outside_workspace(tmp_path):
    with pytest.raises(WorkspacePathError, match="path outside workspace") as exc:
        list_workspace_directory(tmp_path, "..")

    assert exc.value.status_code == 400


def test_list_workspace_directory_rejects_file_target(tmp_path):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    with pytest.raises(WorkspacePathError, match="not a directory") as exc:
        list_workspace_directory(tmp_path, "file.txt")

    assert exc.value.status_code == 400
