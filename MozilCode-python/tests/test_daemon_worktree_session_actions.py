from __future__ import annotations

from types import SimpleNamespace

import pytest

from mozilcode.daemon.responses import DaemonActionResult
from mozilcode.daemon.actions.worktree_session import (
    create_session_worktree,
    enter_session_worktree,
    list_session_worktrees,
)
from mozilcode.worktree.models import Worktree, WorktreeSession


class _Agent:
    def __init__(self, work_dir: str) -> None:
        self.work_dir = work_dir


class _WorktreeManager:
    def __init__(self, root: str) -> None:
        self.root = root
        self.active: dict[str, Worktree] = {}
        self.current_session: WorktreeSession | None = None
        self.created_with: tuple[str, str] | None = None

    def list_worktrees(self):
        return list(self.active.values())

    def get_current_session(self):
        return self.current_session

    async def create(self, name: str, base_branch: str = "HEAD"):
        self.created_with = (name, base_branch)
        worktree = Worktree(
            name=name,
            path=f"{self.root}/.mozilcode/worktrees/{name}",
            branch=f"worktree-{name}",
            based_on=base_branch,
            head_commit="abc123",
        )
        self.active[name] = worktree
        return worktree

    async def enter(self, name: str):
        worktree = self.active.get(name)
        if worktree is None:
            raise ValueError(f"worktree not found: {name}")
        self.current_session = WorktreeSession(
            original_cwd=self.root,
            worktree_path=worktree.path,
            worktree_name=name,
            original_branch="main",
            original_head_commit="abc123",
        )
        return self.current_session


def _set_agent_work_dir(_sid: str, agent: _Agent, work_dir: str) -> None:
    agent.work_dir = work_dir


@pytest.mark.asyncio
async def test_list_session_worktrees_returns_current_payload(tmp_path) -> None:
    manager = _WorktreeManager(str(tmp_path))
    await manager.create("feature", "HEAD")
    await manager.enter("feature")

    async def require_deps(_sid: str):
        return SimpleNamespace(worktree_manager=manager), None

    result = await list_session_worktrees("sid", require_deps)

    assert result.payload["current"] == "feature"
    assert result.payload["worktrees"][0]["current"] is True


@pytest.mark.asyncio
async def test_create_session_worktree_validates_name_before_session_lookup() -> None:
    async def require_agent_and_deps(_sid: str):
        raise AssertionError("session lookup should not run for invalid names")

    result = await create_session_worktree(
        "sid",
        " ",
        "HEAD",
        require_agent_and_deps=require_agent_and_deps,
        set_agent_work_dir=_set_agent_work_dir,
        status_provider=lambda _sid: {},
    )

    assert result == DaemonActionResult({"error": "name is required"}, status_code=400)


@pytest.mark.asyncio
async def test_create_session_worktree_updates_agent_work_dir_and_status(tmp_path) -> None:
    agent = _Agent(str(tmp_path))
    manager = _WorktreeManager(str(tmp_path))

    async def require_agent_and_deps(_sid: str):
        return agent, SimpleNamespace(worktree_manager=manager), None

    result = await create_session_worktree(
        "sid",
        " feature ",
        "  ",
        require_agent_and_deps=require_agent_and_deps,
        set_agent_work_dir=_set_agent_work_dir,
        status_provider=lambda sid: {"id": sid, "work_dir": agent.work_dir},
    )

    assert result.status_code == 200
    assert manager.created_with == ("feature", "HEAD")
    assert agent.work_dir.endswith("/.mozilcode/worktrees/feature")
    assert result.payload["worktree"]["name"] == "feature"
    assert result.payload["worktree"]["current"] is True
    assert result.payload["status"]["work_dir"] == agent.work_dir


@pytest.mark.asyncio
async def test_enter_session_worktree_converts_manager_error(tmp_path) -> None:
    agent = _Agent(str(tmp_path))
    manager = _WorktreeManager(str(tmp_path))

    async def require_agent_and_deps(_sid: str):
        return agent, SimpleNamespace(worktree_manager=manager), None

    result = await enter_session_worktree(
        "sid",
        "missing",
        require_agent_and_deps=require_agent_and_deps,
        set_agent_work_dir=_set_agent_work_dir,
        status_provider=lambda _sid: {},
    )

    assert result == DaemonActionResult(
        {"error": "worktree not found: missing"},
        status_code=400,
    )
