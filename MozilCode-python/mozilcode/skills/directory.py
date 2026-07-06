from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import Tool, ToolResult

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


def parse_tool_json(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Failed to parse tool.json at %s: %s", path, e)
        return []

    return normalize_tool_schemas(raw, path)


def load_tool_implementation(
    references_dir: Path, tool_name: str
) -> Callable[..., Any] | None:
    if not is_valid_tool_name(tool_name):
        log.warning(
            "Refusing to load implementation for invalid tool name '%s'",
            tool_name,
        )
        return None

    script = references_dir / f"{tool_name}.py"
    if not script.is_file():
        return None

    module_name = f"mozilcode_skill_tool_{tool_name}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        log.warning("Cannot create module spec for %s", script)
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        log.warning("Failed to load tool implementation %s: %s", script, e)
        return None

    execute_fn = getattr(module, "execute", None)
    if execute_fn is None:
        log.warning("Tool implementation %s has no 'execute' function", script)
        return None

    return execute_fn


class _DynamicParams(BaseModel):
    model_config = {"extra": "allow"}


class SkillCustomTool(Tool):
    def __init__(
        self,
        tool_name: str,
        description: str,
        schema: dict[str, Any],
        impl: Callable[..., Any] | None,
    ) -> None:
        self.name = tool_name
        self.description = description
        self.params_model = _DynamicParams
        self.category = "command"
        self.is_concurrency_safe = False
        self._schema = schema
        self._impl = impl

    def get_schema(self) -> dict[str, Any]:
        input_schema = self._schema.get("parameters", self._schema.get("input_schema", {}))
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": input_schema,
        }

    async def execute(self, params: BaseModel) -> ToolResult:
        if self._impl is None:
            return ToolResult(
                output=f"Error: no implementation found for tool '{self.name}'",
                is_error=True,
            )
        try:
            kwargs = params.model_dump()
            if asyncio.iscoroutinefunction(self._impl):
                result = await self._impl(**kwargs)
            else:
                result = self._impl(**kwargs)
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(output=f"Tool execution error: {e}", is_error=True)


def register_skill_tools(skill_dir: Path, registry: ToolRegistry) -> int:
    tool_json_path = skill_dir / "tool.json"
    if not tool_json_path.is_file():
        return 0

    schemas = parse_tool_json(tool_json_path)
    references_dir = skill_dir / "references"
    count = 0

    for schema in schemas:
        tool_name = schema["name"]

        if registry.get(tool_name) is not None:
            log.debug("Tool '%s' already registered, skipping", tool_name)
            continue

        description = schema["description"]
        impl = load_tool_implementation(references_dir, tool_name) if references_dir.is_dir() else None

        if impl is None:
            log.warning("No implementation for tool '%s' in %s", tool_name, references_dir)

        tool = SkillCustomTool(tool_name, description, schema, impl)
        registry.register(tool)
        count += 1

    return count
