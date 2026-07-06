"""MCP 客户端系统的测试（第 6 章）。"""
from __future__ import annotations

import asyncio
import os
import textwrap
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from mozilcode.config import (
    AppConfig,
    ConfigError,
    MCPServerConfig,
    build_child_env,
    load_config,
    resolve_env_vars,
)

# ===========================================================================
# resolve_env_vars
# ===========================================================================

class TestResolveEnvVars:

    def test_substitutes_existing_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "secret123")
        assert resolve_env_vars("${MY_TOKEN}") == "secret123"

    def test_preserves_missing_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        assert resolve_env_vars("${NONEXISTENT_VAR}") == "${NONEXISTENT_VAR}"

    def test_no_placeholder_passthrough(self) -> None:
        assert resolve_env_vars("plain-text") == "plain-text"

    def test_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("A", "hello")
        monkeypatch.setenv("B", "world")
        assert resolve_env_vars("${A}-${B}") == "hello-world"

    def test_mixed_existing_and_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXISTS", "yes")
        monkeypatch.delenv("NOPE", raising=False)
        assert resolve_env_vars("${EXISTS}/${NOPE}") == "yes/${NOPE}"

# ===========================================================================
# build_child_env
# ===========================================================================

class TestBuildChildEnv:
    def test_includes_path(self) -> None:
        env = build_child_env(None)
        assert "PATH" in env

    def test_includes_declared_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_SECRET", "abc")
        env = build_child_env({"TOKEN": "${MY_SECRET}"})
        assert env["TOKEN"] == "abc"
        assert "PATH" in env

    def test_excludes_host_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        env = build_child_env({"FOO": "bar"})
        assert "ANTHROPIC_API_KEY" not in env
        assert env["FOO"] == "bar"

    def test_empty_declared_env(self) -> None:
        env = build_child_env({})
        assert "PATH" in env
        assert len(env) == 1

# ===========================================================================
# load_config：解析 mcp_servers
# ===========================================================================

class TestLoadConfigMCP:
    def _write_config(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "config.yaml"
        p.write_text(textwrap.dedent(content))
        return p

    def test_no_mcp_servers(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
        """)
        config = load_config(path)
        assert config.mcp_servers == []

    def test_stdio_server(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: github
                command: npx
                args: ["-y", "@modelcontextprotocol/server-github"]
                env:
                  GITHUB_TOKEN: "${GITHUB_TOKEN}"
        """)
        config = load_config(path)
        assert len(config.mcp_servers) == 1
        srv = config.mcp_servers[0]
        assert srv.name == "github"
        assert srv.command == "npx"
        assert srv.is_stdio is True
        assert srv.args == ["-y", "@modelcontextprotocol/server-github"]

    def test_server_name_is_trimmed(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: " github "
                command: npx
        """)
        config = load_config(path)
        assert config.mcp_servers[0].name == "github"

    def test_http_server(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: remote
                url: "https://api.example.com/mcp"
                headers:
                  Authorization: "Bearer ${TOKEN}"
        """)
        config = load_config(path)
        srv = config.mcp_servers[0]
        assert srv.name == "remote"
        assert srv.url == "https://api.example.com/mcp"
        assert srv.is_stdio is False

    def test_mcp_transport_fields_are_trimmed(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: local
                command: " npx "
              - name: remote
                url: " https://api.example.com/mcp "
        """)
        config = load_config(path)
        assert config.mcp_servers[0].command == "npx"
        assert config.mcp_servers[1].url == "https://api.example.com/mcp"

    def test_both_command_and_url_errors(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: bad
                command: npx
                url: "https://example.com"
        """)
        with pytest.raises(ConfigError, match="cannot have both"):
            load_config(path)

    def test_neither_command_nor_url_errors(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: bad
                env:
                  FOO: bar
        """)
        with pytest.raises(ConfigError, match="must have either"):
            load_config(path)

    def test_duplicate_server_names_are_rejected(self, tmp_path: Path) -> None:
        path = self._write_config(tmp_path, """\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: github
                command: npx
              - name: " github "
                url: "https://example.com/mcp"
        """)
        with pytest.raises(ConfigError, match="duplicate name"):
            load_config(path)

    @pytest.mark.parametrize(
        "field, value, message",
        [
            ("command", "[]", "command must be a string"),
            ("command", "''", "command must not be empty"),
            ("url", "123", "url must be a string"),
            ("url", "''", "url must not be empty"),
        ],
    )
    def test_mcp_transport_fields_are_validated(
        self,
        tmp_path: Path,
        field: str,
        value: str,
        message: str,
    ) -> None:
        path = self._write_config(tmp_path, f"""\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: bad
                {field}: {value}
        """)
        with pytest.raises(ConfigError, match=message):
            load_config(path)

    @pytest.mark.parametrize(
        "body, message",
        [
            ("args: echo", "args must be a list of strings"),
            ("args: ['ok', 1]", "args must be a list of strings"),
            ("headers: []", "headers must be a mapping of strings to strings"),
            (
                "headers:\n                  X-Test: 1",
                "headers must be a mapping of strings to strings",
            ),
            ("env: []", "env must be a mapping of strings to strings"),
            (
                "env:\n                  TOKEN: 1",
                "env must be a mapping of strings to strings",
            ),
        ],
    )
    def test_mcp_collection_fields_are_validated(
        self,
        tmp_path: Path,
        body: str,
        message: str,
    ) -> None:
        path = self._write_config(tmp_path, f"""\
            providers:
              - name: test
                protocol: openai
                base_url: http://localhost
                model: gpt-4o
            mcp_servers:
              - name: bad
                command: npx
                {body}
        """)
        with pytest.raises(ConfigError, match=message):
            load_config(path)

# ===========================================================================
# MCPToolWrapper
# ===========================================================================

class TestMCPToolWrapper:
    def test_name_format(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import MCPToolWrapper
        from mozilcode.mcp.client import MCPClient

        tool_def = mcp_types.Tool(
            name="search_issues",
            description="Search GitHub issues",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["repo"],
            },
        )
        mock_client = MagicMock(spec=MCPClient)
        wrapper = MCPToolWrapper("github", tool_def, mock_client)

        assert wrapper.name == "mcp_github_search_issues"
        assert wrapper.category == "command"
        assert wrapper.description == "Search GitHub issues"

    def test_public_name_is_sanitized_but_mcp_name_is_preserved(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import (
            MAX_PUBLIC_TOOL_NAME_LENGTH,
            MCPToolWrapper,
        )

        tool_def = mcp_types.Tool(
            name="search issues with a very long external MCP name!!!" * 2,
            description="Search",
            inputSchema={"type": "object", "properties": {}},
        )
        wrapper = MCPToolWrapper("github-prod", tool_def, MagicMock())

        assert wrapper.name.startswith("mcp_github_prod_search_issues")
        assert len(wrapper.name) <= MAX_PUBLIC_TOOL_NAME_LENGTH
        assert "-" not in wrapper.name
        assert "!" not in wrapper.name
        assert wrapper.mcp_tool_name == tool_def.name

    def test_get_schema_uses_original_input_schema(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import MCPToolWrapper

        input_schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        tool_def = mcp_types.Tool(
            name="search",
            description="Search",
            inputSchema=input_schema,
        )
        mock_client = MagicMock()
        wrapper = MCPToolWrapper("srv", tool_def, mock_client)

        schema = wrapper.get_schema()
        assert schema["name"] == "mcp_srv_search"
        assert schema["input_schema"] == input_schema

    def test_malformed_input_schema_is_normalized(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import MCPToolWrapper

        tool_def = mcp_types.Tool(
            name="search",
            description="Search",
            inputSchema={
                "type": "array",
                "properties": [],
                "required": "query",
            },
        )
        wrapper = MCPToolWrapper("srv", tool_def, MagicMock())

        schema = wrapper.get_schema()["input_schema"]
        assert schema == {"type": "object", "properties": {}, "required": []}
        assert wrapper.params_model.model_validate({}).model_dump() == {}

    def test_input_schema_properties_are_normalized(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import MCPToolWrapper

        tool_def = mcp_types.Tool(
            name="search",
            description="Search",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": ["string", "null"]},
                    "count": {"type": "integer"},
                    "fallback": True,
                    "": {"type": "string"},
                },
                "required": ["query", "missing", 7],
            },
        )
        wrapper = MCPToolWrapper("srv", tool_def, MagicMock())

        schema = wrapper.get_schema()["input_schema"]
        assert schema["required"] == ["query"]
        assert schema["properties"]["fallback"] == {"type": "string"}
        assert "" not in schema["properties"]

        params = wrapper.params_model.model_validate(
            {"query": "bugs", "count": 2, "fallback": "ok"}
        )
        assert params.model_dump() == {
            "query": "bugs",
            "count": 2,
            "fallback": "ok",
        }

    @pytest.mark.asyncio
    async def test_execute_uses_original_mcp_tool_name(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import MCPToolWrapper

        tool_def = mcp_types.Tool(
            name="search issues",
            description="Search",
            inputSchema={"type": "object", "properties": {}},
        )
        result = mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="ok")],
            isError=False,
        )
        client = AsyncMock()
        client.is_alive = True
        client.call_tool.return_value = result

        wrapper = MCPToolWrapper("github-prod", tool_def, client)
        params = wrapper.params_model()

        output = await wrapper.execute(params)

        assert output.output == "ok"
        client.call_tool.assert_awaited_once_with("search issues", {})

    @pytest.mark.asyncio
    async def test_execute_closes_client_after_call_failure(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import MCPToolWrapper

        tool_def = mcp_types.Tool(
            name="search",
            description="Search",
            inputSchema={"type": "object", "properties": {}},
        )
        client = AsyncMock()
        client.is_alive = True
        client.call_tool.side_effect = RuntimeError("server closed")

        wrapper = MCPToolWrapper("github", tool_def, client)
        params = wrapper.params_model()

        output = await wrapper.execute(params)

        assert output.is_error is True
        assert "server closed" in output.output
        client.close.assert_awaited_once()


# ===========================================================================
# MCPClient 状态守卫
# ===========================================================================

class TestMCPClientState:
    @pytest.mark.asyncio
    async def test_list_tools_requires_connected_session(self) -> None:
        from mozilcode.mcp.client import MCPClient

        client = MCPClient(MCPServerConfig(name="local", command="echo"))

        with pytest.raises(RuntimeError, match="not connected"):
            await client.list_tools()

    @pytest.mark.asyncio
    async def test_call_tool_requires_connected_session(self) -> None:
        from mozilcode.mcp.client import MCPClient

        client = MCPClient(MCPServerConfig(name="local", command="echo"))

        with pytest.raises(RuntimeError, match="not connected"):
            await client.call_tool("tool", {})

    @pytest.mark.asyncio
    async def test_connect_cleans_stale_stack_before_reconnect(self) -> None:
        from contextlib import AsyncExitStack

        from mozilcode.mcp.client import MCPClient

        client = MCPClient(MCPServerConfig(name="local", command="echo"))
        stale_stack = AsyncMock(spec=AsyncExitStack)
        client._stack = stale_stack

        with patch.object(client, "_connect_stdio", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await client.connect()

        stale_stack.__aexit__.assert_awaited_once_with(None, None, None)

# ===========================================================================
# _extract_text
# ===========================================================================

class TestExtractText:
    def test_text_content(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import _extract_text

        content = [
            mcp_types.TextContent(type="text", text="hello"),
            mcp_types.TextContent(type="text", text="world"),
        ]
        assert _extract_text(content) == "hello\nworld"

    def test_empty_content(self) -> None:
        from mozilcode.mcp.tool_wrapper import _extract_text

        assert _extract_text([]) == "(no output)"

    def test_image_content(self) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.tool_wrapper import _extract_text

        content = [mcp_types.ImageContent(type="image", data="...", mimeType="image/png")]
        assert "[image: image/png]" in _extract_text(content)

# ===========================================================================
# MCPManager：部分失败容错
# ===========================================================================

class TestMCPManagerPartialFailure:
    @pytest.mark.asyncio
    async def test_single_server_failure_does_not_block_others(self) -> None:
        from mozilcode.mcp.manager import MCPManager
        from mozilcode.tools import ToolRegistry

        good_config = MCPServerConfig(
            name="good",
            command="echo",
            args=["hello"],
        )
        bad_config = MCPServerConfig(
            name="bad",
            command="nonexistent_command_xyz_12345",
        )

        manager = MCPManager()
        manager.load_configs([bad_config, good_config])

        registry = ToolRegistry()

        with patch("mozilcode.mcp.manager.MCPClient") as MockClient:
            good_instance = AsyncMock()
            good_instance.is_alive = True

            from mcp import types as mcp_types
            good_instance.list_tools.return_value = [
                mcp_types.Tool(
                    name="test_tool",
                    description="A test",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

            bad_instance = AsyncMock()
            bad_instance.connect.side_effect = RuntimeError("command not found")

            def make_client(config: MCPServerConfig) -> AsyncMock:
                if config.name == "bad":
                    return bad_instance
                return good_instance

            MockClient.side_effect = make_client

            errors = await manager.register_all_tools(registry)

        assert len(errors) == 1
        assert "bad" in errors[0]
        assert registry.get("mcp_good_test_tool") is not None

    @pytest.mark.asyncio
    async def test_list_tools_failure_closes_unregistered_client(self) -> None:
        from mozilcode.mcp.manager import MCPManager
        from mozilcode.tools import ToolRegistry

        config = MCPServerConfig(name="bad", command="echo")
        manager = MCPManager()
        manager.load_configs([config])
        registry = ToolRegistry()

        with patch("mozilcode.mcp.manager.MCPClient") as MockClient:
            client = AsyncMock()
            client.list_tools.side_effect = RuntimeError("list failed")
            MockClient.return_value = client

            errors = await manager.register_all_tools(registry)

        assert len(errors) == 1
        assert "list failed" in errors[0]
        client.close.assert_awaited_once()
        assert manager._clients == {}
        assert registry.list_tools() == []

    @pytest.mark.asyncio
    async def test_cleanup_failure_does_not_mask_registration_error(self) -> None:
        from mozilcode.mcp.manager import MCPManager
        from mozilcode.tools import ToolRegistry

        config = MCPServerConfig(name="bad", command="echo")
        manager = MCPManager()
        manager.load_configs([config])

        with patch("mozilcode.mcp.manager.MCPClient") as MockClient:
            client = AsyncMock()
            client.list_tools.side_effect = RuntimeError("list failed")
            client.close.side_effect = RuntimeError("close failed")
            MockClient.return_value = client

            errors = await manager.register_all_tools(ToolRegistry())

        assert len(errors) == 1
        assert "list failed" in errors[0]
        assert "close failed" not in errors[0]
        assert manager._clients == {}

    @pytest.mark.asyncio
    async def test_duplicate_public_tool_names_are_reported_without_overwrite(
        self,
    ) -> None:
        from mcp import types as mcp_types
        from mozilcode.mcp.manager import MCPManager
        from mozilcode.tools import ToolRegistry

        config = MCPServerConfig(name="good", command="echo")
        manager = MCPManager()
        manager.load_configs([config])
        registry = ToolRegistry()

        with patch("mozilcode.mcp.manager.MCPClient") as MockClient:
            client = AsyncMock()
            client.is_alive = True
            client.list_tools.return_value = [
                mcp_types.Tool(
                    name="same_tool",
                    description="First",
                    inputSchema={"type": "object", "properties": {}},
                ),
                mcp_types.Tool(
                    name="same_tool",
                    description="Second",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]
            MockClient.return_value = client

            errors = await manager.register_all_tools(registry)

        assert len(errors) == 1
        assert "duplicate registered tool 'mcp_good_same_tool'" in errors[0]
        assert registry.get("mcp_good_same_tool").description == "First"
        assert manager._clients == {"good": client}
