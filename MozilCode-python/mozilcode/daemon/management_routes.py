from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.config_settings import (
    app_config_to_raw,
    memory_settings_from_payload,
    public_memory_settings,
    write_user_config,
)
from mozilcode.daemon.request_body import read_json_object
from mozilcode.daemon.extension_settings import (
    create_skill_from_payload,
    delete_mcp_server,
    delete_user_skill,
    list_mcp_servers,
    list_skills,
    toggle_mcp_server,
    toggle_skill,
    upsert_mcp_server,
)
from mozilcode.daemon.settings import load_daemon_settings, save_daemon_settings
from mozilcode.validator import ConfigError, validate_config_structure

log = logging.getLogger(__name__)


async def mcp_list(request: Request) -> JSONResponse:
    return JSONResponse({"servers": list_mcp_servers(load_daemon_settings())})


async def mcp_add(request: Request) -> JSONResponse:
    try:
        parsed = await read_json_object(request)
        if not parsed.ok:
            return parsed.error_response()
        body = parsed.payload
        data = load_daemon_settings()
        servers = upsert_mcp_server(data, body or {})
        save_daemon_settings(data)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"ok": True, "servers": servers})


async def mcp_delete(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    data = load_daemon_settings()
    delete_mcp_server(data, name)
    save_daemon_settings(data)
    return JSONResponse({"ok": True})


async def mcp_toggle(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    data = load_daemon_settings()
    toggle_mcp_server(data, name)
    save_daemon_settings(data)
    return JSONResponse({"ok": True})


async def memory_settings_get(request: Request) -> JSONResponse:
    server = request.app.state.server
    return JSONResponse(public_memory_settings(server.config))


async def memory_settings_save(request: Request) -> JSONResponse:
    server = request.app.state.server
    if server.config is None:
        return JSONResponse(
            public_memory_settings(server.config, "model provider is not configured"),
            status_code=400,
        )
    try:
        parsed = await read_json_object(request)
        if not parsed.ok:
            return JSONResponse(
                public_memory_settings(server.config, parsed.error),
                status_code=parsed.status_code,
            )
        body = parsed.payload
        raw = app_config_to_raw(server.config)
        raw["memory"] = memory_settings_from_payload(body or {}, server.config)
        validate_config_structure(raw)
        server.config = write_user_config(raw)
        await server.invalidate_idle_agents()
    except (ConfigError, ValueError, TypeError) as e:
        return JSONResponse(public_memory_settings(server.config, str(e)), status_code=400)
    except Exception as e:
        log.exception("Failed to save memory settings")
        return JSONResponse(public_memory_settings(server.config, str(e)), status_code=500)
    return JSONResponse({"ok": True, **public_memory_settings(server.config)})


async def skills_list(request: Request) -> JSONResponse:
    server = request.app.state.server
    try:
        out = list_skills(server.work_dir, load_daemon_settings())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"skills": out})


async def skill_toggle(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    data = load_daemon_settings()
    toggle_skill(data, name)
    save_daemon_settings(data)
    return JSONResponse({"ok": True})


async def skill_create(request: Request) -> JSONResponse:
    try:
        parsed = await read_json_object(request)
        if not parsed.ok:
            return parsed.error_response()
        body = parsed.payload
        create_skill_from_payload(body or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


async def skill_delete(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    try:
        delete_user_skill(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})
