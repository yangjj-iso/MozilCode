import pytest
from starlette.testclient import TestClient

from mozilcode.config import (
    AppConfig,
    ProviderConfig,
)
from mozilcode.daemon.routes import build_routes
from mozilcode.daemon.server import create_app
from mozilcode.daemon.server import DaemonServer
from mozilcode.daemon.server_state import DaemonSessionRuntime
from mozilcode.daemon.session_store import SessionStore
from mozilcode.permissions.modes import PermissionMode


class _FakeRegistry:
    def list_tools(self):
        return []

    def is_enabled(self, _name):
        return False


class _FakeAgent:
    def __init__(self, mode):
        self.permission_mode = mode
        self.registry = _FakeRegistry()
        self.context_window = 128000
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    @property
    def plan_mode(self):
        return self.permission_mode == PermissionMode.PLAN

    def set_permission_mode(self, mode):
        self.permission_mode = mode


class _FakeDeps:
    def __init__(self, provider):
        self.provider = provider


def test_root_route_is_not_an_application_shell(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 404


def test_daemon_does_not_enable_browser_cors(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        response = client.get(
            "/api/health",
            headers={"origin": "http://127.0.0.1:5173"},
        )

    assert "access-control-allow-origin" not in response.headers


def test_a2a_agent_card_route_is_available(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        response = client.get("/a2a/agent-card.json")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "MozilCode"
    assert data["metadata"]["model"] == "gpt-local"


def test_a2a_message_send_rejects_non_object_metadata(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/a2a/message:send",
            json={
                "message": {"parts": [{"kind": "text", "text": "hello"}]},
                "metadata": "bad",
            },
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": "metadata must be an object",
        "code": -32602,
    }


def test_route_registry_keeps_local_daemon_surface_only():
    paths = {route.path for route in build_routes()}

    assert "/api/health" in paths
    assert "/api/session" in paths
    assert "/api/stream/{sid}" in paths
    assert "/a2a/rpc" in paths
    assert "/" not in paths
    assert "/api/config" not in paths
    assert "/api/settings/mcp" not in paths
    assert "/api/settings/memory" not in paths
    assert "/api/skills" not in paths
    assert "/api/settings/qqbot" not in paths
    assert "/api/settings/telegrambot" not in paths


def test_external_bot_settings_routes_are_removed(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        qq = client.get("/api/settings/qqbot")
        telegram = client.get("/api/settings/telegrambot")
        qq_status = client.get("/api/qq/official/status")
        telegram_status = client.get("/api/telegram/status")

    assert qq.status_code == 404
    assert telegram.status_code == 404
    assert qq_status.status_code == 404
    assert telegram_status.status_code == 404


def test_gui_management_routes_are_removed(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        responses = [
            client.get("/api/config"),
            client.post("/api/config", json={}),
            client.get("/api/settings/mcp"),
            client.post("/api/settings/mcp", json={}),
            client.get("/api/settings/memory"),
            client.post("/api/settings/memory", json={}),
            client.get("/api/skills"),
            client.post("/api/skills", json={}),
        ]

    assert {response.status_code for response in responses} == {404}


def test_create_session_rejects_malformed_json(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/api/session",
            content="{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "Invalid JSON body"


@pytest.mark.asyncio
async def test_command_acceptance_stays_separate_from_plan_mode(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    server = DaemonServer(AppConfig(providers=[provider]), str(tmp_path))
    agent = _FakeAgent(PermissionMode.ACCEPT_EDITS)
    sid = "test-session"
    server._agents[sid] = DaemonSessionRuntime(agent, _FakeDeps(provider), object())
    server._event_logs[sid] = []
    server._session_meta[sid] = {"work_dir": str(tmp_path), "title": ""}

    status = await server.set_permission_mode(sid, "plan")

    assert status["permission_mode"] == "plan"
    assert status["command_acceptance_mode"] == "acceptEdits"
    assert status["plan_mode"] is True

    status = await server.set_permission_mode(sid, "bypassPermissions")

    assert status["permission_mode"] == "plan"
    assert status["command_acceptance_mode"] == "bypassPermissions"
    assert status["plan_mode"] is True

    status = await server.set_permission_mode(sid, "do")

    assert status["permission_mode"] == "bypassPermissions"
    assert status["command_acceptance_mode"] == "bypassPermissions"
    assert status["plan_mode"] is False


def test_session_runtime_accessors_use_named_fields(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    server = DaemonServer(AppConfig(providers=[provider]), str(tmp_path))
    agent = _FakeAgent(PermissionMode.DEFAULT)
    deps = _FakeDeps(provider)
    conversation = object()

    server._agents["sid-1"] = DaemonSessionRuntime(agent, deps, conversation)

    assert server.get_agent("sid-1") is agent
    assert server.get_deps("sid-1") is deps
    assert server.get_conversation("sid-1") is conversation


@pytest.mark.asyncio
async def test_init_session_creates_named_runtime(tmp_path, monkeypatch):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    captured = {}

    async def fake_create_agent_from_config(config, work_dir, mode, hook_engine):
        captured.update(
            {
                "config": config,
                "work_dir": work_dir,
                "mode": mode,
                "hook_engine": hook_engine,
            }
        )
        return _FakeAgent(mode), _FakeDeps(config.providers[0])

    monkeypatch.setattr(
        "mozilcode.daemon.server_state.create_agent_from_config",
        fake_create_agent_from_config,
    )
    config = AppConfig(providers=[provider], permission_mode="acceptEdits")
    server = DaemonServer(
        config,
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )

    sid = await server.init_session("sid-runtime")

    runtime = server._agents[sid]
    session = await server.session_mgr.get_session(sid)
    assert runtime.agent.session_id == "sid-runtime"
    assert runtime.deps.provider is provider
    assert server.get_agent(sid) is runtime.agent
    assert server.get_deps(sid) is runtime.deps
    assert server.get_conversation(sid) is runtime.conversation
    assert session is not None
    assert session.agent is runtime.agent
    assert session.conversation is runtime.conversation
    assert captured == {
        "config": config,
        "work_dir": str(tmp_path),
        "mode": PermissionMode.ACCEPT_EDITS,
        "hook_engine": None,
    }


@pytest.mark.asyncio
async def test_ensure_agent_recreates_persisted_runtime(tmp_path, monkeypatch):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )

    async def fake_create_agent_from_config(config, work_dir, mode, _hook_engine):
        return _FakeAgent(mode), _FakeDeps(config.providers[0])

    monkeypatch.setattr(
        "mozilcode.daemon.server_state.create_agent_from_config",
        fake_create_agent_from_config,
    )
    server = DaemonServer(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )
    server._session_meta["sid-persisted"] = {
        "work_dir": str(tmp_path),
        "title": "persisted",
    }

    assert await server.ensure_agent("sid-persisted") is True

    runtime = server._agents["sid-persisted"]
    session = await server.session_mgr.get_session("sid-persisted")
    assert runtime.agent.session_id == "sid-persisted"
    assert server._event_logs["sid-persisted"] == []
    assert session is not None
    assert session.agent is runtime.agent
