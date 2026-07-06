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
