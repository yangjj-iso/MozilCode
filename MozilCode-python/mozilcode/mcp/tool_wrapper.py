from __future__ import annotations

import hashlib
import re
from typing import Any

from mcp import types as mcp_types
from pydantic import BaseModel, create_model

from mozilcode.mcp.client import MCPClient
from mozilcode.tools.base import Tool, ToolResult

MAX_PUBLIC_TOOL_NAME_LENGTH = 64
_UNSAFE_TOOL_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_]+")


def _normalize_input_schema(input_schema: Any) -> dict[str, Any]:
    if not isinstance(input_schema, dict):
        return {"type": "object", "properties": {}, "required": []}

    schema = dict(input_schema)
    if not isinstance(schema.get("type", "object"), str):
        schema["type"] = "object"
    if schema.get("type") != "object":
        schema["type"] = "object"

    raw_properties = schema.get("properties", {})
    properties: dict[str, dict[str, Any]] = {}
    if isinstance(raw_properties, dict):
        for name, prop_schema in raw_properties.items():
            if not isinstance(name, str) or not name:
                continue
            if isinstance(prop_schema, dict):
                properties[name] = dict(prop_schema)
            else:
                properties[name] = {"type": "string"}
    schema["properties"] = properties

    raw_required = schema.get("required", [])
    if isinstance(raw_required, list):
        schema["required"] = [
            item
            for item in raw_required
            if isinstance(item, str) and item in properties
        ]
    else:
        schema["required"] = []

    return schema


def build_public_tool_name(server_name: str, tool_name: str) -> str:
    raw_name = f"mcp_{server_name}_{tool_name}"
    safe_name = _UNSAFE_TOOL_NAME_CHARS_RE.sub("_", raw_name).strip("_")
    if not safe_name:
        safe_name = "mcp_tool"
    if not re.match(r"^[A-Za-z_]", safe_name):
        safe_name = f"mcp_{safe_name}"

    if safe_name == raw_name and len(safe_name) <= MAX_PUBLIC_TOOL_NAME_LENGTH:
        return safe_name

    digest = hashlib.sha1(raw_name.encode("utf-8")).hexdigest()[:8]
    suffix = f"_{digest}"
    base_length = MAX_PUBLIC_TOOL_NAME_LENGTH - len(suffix)
    base = safe_name[:base_length].rstrip("_") or "mcp_tool"
    return f"{base}{suffix}"


def _build_params_model(
    tool_name: str, input_schema: dict[str, Any]
) -> type[BaseModel]:
    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    field_definitions: dict[str, Any] = {}
    for name, prop in properties.items():
        py_type = _json_type_to_python(prop.get("type", "string"))
        if name in required:
            field_definitions[name] = (py_type, ...)
        else:
            field_definitions[name] = (py_type | None, None)

    return create_model(f"{tool_name}Params", **field_definitions)


def _json_type_to_python(json_type: object) -> type:
    if isinstance(json_type, list):
        json_type = next(
            (item for item in json_type if isinstance(item, str) and item != "null"),
            "string",
        )
    mapping: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    return mapping.get(json_type, str)


def _extract_text(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        if isinstance(block, mcp_types.TextContent):
            parts.append(block.text)
        elif isinstance(block, mcp_types.ImageContent):
            parts.append(f"[image: {block.mimeType}]")
        elif isinstance(block, mcp_types.EmbeddedResource):
            resource = block.resource
            if hasattr(resource, "text"):
                parts.append(resource.text)
            else:
                parts.append(f"[binary resource: {resource.uri}]")
    return "\n".join(parts) if parts else "(no output)"


class MCPToolWrapper(Tool):
    def __init__(
        self,
        server_name: str,
        tool_def: mcp_types.Tool,
        client: MCPClient,
    ) -> None:
        self._server_name = server_name
        self._tool_def = tool_def
        self._client = client
        self._input_schema = _normalize_input_schema(tool_def.inputSchema)
        self.name = build_public_tool_name(server_name, tool_def.name)
        self.description = tool_def.description or tool_def.name
        self.category = "command"
        self.is_concurrency_safe = False
        self.should_defer = True
        self.params_model = _build_params_model(
            self.name, self._input_schema
        )

    @property
    def mcp_tool_name(self) -> str:
        return self._tool_def.name


    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._input_schema,
        }


    async def execute(self, params: BaseModel) -> ToolResult:
        if not self._client.is_alive:
            try:
                await self._client.connect()
            except Exception as e:
                return ToolResult(
                    output=f"MCP server '{self._server_name}' reconnect failed: {e}",
                    is_error=True,
                )

        try:
            result = await self._client.call_tool(
                self._tool_def.name, params.model_dump(exclude_none=True)
            )
        except Exception as e:
            await self._client.close()
            return ToolResult(
                output=f"MCP tool call failed: {e}",
                is_error=True,
            )

        text = _extract_text(result.content)
        return ToolResult(output=text, is_error=bool(result.isError))
