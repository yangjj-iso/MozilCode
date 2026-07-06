from __future__ import annotations

import pytest

from mozilcode.daemon import extension_settings
from mozilcode.daemon.extension_settings import create_skill_from_payload
from mozilcode.daemon.extension_settings import delete_user_skill
from mozilcode.daemon.extension_settings import list_mcp_servers
from mozilcode.daemon.extension_settings import toggle_mcp_server
from mozilcode.daemon.extension_settings import toggle_skill
from mozilcode.daemon.extension_settings import upsert_mcp_server


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
