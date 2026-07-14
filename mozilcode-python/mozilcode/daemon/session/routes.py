"""会话 REST 路由：创建、列表、任务、权限解析等。"""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.request_body import parse_json_object
from mozilcode.daemon.request_context import daemon_server, path_param
from mozilcode.daemon.responses import (
    action_response,
    bad_request_response,
    not_found_response,
)
from mozilcode.daemon.tasks.active import ACTIVE_TASK_RUNNING_ERROR
from mozilcode.daemon.session.payloads import (
    parse_askuser_resolution_body,
    parse_create_session_body,
    parse_mode_body,
    parse_permission_resolution_body,
    parse_start_task_body,
    parse_switch_provider_body,
)
from mozilcode.client.errors import LLMError
from mozilcode.daemon.routes.stream import event_with_id, history_page

USER_CONFIG_FILE = Path.home() / ".mozilcode" / "config.yaml"


async def health(request: Request) -> JSONResponse:
    server = daemon_server(request)
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
    server = daemon_server(request)
    parsed = await parse_json_object(request, parse_create_session_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    try:
        sid = await server.init_session(body.session_id, body.work_dir, body.provider_name)
    except ValueError as e:
        return bad_request_response(str(e), configured=server.config is not None)
    return JSONResponse({"session_id": sid, **server.session_info(sid)})


async def list_sessions(request: Request) -> JSONResponse:
    server = daemon_server(request)
    return JSONResponse({"sessions": server.list_session_infos()})


async def session_info(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    if not server.has_session(sid):
        return not_found_response("session not found")
    return JSONResponse(server.session_info(sid))


async def session_status(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
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


async def session_history(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    events = server.get_event_log(sid)
    if events is None:
        return not_found_response("session not found")
    try:
        before = int(request.query_params.get("before", str(len(events))))
        limit = max(1, min(int(request.query_params.get("limit", "240")), 400))
    except ValueError:
        return bad_request_response("'before' and 'limit' must be integers")
    page, next_before = history_page(events, before, limit)
    start = next_before
    numbered = [event_with_id(event, start + offset) for offset, event in enumerate(page)]
    return JSONResponse({"events": numbered, "before": next_before, "has_more": next_before > 0})


async def set_session_mode(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    parsed = await parse_json_object(request, parse_mode_body)
    if parsed.error is not None:
        return parsed.error
    mode = parsed.unwrap()
    try:
        status = await server.set_permission_mode(sid, mode)
    except ValueError as e:
        return bad_request_response(str(e))
    return JSONResponse(status)


async def set_session_provider(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    parsed = await parse_json_object(request, parse_switch_provider_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    try:
        status = await server.set_session_provider(sid, body.provider_name, body.thinking)
    except ValueError as e:
        msg = str(e)
        if msg == "session not found":
            return not_found_response(msg)
        return bad_request_response(msg)
    return JSONResponse(status)


async def cancel_active_task(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    if not server.has_session(sid):
        return not_found_response("session not found")
    cancelled = server.cancel_active_task(sid)
    return JSONResponse({"cancelled": cancelled})


async def list_background_tasks(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    result = await server.list_background_tasks(sid)
    return action_response(result)


async def cancel_background_task(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    task_id = path_param(request, "task_id")
    result = await server.cancel_background_task(sid, task_id)
    return action_response(result)


async def start_task(request: Request) -> JSONResponse:
    server = daemon_server(request)
    parsed = await parse_json_object(request, parse_start_task_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    try:
        task_id = await server.start_task(body.session_id, body.prompt)
    except ValueError as e:
        if str(e) == ACTIVE_TASK_RUNNING_ERROR:
            return bad_request_response(str(e))
        return not_found_response(str(e))
    return JSONResponse({"task_id": task_id, "session_id": body.session_id})


async def resolve_permission(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    parsed = await parse_json_object(request, parse_permission_resolution_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    ok = await server.resolve_permission(sid, body.request_id, body.response)
    if not ok:
        return not_found_response("request not found")
    return JSONResponse({"resolved": True})


async def resolve_askuser(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    parsed = await parse_json_object(request, parse_askuser_resolution_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    ok = await server.resolve_askuser(sid, body.request_id, body.answers)
    if not ok:
        return not_found_response("request not found")
    return JSONResponse({"resolved": True})


async def manual_compact(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    result = await server.manual_compact(sid)
    return action_response(result)


async def close_session(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    try:
        await server.close_session(sid)
    except ValueError as e:
        return bad_request_response(str(e))
    return JSONResponse({"closed": True})
