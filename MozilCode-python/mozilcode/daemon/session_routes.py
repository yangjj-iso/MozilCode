from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.client import LLMError
from mozilcode.daemon.request_body import (
    choice_field,
    parse_json_object,
    string_field,
    string_mapping_field,
)
from mozilcode.daemon.request_context import daemon_server, path_param
from mozilcode.daemon.responses import (
    action_response,
    bad_request_response,
    not_found_response,
)
from mozilcode.daemon.server_state import ACTIVE_TASK_RUNNING_ERROR

USER_CONFIG_FILE = Path.home() / ".mozilcode" / "config.yaml"
PERMISSION_RESPONSES = {"allow", "deny", "allow_always"}
MODE_REQUESTS = {
    "acceptEdits",
    "bypassPermissions",
    "custom",
    "default",
    "do",
    "dontAsk",
    "plan",
}


@dataclass(frozen=True)
class CreateSessionBody:
    session_id: str | None
    work_dir: str | None


@dataclass(frozen=True)
class StartTaskBody:
    session_id: str
    prompt: str


@dataclass(frozen=True)
class PermissionResolutionBody:
    request_id: str
    response: str


@dataclass(frozen=True)
class AskUserResolutionBody:
    request_id: str
    answers: dict[str, str]


def _parse_create_session_body(body: dict[str, Any]) -> CreateSessionBody:
    return CreateSessionBody(
        session_id=string_field(body, "session_id") or None,
        work_dir=string_field(body, "work_dir") or None,
    )


def _parse_mode_body(body: dict[str, Any]) -> str:
    return choice_field(body, "mode", MODE_REQUESTS).strip()


def _parse_start_task_body(body: dict[str, Any]) -> StartTaskBody:
    return StartTaskBody(
        session_id=string_field(body, "session_id"),
        prompt=string_field(body, "prompt"),
    )


def _parse_permission_resolution_body(
    body: dict[str, Any],
) -> PermissionResolutionBody:
    return PermissionResolutionBody(
        request_id=string_field(body, "request_id"),
        response=choice_field(body, "response", PERMISSION_RESPONSES, "deny"),
    )


def _parse_askuser_resolution_body(body: dict[str, Any]) -> AskUserResolutionBody:
    return AskUserResolutionBody(
        request_id=string_field(body, "request_id"),
        answers=string_mapping_field(body, "answers"),
    )


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
    parsed = await parse_json_object(request, _parse_create_session_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    try:
        sid = await server.init_session(body.session_id, body.work_dir)
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


async def set_session_mode(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    parsed = await parse_json_object(request, _parse_mode_body)
    if parsed.error is not None:
        return parsed.error
    mode = parsed.unwrap()
    if not mode:
        return bad_request_response("mode is required")
    try:
        status = await server.set_permission_mode(sid, mode)
    except ValueError as e:
        return bad_request_response(str(e))
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
    parsed = await parse_json_object(request, _parse_start_task_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    if not body.session_id or not body.prompt:
        return bad_request_response("session_id and prompt are required")
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
    parsed = await parse_json_object(request, _parse_permission_resolution_body)
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
    parsed = await parse_json_object(request, _parse_askuser_resolution_body)
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
