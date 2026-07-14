"""Daemon Provider 配置读写管理测试。"""

from __future__ import annotations

import yaml
from starlette.testclient import TestClient

from mozilcode import config as config_package
from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.routes import config as config_routes
from mozilcode.daemon.server import create_app
from mozilcode.daemon.session.store import SessionStore


def _provider(api_key: str) -> ProviderConfig:
    return ProviderConfig(
        name="local",
        protocol="openai-compat",
        base_url="http://127.0.0.1:9999/v1",
        model="test-model",
        api_key=api_key,
    )


def _payload(*, clear_api_key: bool = False) -> dict:
    return {
        "providers": [
            {
                "name": "local",
                "protocol": "openai-compat",
                "base_url": "http://127.0.0.1:9999/v1",
                "model": "updated-model",
                "api_key": "",
                "clear_api_key": clear_api_key,
                "thinking": False,
                "context_window": 0,
                "max_output_tokens": 0,
            }
        ],
        "permission_mode": "default",
    }


def _prepare(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "providers": [
                    {
                        "name": "local",
                        "protocol": "openai-compat",
                        "base_url": "http://127.0.0.1:9999/v1",
                        "model": "test-model",
                        "api_key": "existing-secret",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_routes, "USER_CONFIG_FILE", config_file)

    def fake_load_config():
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        provider = raw["providers"][0]
        return AppConfig(
            providers=[
                ProviderConfig(
                    name=provider["name"],
                    protocol=provider["protocol"],
                    base_url=provider["base_url"],
                    model=provider["model"],
                    api_key=provider.get("api_key", ""),
                )
            ]
        )

    monkeypatch.setattr(config_package, "load_config", fake_load_config)
    app = create_app(
        AppConfig(providers=[_provider("existing-secret")]),
        str(tmp_path),
        session_store=SessionStore(tmp_path / "sessions"),
    )
    return app, config_file


def test_save_config_preserves_masked_api_key(tmp_path, monkeypatch) -> None:
    app, config_file = _prepare(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post("/api/config", json=_payload())

    assert response.status_code == 200
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert raw["providers"][0]["api_key"] == "existing-secret"
    assert raw["providers"][0]["model"] == "updated-model"


def test_save_config_can_explicitly_clear_api_key(tmp_path, monkeypatch) -> None:
    app, config_file = _prepare(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/config",
            json=_payload(clear_api_key=True),
        )

    assert response.status_code == 200
    raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    assert raw["providers"][0]["api_key"] == ""
