from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mozilcode.daemon import extension_settings
from mozilcode.daemon import settings as daemon_settings
from mozilcode.daemon.extension_settings import create_skill_from_payload
from mozilcode.daemon.extension_settings import delete_user_skill
from mozilcode.daemon.extension_settings import list_mcp_servers
from mozilcode.daemon.extension_settings import toggle_mcp_server
from mozilcode.daemon.extension_settings import toggle_skill
from mozilcode.daemon.extension_settings import upsert_mcp_server
from mozilcode.daemon.server import create_app
from mozilcode.config import AppConfig, ProviderConfig


def test_mcp_server_upsert_replaces_existing_and_trims_fields():
    settings = {
        "mcp_servers": [
            {"name": "local", "command": "old", "args": "", "url": "", "enabled": False},
            {"name": "remote", "command": "", "args": "", "url": "https://example.test", "enabled": True},
        ]
    }

    servers = upsert_mcp_server(
        settings,
        {
            "name": " local ",
            "command": " python ",
            "args": " -m server ",
            "url": " ",
        },
    )

    assert servers == [
        {"name": "remote", "command": "", "args": "", "url": "https://example.test", "enabled": True},
        {"name": "local", "command": "python", "args": "-m server", "url": "", "enabled": True},
    ]
    assert list_mcp_servers(settings) == servers


def test_mcp_server_toggle_updates_matching_server_only():
    settings = {
        "mcp_servers": [
            {"name": "a", "enabled": True},
            {"name": "b", "enabled": False},
        ]
    }

    toggle_mcp_server(settings, "b")

    assert settings["mcp_servers"] == [
        {"name": "a", "enabled": True},
        {"name": "b", "enabled": True},
    ]


def test_skill_toggle_keeps_disabled_skill_names_sorted():
    settings = {"disabled_skills": ["zeta"]}

    toggle_skill(settings, "alpha")

    assert settings["disabled_skills"] == ["alpha", "zeta"]

    toggle_skill(settings, "zeta")

    assert settings["disabled_skills"] == ["alpha"]


def test_create_and_delete_user_skill_uses_configured_user_skill_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(extension_settings, "USER_SKILLS_DIR", tmp_path)

    skill_dir = create_skill_from_payload(
        {
            "name": "review-helper",
            "description": "Review project changes",
            "body": "Check tests before summarizing.",
        }
    )

    skill_md = skill_dir / "SKILL.md"
    assert skill_md.is_file()
    assert "name: review-helper" in skill_md.read_text(encoding="utf-8")

    delete_user_skill("review-helper")

    assert not skill_dir.exists()


def test_delete_user_skill_rejects_invalid_name(tmp_path, monkeypatch):
    monkeypatch.setattr(extension_settings, "USER_SKILLS_DIR", tmp_path)

    with pytest.raises(ValueError, match="invalid skill name"):
        delete_user_skill("..")


def test_management_routes_update_mcp_and_user_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_settings, "DAEMON_SETTINGS_FILE", tmp_path / "daemon_settings.json")
    monkeypatch.setattr(extension_settings, "USER_SKILLS_DIR", tmp_path / "skills")
    provider = ProviderConfig(
        name="openai",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        model="gpt-local",
    )
    app = create_app(AppConfig(providers=[provider]), str(tmp_path))

    with TestClient(app) as client:
        added = client.post(
            "/api/settings/mcp",
            json={"name": "local", "command": "python", "args": "-m demo"},
        )
        listed = client.get("/api/settings/mcp")
        created = client.post(
            "/api/skills",
            json={
                "name": "route-skill",
                "description": "Route-created skill",
                "body": "Use route handlers.",
            },
        )
        deleted = client.delete("/api/skills/route-skill")

    assert added.status_code == 200
    assert listed.json()["servers"][0]["name"] == "local"
    assert created.status_code == 200
    assert deleted.status_code == 200
    assert not (tmp_path / "skills" / "route-skill").exists()
