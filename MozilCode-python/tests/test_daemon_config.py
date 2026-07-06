import pytest
from starlette.testclient import TestClient

from mozilcode.config import (
    AppConfig,
    MemoryConfig,
    MemoryProviderConfig,
    ProviderConfig,
    load_config,
)
from mozilcode.daemon import config_settings
from mozilcode.daemon.config_settings import config_from_settings_payload
from mozilcode.daemon.routes import build_routes
from mozilcode.daemon.settings import normalize_daemon_settings
from mozilcode.daemon.server import create_app
from mozilcode.daemon.server import DaemonServer
from mozilcode.permissions.modes import PermissionMode
from mozilcode.validator import ConfigError


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


def test_normalize_daemon_settings_returns_independent_defaults():
    first = normalize_daemon_settings({})
    first["mcp_servers"].append({"name": "local"})
    first["disabled_skills"].append("review")

    second = normalize_daemon_settings({})

    assert second["mcp_servers"] == []
    assert second["disabled_skills"] == []


def test_settings_config_normalizes_local_openai_base_url_to_v1():
    raw = config_from_settings_payload({
        "protocol": "openai",
        "name": "openai",
        "base_url": "http://127.0.0.1:8080",
        "model": "gpt-local",
        "api_key": "",
    })

    assert raw["providers"][0]["base_url"] == "http://127.0.0.1:8080/v1"


def test_settings_config_preserves_existing_api_key_when_submitted_blank():
    current = AppConfig(providers=[
        ProviderConfig(
            name="openai",
            protocol="openai",
            base_url="http://127.0.0.1:8080/v1",
            model="gpt-local",
            api_key="existing-key",
        )
    ])

    raw = config_from_settings_payload({
        "protocol": "openai",
        "name": "openai",
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "gpt-local",
        "api_key": "",
    }, current)

    assert raw["providers"][0]["api_key"] == "existing-key"


def test_settings_config_accepts_multiple_providers_and_preserves_secrets_by_name():
    current = AppConfig(providers=[
        ProviderConfig(
            name="openai",
            protocol="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="openai-key",
        ),
        ProviderConfig(
            name="anthropic",
            protocol="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-5",
            api_key="anthropic-key",
        ),
    ])

    raw = config_from_settings_payload({
        "providers": [
            {
                "name": "anthropic",
                "protocol": "anthropic",
                "base_url": "https://api.anthropic.com",
                "model": "claude-sonnet-4-5",
                "api_key": "",
            },
            {
                "name": "local",
                "protocol": "openai-compat",
                "base_url": "http://127.0.0.1:8080",
                "model": "gpt-local",
                "api_key": "local-key",
            },
        ],
    }, current)

    assert [provider["name"] for provider in raw["providers"]] == ["anthropic", "local"]
    assert raw["providers"][0]["api_key"] == "anthropic-key"
    assert raw["providers"][1]["api_key"] == "local-key"
    assert raw["providers"][1]["base_url"] == "http://127.0.0.1:8080/v1"


def test_settings_config_preserves_existing_api_key_when_provider_is_renamed():
    current = AppConfig(providers=[
        ProviderConfig(
            name="openai",
            protocol="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            api_key="openai-key",
        ),
    ])

    raw = config_from_settings_payload({
        "providers": [
            {
                "previous_name": "openai",
                "name": "official-openai",
                "protocol": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4.1",
                "api_key": "",
            },
        ],
    }, current)

    assert raw["providers"][0]["name"] == "official-openai"
    assert raw["providers"][0]["api_key"] == "openai-key"


def test_settings_config_rejects_duplicate_provider_names():
    with pytest.raises(ConfigError, match="Duplicate provider names"):
        config_from_settings_payload({
            "providers": [
                {
                    "name": "openai",
                    "protocol": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4.1",
                },
                {
                    "name": "openai",
                    "protocol": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5.1",
                },
            ],
        })


def test_memory_settings_endpoint_returns_provider_metadata(tmp_path):
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    config = AppConfig(
        providers=[provider],
        memory=MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="vector",
                    type="python",
                    module="custom.memory",
                    class_name="VectorMemory",
                    config={"secret": "not-returned", "top_k": 5},
                )
            ]
        ),
    )

    app = create_app(config, str(tmp_path))

    with TestClient(app) as client:
        data = client.get("/api/settings/memory").json()

    assert data["enabled"] is True
    assert data["providers"] == [
        {
            "name": "vector",
            "type": "python",
            "enabled": True,
            "module": "custom.memory",
            "class": "VectorMemory",
            "config": {"secret": "", "top_k": 5},
            "secret_fields": ["secret"],
        }
    ]


def test_root_route_is_not_a_frontend_shell(tmp_path):
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
    assert "/api/settings/qqbot" not in paths
    assert "/api/settings/telegrambot" not in paths


def test_cloud_bot_settings_routes_are_removed(tmp_path):
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


def test_memory_settings_save_updates_config_and_preserves_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(config_settings, "USER_CONFIG_FILE", tmp_path / "config.yaml")
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    config = AppConfig(
        providers=[provider],
        memory=MemoryConfig(
            providers=[
                MemoryProviderConfig(
                    name="vector",
                    type="python",
                    module="my_memory.provider",
                    class_name="VectorMemoryProvider",
                    config={
                        "api_key": "old-secret",
                        "top_k": 5,
                    },
                )
            ]
        ),
    )
    app = create_app(config, str(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/api/settings/memory",
            json={
                "enabled": True,
                "providers": [
                    {
                        "name": "vector",
                        "type": "python",
                        "module": "my_memory.provider",
                        "class": "VectorMemoryProvider",
                        "enabled": True,
                        "config": {
                            "api_key": "",
                            "top_k": 8,
                        },
                    }
                ],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["providers"][0]["config"]["api_key"] == ""
    assert data["providers"][0]["config"]["top_k"] == 8
    saved = load_config(tmp_path / "config.yaml")
    saved_provider = saved.memory.providers[0]
    assert saved_provider.config["api_key"] == "old-secret"
    assert saved_provider.config["top_k"] == 8


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
    server._agents[sid] = (agent, _FakeDeps(provider), object())
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
