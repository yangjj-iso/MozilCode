from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import create_app
from mozilcode.daemon.responses import DaemonActionResult
from mozilcode.daemon.session_store import SessionStore
from mozilcode.daemon.server_state import DaemonServer, DaemonSessionRuntime
from mozilcode.daemon.worktree_actions import (
    create_and_enter_worktree,
    exit_worktree as exit_worktree_action,
    list_worktrees_payload,
    normalize_create_worktree_request,
)
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
    server._agents[sid] = DaemonSessionRuntime(
        agent,
        SimpleNamespace(provider=_Provider(), worktree_manager=manager),
        _Conversation(),
    )
    server._records.event_logs[sid] = []
    server._records.session_meta[sid] = {"work_dir": str(tmp_path), "title": "worktrees"}
    server._records.persisted_count[sid] = 0
    return server, sid, agent, manager


def test_normalize_create_worktree_request_trims_name_and_defaults_branch() -> None:
    assert normalize_create_worktree_request(" feature ", "   ") == (
        "feature",
        "HEAD",
    )


def test_normalize_create_worktree_request_requires_name() -> None:
    with pytest.raises(ValueError, match="name is required"):
        normalize_create_worktree_request(" ", "main")


@pytest.mark.asyncio
async def test_create_and_enter_worktree_action_returns_work_dir(tmp_path):
    manager = _WorktreeManager(str(tmp_path))

    entry = await create_and_enter_worktree(manager, "feature", "main")

    assert entry.worktree is manager.active["feature"]
    assert entry.work_dir.endswith("/.mozilcode/worktrees/feature")
    assert manager.created_with == ("feature", "main")


@pytest.mark.asyncio
async def test_exit_worktree_action_returns_original_work_dir(tmp_path):
    manager = _WorktreeManager(str(tmp_path))
    await create_and_enter_worktree(manager, "feature", "HEAD")

    entry = await exit_worktree_action(manager, remove=True, discard=True)

    assert entry.work_dir == str(tmp_path)
    assert manager.exited_with == ("feature", "remove", True)


def test_list_worktrees_payload_marks_current(tmp_path) -> None:
    manager = _WorktreeManager(str(tmp_path))
    manager.active["feature"] = Worktree(
        name="feature",
        path=f"{tmp_path}/.mozilcode/worktrees/feature",
        branch="worktree-feature",
        based_on="HEAD",
        head_commit="abc123",
    )
    manager.current_session = WorktreeSession(
        original_cwd=str(tmp_path),
        worktree_path=manager.active["feature"].path,
        worktree_name="feature",
        original_branch="main",
        original_head_commit="abc123",
    )

    payload = list_worktrees_payload(manager)

    assert payload["current"] == "feature"
    assert payload["worktrees"][0]["name"] == "feature"
    assert payload["worktrees"][0]["current"] is True


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
async def test_create_worktree_requires_name(tmp_path):
    server, sid, _agent, _manager = _server_with_worktrees(tmp_path)

    result = await server.create_worktree(sid, " ")

    assert result == DaemonActionResult(
        {"error": "name is required"},
        status_code=400,
    )


@pytest.mark.asyncio
async def test_create_worktree_blank_base_branch_defaults_to_head(tmp_path):
    server, sid, _agent, manager = _server_with_worktrees(tmp_path)

    result = await server.create_worktree(sid, "feature", "   ")

    assert result.status_code == 200
    assert manager.created_with == ("feature", "HEAD")
    assert result.payload["worktree"]["based_on"] == "HEAD"


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
async def test_enter_worktree_returns_manager_error(tmp_path):
    server, sid, _agent, _manager = _server_with_worktrees(tmp_path)

    result = await server.enter_worktree(sid, "missing")

    assert result == DaemonActionResult(
        {"error": "worktree not found: missing"},
        status_code=400,
    )


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


@pytest.mark.asyncio
async def test_worktree_actions_return_404_for_missing_session(tmp_path):
    server = DaemonServer(AppConfig(providers=[]), str(tmp_path))

    listed = await server.list_worktrees("missing")
    created = await server.create_worktree("missing", "feature")
    entered = await server.enter_worktree("missing", "feature")
    exited = await server.exit_worktree("missing")

    expected = DaemonActionResult(
        {"error": "session not found"},
        status_code=404,
    )
    assert listed == expected
    assert created == expected
    assert entered == expected
    assert exited == expected


def test_worktree_route_uses_server_action_result(tmp_path, monkeypatch):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    app = create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )

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


def test_enter_worktree_route_accepts_nested_worktree_name(tmp_path, monkeypatch):
    provider = ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="smoke-model",
    )
    app = create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )

    async def fake_enter_worktree(sid: str, name: str):
        assert (sid, name) == ("sid-1", "team/alice")
        return DaemonActionResult({"entered": True})

    monkeypatch.setattr(app.state.server, "enter_worktree", fake_enter_worktree)

    with TestClient(app) as client:
        response = client.post("/api/session/sid-1/worktrees/team/alice/enter")

    assert response.status_code == 200
    assert response.json() == {"entered": True}
