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
from mozilcode.daemon.settings import normalize_daemon_settings
from mozilcode.daemon.settings import public_qqbot_status
from mozilcode.daemon.settings import public_telegrambot_status
from mozilcode.daemon.settings import qqbot_settings_from_payload
from mozilcode.daemon.settings import resolve_qqbot_config
from mozilcode.daemon.settings import resolve_telegrambot_config
from mozilcode.daemon.settings import telegrambot_settings_from_payload
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
    first["qqbot"]["enabled"] = True

    second = normalize_daemon_settings({})

    assert second["mcp_servers"] == []
    assert second["qqbot"] == {}


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


def test_qqbot_public_status_uses_env_fallback_and_masks_secret(monkeypatch):
    monkeypatch.setenv("MOZILCODE_QQ_OFFICIAL_ENABLED", "true")
    monkeypatch.setenv("MOZILCODE_QQ_OFFICIAL_APP_ID", "1234567890")
    monkeypatch.setenv("MOZILCODE_QQ_OFFICIAL_APP_SECRET", "secret-value")
    monkeypatch.setenv("MOZILCODE_QQ_COMMAND_PREFIX", "/mew")

    status = public_qqbot_status(settings={"qqbot": {}})

    assert status["enabled"] is True
    assert status["configured"] is True
    assert status["app_id"] == "1234567890"
    assert status["app_secret_set"] is True
    assert "app_secret" not in status


def test_qqbot_saved_disabled_overrides_env_enabled(monkeypatch):
    monkeypatch.setenv("MOZILCODE_QQ_OFFICIAL_ENABLED", "true")
    monkeypatch.setenv("MOZILCODE_QQ_OFFICIAL_APP_ID", "1234567890")
    monkeypatch.setenv("MOZILCODE_QQ_OFFICIAL_APP_SECRET", "secret-value")

    enabled, cfg, _settings = resolve_qqbot_config({"qqbot": {"enabled": False}})

    assert enabled is False
    assert cfg.is_configured() is True


def test_qqbot_payload_preserves_existing_secret_when_blank():
    settings = qqbot_settings_from_payload(
        {
            "enabled": True,
            "app_id": "1234567890",
            "app_secret": "",
            "command_prefix": "/mc",
            "allowed_users": "u2, u1",
            "allowed_groups": "g1\ng2",
        },
        {"app_secret": "old-secret"},
    )

    assert settings["app_secret"] == "old-secret"
    assert settings["allowed_users"] == "u1\nu2"
    assert settings["allowed_groups"] == "g1\ng2"


def test_telegrambot_public_status_uses_env_fallback_and_masks_token(monkeypatch):
    monkeypatch.setenv("MOZILCODE_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("MOZILCODE_TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("MOZILCODE_TELEGRAM_COMMAND_PREFIX", "/mew")

    status = public_telegrambot_status(settings={"telegrambot": {}})

    assert status["enabled"] is True
    assert status["configured"] is True
    assert status["bot_token_set"] is True
    assert "bot_token" not in status


def test_telegrambot_saved_disabled_overrides_env_enabled(monkeypatch):
    monkeypatch.setenv("MOZILCODE_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("MOZILCODE_TELEGRAM_BOT_TOKEN", "test-token")

    enabled, cfg, _settings = resolve_telegrambot_config({"telegrambot": {"enabled": False}})

    assert enabled is False
    assert cfg.is_configured() is True


def test_telegrambot_payload_preserves_existing_token_when_blank():
    settings = telegrambot_settings_from_payload(
        {
            "enabled": True,
            "bot_token": "",
            "command_prefix": "/mc",
            "allowed_users": "42, 7",
            "allowed_chats": "-100\n-200",
        },
        {"bot_token": "old-token"},
    )

    assert settings["bot_token"] == "old-token"
    assert settings["allowed_users"] == "42\n7"
    assert settings["allowed_chats"] == "-100\n-200"


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


def test_bot_status_routes_are_available(tmp_path):
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

    assert qq.status_code == 200
    assert qq.json()["provider"] == "official"
    assert telegram.status_code == 200
    assert telegram.json()["provider"] == "telegram-official"


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
                    name="tencentdb",
                    type="builtin.tencentdb",
                    config={
                        "base_url": "http://127.0.0.1:8420",
                        "api_key": "old-secret",
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
                        "name": "tencentdb",
                        "type": "builtin.tencentdb",
                        "enabled": True,
                        "config": {
                            "base_url": "http://127.0.0.1:8421",
                            "api_key": "",
                        },
                    }
                ],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["providers"][0]["config"]["api_key"] == ""
    assert data["providers"][0]["config"]["base_url"] == "http://127.0.0.1:8421"
    saved = load_config(tmp_path / "config.yaml")
    saved_provider = saved.memory.providers[0]
    assert saved_provider.config["api_key"] == "old-secret"
    assert saved_provider.config["base_url"] == "http://127.0.0.1:8421"


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
