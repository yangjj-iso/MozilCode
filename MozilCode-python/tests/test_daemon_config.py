import pytest
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.testclient import TestClient

from mozilcode.config import (
    AppConfig,
    ProviderConfig,
)
from mozilcode.daemon.routes.core import HTTP_ROUTES, WEBSOCKET_ROUTES, build_routes
from mozilcode.daemon.server import create_app
from mozilcode.daemon.server import DaemonServer
from mozilcode.daemon.server_state import DaemonSessionRuntime
from mozilcode.daemon.session.store import SessionStore
from mozilcode.permissions.modes import PermissionMode
from mozilcode.config.removed_capabilities import (
    REMOVED_APP_SHELL_PATHS,
    REMOVED_MANAGEMENT_PATHS,
    find_removed_route_paths,
)


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


def _create_app(provider, tmp_path):
    return create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )


@pytest.mark.parametrize("path", sorted(REMOVED_APP_SHELL_PATHS))
def test_removed_app_shell_paths_are_not_served(tmp_path, path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = _create_app(provider, tmp_path)

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 404, path


def test_create_app_uses_injected_session_store(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    store = SessionStore(tmp_path / "sessions")

    app = create_app(
        AppConfig(providers=[provider]),
        str(tmp_path),
        session_store=store,
    )

    assert app.state.server.session_store is store
    assert app.state.server.list_session_infos() == []


def test_daemon_does_not_enable_browser_cors(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = _create_app(provider, tmp_path)

    with TestClient(app) as client:
        response = client.get(
            "/api/health",
            headers={"origin": "http://127.0.0.1:5173"},
        )

    assert "access-control-allow-origin" not in response.headers


def test_app_does_not_mount_gui_or_cloud_shells(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = _create_app(provider, tmp_path)

    assert app.user_middleware == []
    assert [route for route in app.routes if isinstance(route, Mount)] == []
    assert {route.path for route in app.routes if isinstance(route, Route)}.isdisjoint(
        REMOVED_APP_SHELL_PATHS
    )


def test_a2a_agent_card_route_is_available(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = _create_app(provider, tmp_path)

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
    app = _create_app(provider, tmp_path)
    session_count = len(app.state.server.list_session_infos())

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
    assert len(app.state.server.list_session_infos()) == session_count


def test_a2a_message_send_rejects_non_object_configuration(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = _create_app(provider, tmp_path)
    session_count = len(app.state.server.list_session_infos())

    with TestClient(app) as client:
        response = client.post(
            "/a2a/message:send",
            json={
                "message": {"parts": [{"kind": "text", "text": "hello"}]},
                "configuration": "bad",
            },
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": "configuration must be an object",
        "code": -32602,
    }
    assert len(app.state.server.list_session_infos()) == session_count


def test_route_registry_keeps_local_daemon_surface_only():
    assert [(spec.path, spec.methods) for spec in HTTP_ROUTES] == [
        ("/.well-known/agent-card.json", ("GET",)),
        ("/a2a/agent-card.json", ("GET",)),
        ("/a2a/rpc", ("POST",)),
        ("/a2a/message:send", ("POST",)),
        ("/a2a/tasks/{task_id}", ("GET",)),
        ("/a2a/tasks/{task_id}:cancel", ("POST",)),
        ("/api/health", ("GET",)),
        ("/api/session", ("POST",)),
        ("/api/sessions", ("GET",)),
        ("/api/task", ("POST",)),
        ("/api/session/{sid}/status", ("GET",)),
        ("/api/session/{sid}/mode", ("POST",)),
        ("/api/session/{sid}/cancel", ("POST",)),
        ("/api/session/{sid}/tasks", ("GET",)),
        ("/api/session/{sid}/tasks/{task_id}/cancel", ("POST",)),
        ("/api/session/{sid}/worktrees", ("GET",)),
        ("/api/session/{sid}/worktrees", ("POST",)),
        ("/api/session/{sid}/worktrees/{name:path}/enter", ("POST",)),
        ("/api/session/{sid}/worktrees/exit", ("POST",)),
        ("/api/permission/{sid}", ("POST",)),
        ("/api/askuser/{sid}", ("POST",)),
        ("/api/compact/{sid}", ("POST",)),
        ("/api/session/{sid}", ("GET",)),
        ("/api/session/{sid}", ("DELETE",)),
        ("/api/fs/{sid}", ("GET",)),
    ]
    assert [(spec.path, "WEBSOCKET") for spec in WEBSOCKET_ROUTES] == [
        ("/api/stream/{sid}", "WEBSOCKET"),
    ]


def test_route_registry_excludes_gui_cloud_and_bot_management():
    route_paths = [
        spec.path.lower()
        for spec in (*HTTP_ROUTES, *WEBSOCKET_ROUTES)
    ]

    assert find_removed_route_paths(route_paths) == ()


def test_removed_gui_cloud_and_bot_routes_are_not_served(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = _create_app(provider, tmp_path)

    with TestClient(app) as client:
        for path in sorted(REMOVED_MANAGEMENT_PATHS):
            response = client.post(path, json={})
            assert response.status_code == 404, path


def test_build_routes_matches_declared_route_specs():
    actual_http = []
    actual_websocket = []
    for route in build_routes():
        if isinstance(route, WebSocketRoute):
            actual_websocket.append((route.path, route.endpoint))
        elif isinstance(route, Route):
            methods = tuple(sorted((route.methods or set()) - {"HEAD"}))
            actual_http.append((route.path, route.endpoint, methods))

    assert actual_http == [
        (spec.path, spec.endpoint, spec.methods)
        for spec in HTTP_ROUTES
    ]
    assert actual_websocket == [
        (spec.path, spec.endpoint)
        for spec in WEBSOCKET_ROUTES
    ]


def test_create_session_rejects_malformed_json(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = _create_app(provider, tmp_path)

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
    server._records.event_logs[sid] = []
    server._records.session_meta[sid] = {"work_dir": str(tmp_path), "title": ""}

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
    server._records.session_meta["sid-persisted"] = {
        "work_dir": str(tmp_path),
        "title": "persisted",
    }

    assert await server.ensure_agent("sid-persisted") is True

    runtime = server._agents["sid-persisted"]
    session = await server.session_mgr.get_session("sid-persisted")
    assert runtime.agent.session_id == "sid-persisted"
    assert server._records.event_logs["sid-persisted"] == []
    assert session is not None
    assert session.agent is runtime.agent
