"""技能文件解析（frontmatter + 参数替换）。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from mozilcode.frontmatter import FrontmatterParseError, parse_yaml_frontmatter

log = logging.getLogger(__name__)

VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9\-]*$")
VALID_MODES = {"inline", "fork"}
VALID_CONTEXTS = {"full", "recent", "none"}


class SkillParseError(Exception):
    pass


@dataclass
class SkillDef:
    name: str
    description: str
    prompt_body: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    mode: Literal["inline", "fork"] = "inline"
    model: str | None = None
    context: Literal["full", "recent", "none"] = "full"
    source_path: Path | None = None
    is_directory: bool = False


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    try:
        return parse_yaml_frontmatter(raw)
    except FrontmatterParseError as e:
        raise SkillParseError(str(e)) from e


def _source_context(source: str = "") -> str:
    return f" in {source}" if source else ""


def _required_string(meta: dict, field_name: str, ctx: str) -> str:
    if field_name not in meta:
        raise SkillParseError(f"Missing required field '{field_name}'{ctx}")
    value = meta[field_name]
    if not isinstance(value, str) or not value.strip():
        raise SkillParseError(f"Field '{field_name}'{ctx} must be a non-empty string")
    return value.strip()


def _optional_string(meta: dict, field_name: str, ctx: str) -> str | None:
    value = meta.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SkillParseError(f"Field '{field_name}'{ctx} must be a string")
    value = value.strip()
    return value or None


def _optional_string_list(meta: dict, field_name: str, ctx: str) -> list[str]:
    value = meta.get(field_name, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise SkillParseError(f"Field '{field_name}'{ctx} must be a list of strings")

    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SkillParseError(
                f"Field '{field_name}'{ctx} must be a list of non-empty strings"
            )
        cleaned.append(item.strip())
    return cleaned


def _optional_choice(
    meta: dict,
    field_name: str,
    default: str,
    valid_values: set[str],
    ctx: str,
) -> str:
    value = meta.get(field_name, default)
    if not isinstance(value, str):
        raise SkillParseError(f"Field '{field_name}'{ctx} must be a string")
    value = value.strip()
    if value not in valid_values:
        raise SkillParseError(
            f"Invalid {field_name} '{value}'{ctx}: must be one of {valid_values}"
        )
    return value


def _validate_meta(meta: dict, source: str = "") -> None:
    ctx = _source_context(source)

    name = _required_string(meta, "name", ctx)
    _required_string(meta, "description", ctx)
    if not VALID_NAME_RE.match(name):
        raise SkillParseError(
            f"Invalid skill name '{name}'{ctx}: "
            "must be lowercase letters, digits, and hyphens, starting with a letter"
        )

    _optional_choice(meta, "mode", "inline", VALID_MODES, ctx)
    _optional_choice(meta, "context", "full", VALID_CONTEXTS, ctx)
    _optional_string(meta, "model", ctx)
    _optional_string_list(meta, "allowedTools", ctx)


def build_skill_def(
    meta: dict,
    body: str,
    *,
    source: str = "",
    source_path: Path | None = None,
    is_directory: bool = False,
) -> SkillDef:
    _validate_meta(meta, source)
    ctx = _source_context(source)
    mode = _optional_choice(meta, "mode", "inline", VALID_MODES, ctx)
    context = _optional_choice(meta, "context", "full", VALID_CONTEXTS, ctx)
    return SkillDef(
        name=_required_string(meta, "name", ctx),
        description=_required_string(meta, "description", ctx),
        prompt_body=body,
        allowed_tools=_optional_string_list(meta, "allowedTools", ctx),
        mode=cast(Literal["inline", "fork"], mode),
        model=_optional_string(meta, "model", ctx),
        context=cast(Literal["full", "recent", "none"], context),
        source_path=source_path,
        is_directory=is_directory,
    )


def parse_skill_file(path: Path) -> SkillDef:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SkillParseError(f"Cannot read skill file {path}: {e}") from e

    meta, body = parse_frontmatter(raw)
    return build_skill_def(
        meta,
        body,
        source=str(path),
        source_path=path,
    )


def substitute_arguments(prompt_body: str, args: str) -> str:
    return prompt_body.replace("$ARGUMENTS", args)
