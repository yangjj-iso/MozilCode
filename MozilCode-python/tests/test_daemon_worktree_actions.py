from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import create_app
from mozilcode.daemon.server_state import DaemonActionResult, DaemonServer
from mozilcode.permissions import PermissionMode
from mozilcode.worktree.models import Worktree, WorktreeSession


class _Registry:
    def list_tools(self):
        return []

    def is_enabled(self, _name):
        return False


class _Agent:
    permission_mode = PermissionMode.DEFAULT
    plan_mode = False
    context_window = 128_000
    total_input_tokens = 0
    total_output_tokens = 0
    registry = _Registry()
    memory_hub = None

    def __init__(self, work_dir: str) -> None:
        self.work_dir = work_dir


class _Conversation:
    def current_tokens(self):
        return 0


class _Provider:
    name = "local"
    protocol = "openai-compat"
    model = "smoke-model"

    def get_context_window(self):
        return 128_000


class _WorktreeManager:
    def __init__(self, root: str) -> None:
        self.root = root
        self.active: dict[str, Worktree] = {}
        self.current_session: WorktreeSession | None = None
        self.created_with: tuple[str, str] | None = None
        self.exited_with: tuple[str, str, bool] | None = None

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

    async def exit(self, name: str, action: str = "keep", discard_changes: bool = False):
        if self.current_session is None:
            raise ValueError("not in a worktree")
        self.exited_with = (name, action, discard_changes)
        self.current_session = None


def _server_with_worktrees(tmp_path) -> tuple[DaemonServer, str, _Agent, _WorktreeManager]:
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    server = DaemonServer(AppConfig(providers=[provider]), str(tmp_path))
    sid = "session-worktree"
    agent = _Agent(str(tmp_path))
    manager = _WorktreeManager(str(tmp_path))
    server._agents[sid] = (
        agent,
        SimpleNamespace(provider=_Provider(), worktree_manager=manager),
        _Conversation(),
    )
    server._event_logs[sid] = []
    server._session_meta[sid] = {"work_dir": str(tmp_path), "title": "worktrees"}
    server._persisted_count[sid] = 0
    return server, sid, agent, manager


@pytest.mark.asyncio
async def test_create_worktree_enters_and_updates_session_work_dir(tmp_path):
    server, sid, agent, manager = _server_with_worktrees(tmp_path)

    result = await server.create_worktree(sid, " feature ", "main")

    assert result.status_code == 200
    assert result.payload["worktree"]["name"] == "feature"
    assert result.payload["worktree"]["current"] is True
    assert result.payload["status"]["work_dir"].endswith("/.mozilcode/worktrees/feature")
    assert manager.created_with == ("feature", "main")
    assert agent.work_dir.endswith("/.mozilcode/worktrees/feature")
    assert server.session_work_dir(sid).endswith("/.mozilcode/worktrees/feature")


@pytest.mark.asyncio
async def test_list_worktrees_marks_current_worktree(tmp_path):
    server, sid, _agent, _manager = _server_with_worktrees(tmp_path)
    await server.create_worktree(sid, "feature", "HEAD")

    result = await server.list_worktrees(sid)

    assert result.payload["current"] == "feature"
    assert result.payload["worktrees"][0]["name"] == "feature"
    assert result.payload["worktrees"][0]["current"] is True


@pytest.mark.asyncio
async def test_enter_worktree_updates_agent_and_status(tmp_path):
    server, sid, agent, manager = _server_with_worktrees(tmp_path)
    await manager.create("feature", "HEAD")

    result = await server.enter_worktree(sid, "feature")

    assert result.payload["entered"] is True
    assert result.payload["status"]["work_dir"].endswith("/.mozilcode/worktrees/feature")
    assert agent.work_dir.endswith("/.mozilcode/worktrees/feature")


@pytest.mark.asyncio
async def test_exit_worktree_returns_to_original_workspace(tmp_path):
    server, sid, agent, manager = _server_with_worktrees(tmp_path)
    await server.create_worktree(sid, "feature", "HEAD")

    result = await server.exit_worktree(sid, remove=True, discard=True)

    assert result.payload["exited"] is True
    assert result.payload["status"]["work_dir"] == str(tmp_path)
    assert agent.work_dir == str(tmp_path)
    assert server.session_work_dir(sid) == str(tmp_path)
    assert manager.exited_with == ("feature", "remove", True)


@pytest.mark.asyncio
async def test_exit_worktree_without_active_session_returns_error(tmp_path):
    server, sid, _agent, _manager = _server_with_worktrees(tmp_path)

    result = await server.exit_worktree(sid)

    assert result == DaemonActionResult(
        {"error": "not in a worktree"},
        status_code=400,
    )


def test_worktree_route_uses_server_action_result(tmp_path, monkeypatch):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    async def fake_create_worktree(sid: str, name: str, base_branch: str):
        assert (sid, name, base_branch) == ("sid-1", "feature", "main")
        return DaemonActionResult({"created": True}, status_code=201)

    monkeypatch.setattr(app.state.server, "create_worktree", fake_create_worktree)

    with TestClient(app) as client:
        response = client.post(
            "/api/session/sid-1/worktrees",
            json={"name": "feature", "base_branch": "main"},
        )

    assert response.status_code == 201
    assert response.json() == {"created": True}
