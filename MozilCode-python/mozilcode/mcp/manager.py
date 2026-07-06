from __future__ import annotations

import logging

from mozilcode.config import MCPServerConfig
from mozilcode.mcp.client import MCPClient
from mozilcode.mcp.tool_wrapper import MCPToolWrapper
from mozilcode.tools import ToolRegistry

logger = logging.getLogger(__name__)


class MCPManager:
    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    def load_configs(self, configs: list[MCPServerConfig]) -> None:
        for cfg in configs:
            self._configs[cfg.name] = cfg

    async def register_all_tools(self, registry: ToolRegistry) -> list[str]:
        errors: list[str] = []
        for name, config in self._configs.items():
            try:
                errors.extend(
                    await self._register_server_tools(name, config, registry)
                )
            except Exception as e:
                msg = f"MCP server '{name}': {e}"
                logger.warning(msg)
                errors.append(msg)

        return errors

    async def _register_server_tools(
        self,
        name: str,
        config: MCPServerConfig,
        registry: ToolRegistry,
    ) -> list[str]:
        client = MCPClient(config)
        errors: list[str] = []
        try:
            await client.connect()
            tools = await client.list_tools()
            for tool_def in tools:
                wrapper = MCPToolWrapper(name, tool_def, client)
                if registry.get(wrapper.name) is not None:
                    msg = (
                        f"MCP server '{name}' tool '{tool_def.name}' maps to "
                        f"duplicate registered tool '{wrapper.name}'"
                    )
                    logger.warning(msg)
                    errors.append(msg)
                    continue
                registry.register(wrapper)
                logger.info("Registered MCP tool: %s", wrapper.name)
            self._clients[name] = client
            return errors
        except Exception:
            try:
                await client.close()
            except Exception:
                logger.debug("Error closing failed MCP server '%s'", name, exc_info=True)
            raise

    async def get_client(self, name: str) -> MCPClient | None:
        client = self._clients.get(name)
        if client is None:
            config = self._configs.get(name)
            if config is None:
                return None
            client = MCPClient(config)
            await client.connect()
            self._clients[name] = client
            return client

        if not client.is_alive:
            logger.info("Reconnecting MCP server '%s'", name)
            await client.close()
            client = MCPClient(self._configs[name])
            await client.connect()
            self._clients[name] = client

        return client

    async def shutdown(self) -> None:
        for name, client in self._clients.items():
            try:
                await client.close()
                logger.info("MCP server '%s' closed", name)
            except Exception:
                logger.debug("Error closing MCP server '%s'", name, exc_info=True)
        self._clients.clear()
