"""Agent 定义文件解析。

解析 frontmatter 与校验字段，产出 AgentDef。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from mozilcode.frontmatter import FrontmatterParseError, parse_yaml_frontmatter

log = logging.getLogger(__name__)

VALID_MODELS = {"inherit", "sonnet", "opus", "haiku", ""}
VALID_PERMISSION_MODES = {"default", "acceptEdits", "dontAsk", ""}


class AgentParseError(Exception):
    pass


VALID_ISOLATION_MODES = {"", "worktree"}


@dataclass
class AgentDef:
    agent_type: str
    when_to_use: str
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: str = "inherit"
    max_turns: int = 50
    permission_mode: str = "default"
    background: bool = False
    isolation: str = ""
    file_path: Path | None = None
    source: str = "builtin"


def _required_string(meta: dict, field_name: str, ctx: str) -> str:
    if field_name not in meta:
        raise AgentParseError(f"Missing required field '{field_name}'{ctx}")
    value = meta[field_name]
    if not isinstance(value, str) or not value.strip():
        raise AgentParseError(f"Field '{field_name}'{ctx} must be a non-empty string")
    return value.strip()


def _optional_string_choice(
    meta: dict,
    field_name: str,
    default: str,
    valid_values: set[str],
    ctx: str,
) -> str:
    value = meta.get(field_name, default)
    if not isinstance(value, str):
        raise AgentParseError(f"Field '{field_name}'{ctx} must be a string")
    value = value.strip()
    if value not in valid_values:
        allowed = valid_values - {""}
        raise AgentParseError(
            f"Invalid {field_name} '{value}'{ctx}: must be one of {allowed}"
        )
    return value


def _optional_string_list(
    meta: dict,
    field_name: str,
    ctx: str,
) -> list[str]:
    value = meta.get(field_name, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AgentParseError(f"Field '{field_name}'{ctx} must be a list of strings")
    return value


def _optional_positive_int(meta: dict, field_name: str, default: int, ctx: str) -> int:
    value = meta.get(field_name, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AgentParseError(
            f"Invalid {field_name} '{value}'{ctx}: must be a positive integer"
        )
    return value


def _optional_bool(meta: dict, field_name: str, default: bool, ctx: str) -> bool:
    value = meta.get(field_name, default)
    if not isinstance(value, bool):
        raise AgentParseError(f"Field '{field_name}'{ctx} must be a boolean")
    return value


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    try:
        return parse_yaml_frontmatter(raw)
    except FrontmatterParseError as e:
        raise AgentParseError(str(e)) from e


def _validate_agent_meta(meta: dict, source: str = "") -> None:
    ctx = f" in {source}" if source else ""

    _required_string(meta, "name", ctx)
    _required_string(meta, "description", ctx)
    _optional_string_choice(meta, "model", "inherit", VALID_MODELS, ctx)
    _optional_string_choice(
        meta,
        "permissionMode",
        "default",
        VALID_PERMISSION_MODES,
        ctx,
    )
    _optional_positive_int(meta, "maxTurns", 50, ctx)
    _optional_string_choice(meta, "isolation", "", VALID_ISOLATION_MODES, ctx)
    _optional_bool(meta, "background", False, ctx)
    _optional_string_list(meta, "tools", ctx)
    _optional_string_list(meta, "disallowedTools", ctx)


def build_agent_def(
    meta: dict,
    body: str,
    *,
    file_path: Path | None = None,
    source: str = "builtin",
) -> AgentDef:
    _validate_agent_meta(meta, str(file_path) if file_path is not None else "")
    return AgentDef(
        agent_type=_required_string(meta, "name", ""),
        when_to_use=_required_string(meta, "description", ""),
        system_prompt=body,
        tools=_optional_string_list(meta, "tools", ""),
        disallowed_tools=_optional_string_list(meta, "disallowedTools", ""),
        model=_optional_string_choice(meta, "model", "inherit", VALID_MODELS, ""),
        max_turns=_optional_positive_int(meta, "maxTurns", 50, ""),
        permission_mode=_optional_string_choice(
            meta,
            "permissionMode",
            "default",
            VALID_PERMISSION_MODES,
            "",
        ),
        background=_optional_bool(meta, "background", False, ""),
        isolation=_optional_string_choice(
            meta,
            "isolation",
            "",
            VALID_ISOLATION_MODES,
            "",
        ),
        file_path=file_path,
        source=source,
    )


def parse_agent_file(path: Path) -> AgentDef:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise AgentParseError(f"Cannot read agent file {path}: {e}") from e

    meta, body = parse_frontmatter(raw)
    return build_agent_def(meta, body, file_path=path, source="builtin")
