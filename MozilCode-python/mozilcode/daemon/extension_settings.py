from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from mozilcode.skills.loader import SkillLoader
from mozilcode.skills.parser import VALID_NAME_RE

USER_SKILLS_DIR = Path.home() / ".mozilcode" / "skills"


def list_mcp_servers(settings: dict) -> list[dict]:
    servers = settings.get("mcp_servers", []) if isinstance(settings, dict) else []
    return list(servers) if isinstance(servers, list) else []


def upsert_mcp_server(settings: dict, body: dict) -> list[dict]:
    if not isinstance(body, dict):
        raise ValueError("JSON object is required")
    name = str(body.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    servers = [s for s in list_mcp_servers(settings) if s.get("name") != name]
    servers.append(
        {
            "name": name,
            "command": str(body.get("command") or "").strip(),
            "args": str(body.get("args") or "").strip(),
            "url": str(body.get("url") or "").strip(),
            "enabled": True,
        }
    )
    settings["mcp_servers"] = servers
    return servers


def delete_mcp_server(settings: dict, name: str) -> None:
    settings["mcp_servers"] = [
        s for s in list_mcp_servers(settings)
        if s.get("name") != name
    ]


def toggle_mcp_server(settings: dict, name: str) -> None:
    for server in list_mcp_servers(settings):
        if server.get("name") == name:
            server["enabled"] = not server.get("enabled", True)
    settings["mcp_servers"] = list_mcp_servers(settings)


def list_skills(work_dir: str, settings: dict) -> list[dict]:
    disabled = set(settings.get("disabled_skills", [])) if isinstance(settings, dict) else set()
    loader = SkillLoader(work_dir)
    out = [
        {
            "name": name,
            "description": getattr(skill, "description", "") or "",
            "source": loader.get_source_label(name),
            "enabled": name not in disabled,
        }
        for name, skill in loader.load_all().items()
    ]
    out.sort(key=lambda item: item["name"])
    return out


def toggle_skill(settings: dict, name: str) -> None:
    disabled = set(settings.get("disabled_skills", []))
    if name in disabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    settings["disabled_skills"] = sorted(disabled)


def _validate_skill_payload(body: dict) -> tuple[str, str, str]:
    if not isinstance(body, dict):
        raise ValueError("JSON object is required")
    name = str(body.get("name") or "").strip()
    description = str(body.get("description") or "").strip()
    prompt_body = str(body.get("body") or "")
    if not VALID_NAME_RE.match(name):
        raise ValueError(
            "skill name must be lowercase letters, digits, and hyphens, "
            "starting with a letter"
        )
    if not description:
        raise ValueError("description is required")
    return name, description, prompt_body


def create_skill_from_payload(body: dict) -> Path:
    name, description, prompt_body = _validate_skill_payload(body)
    skill_dir = USER_SKILLS_DIR / name
    if skill_dir.exists():
        raise ValueError("skill already exists")

    front = yaml.safe_dump(
        {"name": name, "description": description},
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    content = f"---\n{front}\n---\n\n{prompt_body.strip()}\n"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def delete_user_skill(name: str) -> None:
    if not VALID_NAME_RE.match(name):
        raise ValueError("invalid skill name")
    skill_dir = USER_SKILLS_DIR / name
    if not skill_dir.is_dir():
        raise ValueError("only user-created skills can be deleted")
    shutil.rmtree(skill_dir, ignore_errors=True)
