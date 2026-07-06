from __future__ import annotations

from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.daemon.request_body import read_json_object
from mozilcode.daemon.workspace_payloads import (
    WorkspacePathError,
    list_workspace_directory,
    worktree_to_dict,
)


async def list_worktrees(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    if deps is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    manager = deps.worktree_manager
    session = manager.get_current_session()
    current_name = session.worktree_name if session else None
    return JSONResponse({
        "current": current_name,
        "worktrees": [worktree_to_dict(wt, current_name) for wt in manager.list_worktrees()],
    })


async def create_worktree(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    name = (body.get("name") or "").strip()
    base_branch = (body.get("base_branch") or "HEAD").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    agent = server.get_agent(sid)
    if deps is None or agent is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    try:
        wt = await deps.worktree_manager.create(name, base_branch)
        session = await deps.worktree_manager.enter(name)
        agent.work_dir = session.worktree_path
        server.update_session_work_dir(sid, session.worktree_path)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"worktree": worktree_to_dict(wt, name), "status": server.status(sid)})


async def enter_worktree(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    name = request.path_params["name"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    agent = server.get_agent(sid)
    if deps is None or agent is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    try:
        session = await deps.worktree_manager.enter(name)
        agent.work_dir = session.worktree_path
        server.update_session_work_dir(sid, session.worktree_path)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"entered": True, "status": server.status(sid)})


async def exit_worktree(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    parsed = await read_json_object(request)
    if not parsed.ok:
        return parsed.error_response()
    body = parsed.payload
    remove = bool(body.get("remove", False))
    discard = bool(body.get("discard", False))
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    agent = server.get_agent(sid)
    if deps is None or agent is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    manager = deps.worktree_manager
    session = manager.get_current_session()
    if session is None:
        return JSONResponse({"error": "not in a worktree"}, status_code=400)
    try:
        await manager.exit(
            session.worktree_name,
            action="remove" if remove else "keep",
            discard_changes=discard,
        )
        agent.work_dir = session.original_cwd
        server.update_session_work_dir(sid, session.original_cwd)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"exited": True, "status": server.status(sid)})


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
