"""Routes for settings management — MCP servers, memory, and bot stubs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any

import yaml
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
from mozilcode.config import load_config
from mozilcode.config.validator import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    ConfigError,
    validate_memory,
)

USER_CONFIG_FILE = Path.home() / ".mozilcode" / "config.yaml"


def _read_raw_config() -> dict[str, Any]:
    if not USER_CONFIG_FILE.exists():
        return {}
    try:
        raw = yaml.safe_load(USER_CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return raw
    except yaml.YAMLError:
        return {}


def _write_raw_config(raw: dict[str, Any]) -> None:
    USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        raw, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    fd, temporary = tempfile.mkstemp(
        prefix=f".{USER_CONFIG_FILE.name}.",
        suffix=".tmp",
        dir=USER_CONFIG_FILE.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, USER_CONFIG_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _apply_raw_config(request: Request, raw: dict[str, Any]) -> JSONResponse | None:
    server = daemon_server(request)
    previous_exists = USER_CONFIG_FILE.exists()
    previous_raw = _read_raw_config()
    try:
        raw.setdefault("schema_version", CURRENT_CONFIG_SCHEMA_VERSION)
        _write_raw_config(raw)
        server.config = load_config()
    except Exception as exc:
        if previous_exists:
            _write_raw_config(previous_raw)
        elif USER_CONFIG_FILE.exists():
            USER_CONFIG_FILE.unlink()
        return bad_request_response(f"Configuration was not applied: {exc}")
    return None


def _mcp_server_to_dict(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": s.get("name", ""),
        "command": s.get("command") or "",
        "args": s.get("args") or [],
        "url": s.get("url") or "",
        "enabled": s.get("enabled", True),
    }


def _application_status(request: Request) -> dict[str, object]:
    return daemon_server(request).config_application_status()


# ---------------------------------------------------------------------------
# MCP server routes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CreateMcpBody:
    name: str
    command: str
    args: str
    url: str


def _parse_create_mcp_body(payload: dict[str, Any]) -> CreateMcpBody:
    name = required_string_field(payload, "name")
    command = string_field(payload, "command")
    args = string_field(payload, "args")
    url = string_field(payload, "url")
    if not command and not url:
        raise BodyFieldError("MCP server must have either 'command' or 'url'")
    if command and url:
        raise BodyFieldError("MCP server cannot have both 'command' and 'url'")
    return CreateMcpBody(name=name, command=command, args=args, url=url)


async def list_mcp_servers(request: Request) -> JSONResponse:
    raw = _read_raw_config()
    servers = raw.get("mcp_servers", [])
    if not isinstance(servers, list):
        servers = []
    return JSONResponse({"servers": [_mcp_server_to_dict(s) for s in servers]})


async def create_mcp_server(request: Request) -> JSONResponse:
    parsed = await parse_json_object(request, _parse_create_mcp_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()

    raw = _read_raw_config()
    servers = raw.get("mcp_servers", [])
    if not isinstance(servers, list):
        servers = []
    if any(s.get("name") == body.name for s in servers):
        return bad_request_response(f"MCP server '{body.name}' already exists")

    entry: dict[str, Any] = {"name": body.name, "enabled": True}
    if body.command:
        entry["command"] = body.command
        entry["args"] = [a.strip() for a in body.args.split() if a.strip()] if body.args else []
    if body.url:
        entry["url"] = body.url

    servers.append(entry)
    raw["mcp_servers"] = servers
    error = _apply_raw_config(request, raw)
    if error is not None:
        return error
    return JSONResponse({
        "servers": [_mcp_server_to_dict(s) for s in servers],
        **_application_status(request),
    })


async def toggle_mcp_server(request: Request) -> JSONResponse:
    name = path_param(request, "name")
    raw = _read_raw_config()
    servers = raw.get("mcp_servers", [])
    if not isinstance(servers, list):
        servers = []
    found = False
    for s in servers:
        if s.get("name") == name:
            s["enabled"] = not s.get("enabled", True)
            found = True
            enabled = s["enabled"]
            break
    if not found:
        return not_found_response(f"MCP server '{name}' not found")
    raw["mcp_servers"] = servers
    error = _apply_raw_config(request, raw)
    if error is not None:
        return error
    return JSONResponse({
        "name": name,
        "enabled": enabled,
        **_application_status(request),
    })


async def delete_mcp_server(request: Request) -> JSONResponse:
    name = path_param(request, "name")
    raw = _read_raw_config()
    servers = raw.get("mcp_servers", [])
    if not isinstance(servers, list):
        servers = []
    new_servers = [s for s in servers if s.get("name") != name]
    if len(new_servers) == len(servers):
        return not_found_response(f"MCP server '{name}' not found")
    raw["mcp_servers"] = new_servers
    error = _apply_raw_config(request, raw)
    if error is not None:
        return error
    return JSONResponse({
        "name": name,
        "deleted": True,
        **_application_status(request),
    })


# ---------------------------------------------------------------------------
# Memory settings routes
# ---------------------------------------------------------------------------

async def get_memory_settings(request: Request) -> JSONResponse:
    raw = _read_raw_config()
    memory = raw.get("memory", {})
    if not isinstance(memory, dict):
        memory = {}
    return JSONResponse({
        "enabled": memory.get("enabled", True),
        "providers": memory.get("providers", []),
        "config_path": str(USER_CONFIG_FILE),
    })


async def save_memory_settings(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        return bad_request_response("Invalid JSON body")
    if not isinstance(payload, dict):
        return bad_request_response("JSON object is required")

    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        return bad_request_response("'enabled' must be a boolean")
    providers = payload.get("providers", [])
    if not isinstance(providers, list):
        return bad_request_response("'providers' must be a list")
    try:
        normalized = validate_memory({"enabled": enabled, "providers": providers})
    except ConfigError as exc:
        return bad_request_response(str(exc))

    raw = _read_raw_config()
    raw["memory"] = normalized
    error = _apply_raw_config(request, raw)
    if error is not None:
        return error
    return JSONResponse({
        "enabled": enabled,
        "providers": normalized["providers"],
        "config_path": str(USER_CONFIG_FILE),
        **_application_status(request),
    })


# ---------------------------------------------------------------------------
# QQ Bot stub routes (feature not supported)
# ---------------------------------------------------------------------------

async def get_qqbot_settings(request: Request) -> JSONResponse:
    return JSONResponse({
        "enabled": False,
        "configured": False,
        "running": False,
        "session_ready": False,
        "bot_name": "",
        "last_error": "",
        "config_path": "",
        "error": "QQ Bot is not supported in this build",
    })


async def save_qqbot_settings(request: Request) -> JSONResponse:
    return bad_request_response("QQ Bot is not supported in this build")


# ---------------------------------------------------------------------------
# Telegram Bot stub routes (feature not supported)
# ---------------------------------------------------------------------------

async def get_telegrambot_settings(request: Request) -> JSONResponse:
    return JSONResponse({
        "enabled": False,
        "configured": False,
        "running": False,
        "session_ready": False,
        "bot_username": "",
        "last_error": "",
        "config_path": "",
        "error": "Telegram Bot is not supported in this build",
    })


async def save_telegrambot_settings(request: Request) -> JSONResponse:
    return bad_request_response("Telegram Bot is not supported in this build")
