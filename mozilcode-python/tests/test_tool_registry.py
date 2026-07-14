"""ToolRegistry 注册、启用与 schema 测试。"""

from __future__ import annotations

from pydantic import BaseModel

from mozilcode.tools import ToolRegistry as PublicToolRegistry
from mozilcode.tools.base import Tool, ToolResult
from mozilcode.tools.registry import ToolRegistry, schema_for_protocol


class _Params(BaseModel):
    text: str = ""


class _Tool(Tool):
    name = "SampleTool"
    description = "Sample tool"
    params_model = _Params

    async def execute(self, params: BaseModel) -> ToolResult:
        return ToolResult(output=params.model_dump_json())


def test_public_tool_registry_import_remains_compatible() -> None:
    assert PublicToolRegistry is ToolRegistry


def test_schema_for_protocol_keeps_anthropic_shape() -> None:
    schema = schema_for_protocol(_Tool(), "anthropic")

    assert schema["name"] == "SampleTool"
    assert schema["input_schema"]["type"] == "object"
    assert "parameters" not in schema


def test_schema_for_protocol_converts_openai_shape() -> None:
    schema = schema_for_protocol(_Tool(), "openai-compat")

    assert schema["type"] == "function"
    assert schema["name"] == "SampleTool"
    assert schema["parameters"]["type"] == "object"
    assert "input_schema" not in schema


def test_registry_search_and_visibility_use_shared_schema_formatter() -> None:
    tool = _Tool()
    tool.should_defer = True
    registry = ToolRegistry()
    registry.register(tool)

    assert registry.get_all_schemas("openai") == []

    selected = registry.find_deferred_by_names(["SampleTool"], "openai")
    assert selected[0]["type"] == "function"

    registry.mark_discovered("SampleTool")
    assert registry.get_all_schemas("openai")[0]["type"] == "function"
