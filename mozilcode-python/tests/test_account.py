"""账号会话与 provider 合成测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from mozilcode.account.client import CatalogModel
from mozilcode.account.providers import (
    account_provider_name,
    build_account_providers,
    is_account_provider_name,
    merge_account_providers,
)
from mozilcode.account.service import (
    filter_local_providers,
    get_status,
    load_account_providers,
    select_model,
    sign_in,
    sign_out,
)
from mozilcode.account.session import AccountSession, load_session, save_session
from mozilcode.config import ProviderConfig


def test_session_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "account.yaml"
    session = AccountSession(
        base_url="http://127.0.0.1:8000",
        token="tok-1",
        email="u@example.com",
        role="user",
        user_id=7,
        selected_model="gpt-cloud",
    )
    save_session(session, path)
    loaded = load_session(path)
    assert loaded is not None
    assert loaded.token == "tok-1"
    assert loaded.email == "u@example.com"
    assert loaded.selected_model == "gpt-cloud"
    assert loaded.gateway_base_url() == "http://127.0.0.1:8000/api/gateway"


def test_build_account_providers_prefers_selected() -> None:
    session = AccountSession(
        base_url="http://cloud.test",
        token="jwt",
        selected_model="b",
    )
    models = [
        CatalogModel(name="a", display_name="A"),
        CatalogModel(name="b", display_name="B"),
    ]
    providers = build_account_providers(session, models)
    assert [p.model for p in providers] == ["b", "a"]
    assert providers[0].name == account_provider_name("b")
    assert providers[0].protocol == "openai-compat"
    assert providers[0].api_key == "jwt"
    assert providers[0].base_url.endswith("/api/gateway")


def test_merge_account_providers_override_same_name() -> None:
    account = [
        ProviderConfig(
            name="account:x",
            protocol="openai-compat",
            base_url="http://cloud/api/gateway",
            model="x",
            api_key="jwt",
        )
    ]
    local = [
        ProviderConfig(
            name="local",
            protocol="openai",
            base_url="http://local",
            model="y",
        ),
        ProviderConfig(
            name="account:x",
            protocol="openai",
            base_url="http://stale",
            model="stale",
        ),
    ]
    merged = merge_account_providers(account, local)
    # Local providers first; stale local account:x dropped (account version wins)
    assert [p.name for p in merged] == ["local", "account:x"]
    assert merged[0].name == "local"
    assert merged[1].api_key == "jwt"  # account version, not stale


def test_filter_local_providers_drops_account() -> None:
    raw = [
        {"name": "openai", "protocol": "openai"},
        {"name": "account:gpt", "protocol": "openai-compat"},
        {"name": "other", "managed": "account"},
    ]
    filtered = filter_local_providers(raw)
    assert [p["name"] for p in filtered] == ["openai"]
    assert is_account_provider_name("account:gpt")


def test_sign_in_and_select_model(tmp_path: Path) -> None:
    path = tmp_path / "account.yaml"

    def fake_login(**kwargs):
        return AccountSession(
            base_url="http://127.0.0.1:8000",
            token="jwt-token",
            email=kwargs["email"],
            role="user",
            user_id=1,
        )

    def fake_models(session):
        return [
            CatalogModel(name="gpt-a", display_name="A"),
            CatalogModel(name="gpt-b", display_name="B"),
        ]

    with (
        patch("mozilcode.account.service.cloud_login", side_effect=fake_login),
        patch("mozilcode.account.service.fetch_models", side_effect=fake_models),
    ):
        session = sign_in(
            email="a@b.com",
            password="secret",
            base_url="http://127.0.0.1:8000",
            path=path,
        )
        assert session.email == "a@b.com"
        assert get_status(path).logged_in is True
        selected = select_model("gpt-b", path=path)
        assert selected.selected_model == "gpt-b"
        providers = load_account_providers(path)
        assert providers[0].model == "gpt-b"
        sign_out(path)
        assert get_status(path).logged_in is False


def test_load_config_injects_account_providers(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    session_file = home / ".mozilcode" / "account.yaml"
    session_file.parent.mkdir(parents=True)
    (home / ".mozilcode" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "providers": [
                    {
                        "name": "local",
                        "protocol": "openai",
                        "base_url": "http://127.0.0.1:9/v1",
                        "model": "local-model",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    save_session(
        AccountSession(
            base_url="http://127.0.0.1:8000",
            token="jwt",
            email="u@x.com",
            selected_model="cloud-m",
        ),
        session_file,
    )

    monkeypatch.setattr("mozilcode.account.session.SESSION_FILE", session_file)
    monkeypatch.setattr("mozilcode.config.core.Path.home", lambda: home)
    monkeypatch.setattr("mozilcode.config.core.Path.cwd", lambda: cwd)

    with patch(
        "mozilcode.account.service.fetch_models",
        return_value=[CatalogModel(name="cloud-m", display_name="Cloud")],
    ):
        from mozilcode.config import load_config

        config = load_config()
    # Local providers take priority (index 0); account providers appended after
    assert config.providers[0].name == "local"
    assert config.providers[0].api_key == ""  # local, no JWT
    assert any(p.name == "account:cloud-m" for p in config.providers)
    assert any(p.api_key == "jwt" for p in config.providers)