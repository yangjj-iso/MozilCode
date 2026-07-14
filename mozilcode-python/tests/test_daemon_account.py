"""Daemon 账号路由测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from mozilcode.account.client import CatalogModel
from mozilcode.account.session import AccountSession
from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.daemon.server import create_app


def _app(tmp_path: Path, config: AppConfig | None = None):
    return create_app(
        config
        or AppConfig(
            providers=[
                ProviderConfig(
                    name="local",
                    protocol="openai",
                    base_url="http://127.0.0.1:9/v1",
                    model="local",
                )
            ]
        ),
        str(tmp_path),
    )


def test_account_status_unsigned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_file = tmp_path / "account.yaml"
    monkeypatch.setattr("mozilcode.account.session.SESSION_FILE", session_file)

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/account")

    assert response.status_code == 200
    data = response.json()
    assert data["logged_in"] is False


def test_account_sign_in_models_and_select(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_file = tmp_path / "account.yaml"
    monkeypatch.setattr("mozilcode.account.session.SESSION_FILE", session_file)

    def fake_login(**kwargs):
        return AccountSession(
            base_url="http://127.0.0.1:8000",
            token="jwt-xyz",
            email=kwargs["email"],
            role="user",
            user_id=3,
        )

    models = [
        CatalogModel(name="gpt-a", display_name="A"),
        CatalogModel(name="gpt-b", display_name="B"),
    ]

    with (
        patch("mozilcode.account.service.cloud_login", side_effect=fake_login),
        patch("mozilcode.account.service.fetch_models", return_value=models),
        TestClient(_app(tmp_path)) as client,
    ):
        signed = client.post(
            "/api/account/session",
            json={
                "email": "user@example.com",
                "password": "secret12",
                "base_url": "http://127.0.0.1:8000",
            },
        )
        assert signed.status_code == 200, signed.text
        body = signed.json()
        assert body["logged_in"] is True
        assert body["email"] == "user@example.com"
        assert any(p["name"].startswith("account:") for p in body.get("providers", []))

        catalog = client.get("/api/account/models")
        assert catalog.status_code == 200
        names = [m["name"] for m in catalog.json()["models"]]
        assert names == ["gpt-a", "gpt-b"]

        selected = client.post("/api/account/model", json={"model": "gpt-b"})
        assert selected.status_code == 200
        assert selected.json()["selected_model"] == "gpt-b"

        signed_out = client.delete("/api/account/session")
        assert signed_out.status_code == 200
        assert signed_out.json()["logged_in"] is False


def test_save_config_strips_account_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_file = tmp_path / "account.yaml"
    monkeypatch.setattr("mozilcode.account.session.SESSION_FILE", session_file)
    cfg = tmp_path / "config.yaml"
    monkeypatch.setattr("mozilcode.daemon.routes.config.USER_CONFIG_FILE", cfg)

    with (
        patch("mozilcode.account.service.load_account_providers", return_value=[]),
        TestClient(_app(tmp_path)) as client,
    ):
        response = client.post(
            "/api/config",
            json={
                "permission_mode": "default",
                "providers": [
                    {
                        "name": "account:gpt",
                        "protocol": "openai-compat",
                        "base_url": "http://x/api/gateway",
                        "model": "gpt",
                        "api_key": "should-not-persist",
                    },
                    {
                        "name": "local",
                        "protocol": "openai",
                        "base_url": "http://127.0.0.1:9/v1",
                        "model": "local-model",
                        "api_key": "k",
                    },
                ],
            },
        )
    assert response.status_code == 200, response.text
    text = cfg.read_text(encoding="utf-8")
    assert "account:gpt" not in text
    assert "should-not-persist" not in text
    assert "local-model" in text