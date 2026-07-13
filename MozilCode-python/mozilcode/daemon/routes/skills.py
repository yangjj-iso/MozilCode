"""Routes for skills management — list, create, toggle, and delete."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.request_body import (
    BodyFieldError,
    parse_json_object,
    required_string_field,
    string_field,
)
from mozilcode.daemon.request_context import daemon_server, path_param
from mozilcode.daemon.responses import bad_request_response, not_found_response

USER_SKILLS_DIR = Path.home() / ".mozilcode" / "skills"
VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9\-]*$")


@dataclass(frozen=True)
class CreateSkillBody:
    name: str
    description: str
    body: str


def _parse_create_skill_body(payload: dict[str, Any]) -> CreateSkillBody:
    name = required_string_field(payload, "name")
    if not VALID_NAME_RE.match(name):
        raise BodyFieldError(
            f"Invalid skill name '{name}': must be lowercase letters, digits, and hyphens, "
            "starting with a letter"
        )
    description = required_string_field(payload, "description")
    body = string_field(payload, "body")
    return CreateSkillBody(name=name, description=description, body=body)


def _skill_to_dict(skill: Any, source_label: str) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "enabled": not _is_disabled(skill),
        "source": source_label,
        "mode": skill.mode,
        "context": skill.context,
        "model": skill.model or "",
    }


def _is_disabled(skill: Any) -> bool:
    if skill.source_path is None:
        return False
    return skill.source_path.suffix == ".disabled" or (
        skill.is_directory and (skill.source_path.parent / ".disabled").exists()
    )


def _find_skill_file(name: str) -> Path | None:
    """Find a user-level or project-level skill file by name."""
    for base in (USER_SKILLS_DIR,):
        # File-based skill
        md_file = base / f"{name}.md"
        if md_file.exists():
            return md_file
        md_disabled = base / f"{name}.md.disabled"
        if md_disabled.exists():
            return md_disabled
        # Directory-based skill
        dir_path = base / name
        skill_md = dir_path / "SKILL.md"
        if skill_md.exists():
            return skill_md
        skill_md_disabled = dir_path / "SKILL.md.disabled"
        if skill_md_disabled.exists():
            return skill_md_disabled
    return None


async def list_skills(request: Request) -> JSONResponse:
    server = daemon_server(request)
    from mozilcode.skills.loader import SkillLoader

    loader = SkillLoader(server.work_dir)
    skills = loader.load_all()
    result = []
    for name, skill in skills.items():
        source_label = loader.get_source_label(name)
        result.append(_skill_to_dict(skill, source_label))
    return JSONResponse({"skills": result})


async def create_skill(request: Request) -> JSONResponse:
    parsed = await parse_json_object(request, _parse_create_skill_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()

    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skill_file = USER_SKILLS_DIR / f"{body.name}.md"
    if skill_file.exists():
        return bad_request_response(f"Skill '{body.name}' already exists")

    content = f"---\nname: {body.name}\ndescription: {body.description}\n---\n{body.body}\n"
    skill_file.write_text(content, encoding="utf-8")
    return JSONResponse({"name": body.name, "description": body.description, "created": True})


async def toggle_skill(request: Request) -> JSONResponse:
    name = path_param(request, "name")
    skill_path = _find_skill_file(name)
    if skill_path is None:
        return not_found_response(f"Skill '{name}' not found")

    if skill_path.suffix == ".disabled":
        # Enable: remove .disabled suffix
        enabled_path = skill_path.with_suffix("")
        skill_path.rename(enabled_path)
        enabled = True
    elif skill_path.name == "SKILL.md.disabled":
        # Enable directory-based skill
        enabled_path = skill_path.parent / "SKILL.md"
        skill_path.rename(enabled_path)
        enabled = True
    else:
        # Disable: add .disabled suffix
        disabled_path = Path(str(skill_path) + ".disabled")
        skill_path.rename(disabled_path)
        enabled = False

    return JSONResponse({"name": name, "enabled": enabled})


async def delete_skill(request: Request) -> JSONResponse:
    name = path_param(request, "name")
    skill_path = _find_skill_file(name)
    if skill_path is None:
        return not_found_response(f"Skill '{name}' not found")

    # Only allow deleting user-level skills
    try:
        skill_path.relative_to(USER_SKILLS_DIR)
    except ValueError:
        return bad_request_response("Cannot delete built-in or project-level skills")

    if skill_path.is_file():
        skill_path.unlink()
    elif skill_path.is_dir():
        import shutil
        shutil.rmtree(skill_path)

    return JSONResponse({"name": name, "deleted": True})
