from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.client import LLMError
from mozilcode.daemon.request_body import read_json_object
from mozilcode.daemon.responses import (
    action_response,
    bad_request_response,
    not_found_response,
)

USER_CONFIG_FILE = Path.home() / ".mozilcode" / "config.yaml"


async def health(request: Request) -> JSONResponse:
    server = request.app.state.server
    return JSONResponse(
        {
            "status": "ok",
            "service": "mozilcode-daemon",
            "work_dir": server.work_dir,
            "configured": server.config is not None,
            "config_path": str(USER_CONFIG_FILE),
        }
    )


async def create_session(request: Request) -> JSONResponse:
    server = request.app.state.server
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    session_id = body.get("session_id") if body else None
    work_dir = body.get("work_dir") if body else None
    try:
        sid = await server.init_session(session_id, work_dir)
    except ValueError as e:
        return bad_request_response(str(e), configured=server.config is not None)
    return JSONResponse({"session_id": sid, **server.session_info(sid)})


async def list_sessions(request: Request) -> JSONResponse:
    server = request.app.state.server
    return JSONResponse({"sessions": server.list_session_infos()})


async def session_info(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    if not server.has_session(sid):
        return not_found_response("session not found")
    return JSONResponse(server.session_info(sid))


async def session_status(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    try:
        ok = await server.ensure_agent(sid)
    except LLMError as e:
        status = server.status(sid)
        status["agent_ready"] = False
        status["error"] = str(e)
        return JSONResponse(status)
    if not ok:
        return not_found_response("session not found")
    status = server.status(sid)
    status["agent_ready"] = True
    return JSONResponse(status)


async def set_session_mode(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    mode = (body.get("mode") or "").strip()
    if not mode:
        return bad_request_response("mode is required")
    try:
        status = await server.set_permission_mode(sid, mode)
    except ValueError as e:
        return bad_request_response(str(e))
    return JSONResponse(status)


async def cancel_active_task(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    if not server.has_session(sid):
        return not_found_response("session not found")
    cancelled = server.cancel_active_task(sid)
    return JSONResponse({"cancelled": cancelled})


async def list_background_tasks(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    result = await server.list_background_tasks(sid)
    return action_response(result)


async def cancel_background_task(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    task_id = request.path_params["task_id"]
    result = await server.cancel_background_task(sid, task_id)
    return action_response(result)


async def start_task(request: Request) -> JSONResponse:
    server = request.app.state.server
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    sid = body.get("session_id")
    prompt = body.get("prompt", "")
    if not sid or not prompt:
        return bad_request_response("session_id and prompt are required")
    try:
        task_id = await server.start_task(sid, prompt)
    except ValueError as e:
        return not_found_response(str(e))
    return JSONResponse({"task_id": task_id, "session_id": sid})


async def resolve_permission(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    request_id = body.get("request_id", "")
    response = body.get("response", "deny")
    ok = await server.resolve_permission(sid, request_id, response)
    if not ok:
        return not_found_response("request not found")
    return JSONResponse({"resolved": True})


async def resolve_askuser(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    request_id = body.get("request_id", "")
    answers = body.get("answers", {})
    ok = await server.resolve_askuser(sid, request_id, answers)
    if not ok:
        return not_found_response("request not found")
    return JSONResponse({"resolved": True})


async def manual_compact(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    result = await server.manual_compact(sid)
    return action_response(result)


async def close_session(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    await server.close_session(sid)
    return JSONResponse({"closed": True})
