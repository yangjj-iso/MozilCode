from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.request_body import read_json_object
from mozilcode.daemon.workspace_payloads import (
    WorkspacePathError,
    list_workspace_directory,
)


async def list_worktrees(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    result = await server.list_worktrees(sid)
    return JSONResponse(result.payload, status_code=result.status_code)


async def create_worktree(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    name = (body.get("name") or "").strip()
    base_branch = (body.get("base_branch") or "HEAD").strip()
    result = await server.create_worktree(sid, name, base_branch)
    return JSONResponse(result.payload, status_code=result.status_code)


async def enter_worktree(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    name = request.path_params["name"]
    result = await server.enter_worktree(sid, name)
    return JSONResponse(result.payload, status_code=result.status_code)


async def exit_worktree(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    remove = bool(body.get("remove", False))
    discard = bool(body.get("discard", False))
    result = await server.exit_worktree(sid, remove=remove, discard=discard)
    return JSONResponse(result.payload, status_code=result.status_code)


async def list_files(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    work_dir = server.session_work_dir(sid)
    if work_dir is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    root = Path(work_dir).resolve()
    rel = request.query_params.get("path", "") or ""
    try:
        payload = list_workspace_directory(root, rel)
    except WorkspacePathError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status_code)
    return JSONResponse(payload)
