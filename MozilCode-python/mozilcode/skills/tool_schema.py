from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

VALID_TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def is_valid_tool_name(name: object) -> bool:
    return isinstance(name, str) and VALID_TOOL_NAME_RE.fullmatch(name) is not None


def clean_tool_schema(
    item: dict[str, Any],
    path: Path,
    index: int,
) -> dict[str, Any] | None:
    tool_name = item.get("name")
    if not is_valid_tool_name(tool_name):
        log.warning(
            "Skipping tool schema #%d in %s: invalid or missing name",
            index,
            path,
        )
        return None

    description = item.get("description", "")
    if not isinstance(description, str):
        log.warning(
            "Skipping tool schema '%s' in %s: description must be a string",
            tool_name,
            path,
        )
        return None

    for schema_key in ("parameters", "input_schema"):
        schema_value = item.get(schema_key)
        if schema_value is not None and not isinstance(schema_value, dict):
            log.warning(
                "Skipping tool schema '%s' in %s: %s must be an object",
                tool_name,
                path,
                schema_key,
            )
            return None

    schema = dict(item)
    schema["name"] = tool_name
    schema["description"] = description
    return schema


def normalize_tool_schemas(raw: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        log.warning("tool.json at %s must be a JSON array or object", path)
        return []

    schemas: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            schema = clean_tool_schema(item, path, index)
            if schema is not None:
                tool_name = schema["name"]
                if tool_name in seen_names:
                    log.warning(
                        "Skipping duplicate tool schema '%s' in %s",
                        tool_name,
                        path,
                    )
                    continue
                seen_names.add(tool_name)
                schemas.append(schema)
        else:
            log.warning(
                "Skipping non-object tool schema #%d in %s",
                index,
                path,
            )
    return schemas
