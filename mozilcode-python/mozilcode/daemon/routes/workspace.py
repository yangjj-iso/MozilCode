"""工作区/worktree 与文件列表路由。"""

from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.request_body import parse_json_object
from mozilcode.daemon.request_context import daemon_server, path_param, query_param
from mozilcode.daemon.responses import (
    action_response,
    error_response,
    not_found_response,
)
from mozilcode.daemon.workspace_payloads import (
    WorkspacePathError,
    list_workspace_directory,
    parse_create_worktree_body,
    parse_exit_worktree_body,
)


async def list_worktrees(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    result = await server.list_worktrees(sid)
    return action_response(result)


async def create_worktree(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    parsed = await parse_json_object(request, parse_create_worktree_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    result = await server.create_worktree(sid, body.name, body.base_branch)
    return action_response(result)


async def enter_worktree(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    name = path_param(request, "name")
    result = await server.enter_worktree(sid, name)
    return action_response(result)


async def exit_worktree(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    parsed = await parse_json_object(request, parse_exit_worktree_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    result = await server.exit_worktree(
        sid,
        remove=body.remove,
        discard=body.discard,
    )
    return action_response(result)


async def list_files(request: Request) -> JSONResponse:
    server = daemon_server(request)
    sid = path_param(request, "sid")
    work_dir = server.session_work_dir(sid)
    if work_dir is None:
        return not_found_response("session not found")
    root = Path(work_dir).resolve()
    rel = query_param(request, "path")
    try:
        payload = list_workspace_directory(root, rel)
    except WorkspacePathError as e:
        return error_response(str(e), e.status_code)
    return JSONResponse(payload)
