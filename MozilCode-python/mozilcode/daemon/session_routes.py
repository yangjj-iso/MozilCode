from __future__ import annotations

import json
import logging
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from mozilcode.agent import ErrorEvent
from mozilcode.client import LLMError
from mozilcode.context import compute_compact_threshold
from mozilcode.daemon.config_settings import (
    USER_CONFIG_FILE,
    config_from_settings_payload,
    public_config,
    write_user_config,
)
from mozilcode.daemon.serialize import serialize_event
from mozilcode.daemon.workspace_payloads import (
    WorkspacePathError,
    list_workspace_directory,
    task_to_dict,
    worktree_to_dict,
)
from mozilcode.validator import ConfigError

log = logging.getLogger(__name__)


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


async def config_status(request: Request) -> JSONResponse:
    server = request.app.state.server
    return JSONResponse(public_config(server.config))


async def save_config(request: Request) -> JSONResponse:
    server = request.app.state.server
    try:
        body = await request.json()
        raw = config_from_settings_payload(body or {}, server.config)
        server.config = write_user_config(raw)
        await server.invalidate_idle_agents()
    except (ConfigError, ValueError, TypeError) as e:
        return JSONResponse(public_config(server.config, str(e)), status_code=400)
    except Exception as e:
        log.exception("Failed to save config")
        return JSONResponse(public_config(server.config, str(e)), status_code=500)
    return JSONResponse(public_config(server.config))


async def create_session(request: Request) -> JSONResponse:
    server = request.app.state.server
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if body is not None and not isinstance(body, dict):
        return JSONResponse({"error": "JSON object is required"}, status_code=400)
    session_id = body.get("session_id") if body else None
    work_dir = body.get("work_dir") if body else None
    try:
        sid = await server.init_session(session_id, work_dir)
    except ValueError as e:
        return JSONResponse({"error": str(e), "configured": server.config is not None}, status_code=400)
    return JSONResponse({"session_id": sid, **server.session_info(sid)})


async def list_sessions(request: Request) -> JSONResponse:
    server = request.app.state.server
    return JSONResponse({"sessions": server.list_session_infos()})


async def session_info(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    if not server.has_session(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
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
        return JSONResponse({"error": "session not found"}, status_code=404)
    status = server.status(sid)
    status["agent_ready"] = True
    return JSONResponse(status)


async def set_session_mode(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    mode = (body.get("mode") or "").strip()
    if not mode:
        return JSONResponse({"error": "mode is required"}, status_code=400)
    try:
        status = await server.set_permission_mode(sid, mode)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(status)


async def cancel_active_task(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    if not server.has_session(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    cancelled = server.cancel_active_task(sid)
    return JSONResponse({"cancelled": cancelled})


async def list_background_tasks(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    tasks = deps.task_manager.list_tasks() if deps else []
    return JSONResponse({"tasks": [task_to_dict(t) for t in tasks]})


async def cancel_background_task(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    task_id = request.path_params["task_id"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    if deps is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return JSONResponse({"cancelled": deps.task_manager.cancel(task_id)})


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
    body = await request.json()
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
    body = await request.json()
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


async def start_task(request: Request) -> JSONResponse:
    server = request.app.state.server
    body = await request.json()
    sid = body.get("session_id")
    prompt = body.get("prompt", "")
    if not sid or not prompt:
        return JSONResponse(
            {"error": "session_id and prompt are required"}, status_code=400
        )
    try:
        task_id = await server.start_task(sid, prompt)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return JSONResponse({"task_id": task_id, "session_id": sid})


async def resolve_permission(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    request_id = body.get("request_id", "")
    response = body.get("response", "deny")
    ok = await server.resolve_permission(sid, request_id, response)
    if not ok:
        return JSONResponse({"error": "request not found"}, status_code=404)
    return JSONResponse({"resolved": True})


async def resolve_askuser(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    request_id = body.get("request_id", "")
    answers = body.get("answers", {})
    ok = await server.resolve_askuser(sid, request_id, answers)
    if not ok:
        return JSONResponse({"error": "request not found"}, status_code=404)
    return JSONResponse({"resolved": True})


async def manual_compact(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    await server.ensure_agent(sid)
    agent = server.get_agent(sid)
    conv = server.get_conversation(sid)
    if agent is None or conv is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    before_tokens = conv.current_tokens()
    server.emit_event(sid, {
        "type": "CompactStarted",
        "data": {
            "current_tokens": before_tokens,
            "threshold": max(0, compute_compact_threshold(agent.context_window, manual=True)),
            "context_window": agent.context_window,
            "message": "正在压缩上下文",
        },
    })
    result = await agent.manual_compact(conv)
    event = serialize_event(result)
    server.emit_event(sid, event)
    if not isinstance(result, ErrorEvent):
        server.emit_event(sid, {
            "type": "UsageEvent",
            "data": {
                "input_tokens": agent.total_input_tokens,
                "output_tokens": agent.total_output_tokens,
                "context_tokens": conv.current_tokens(),
            },
        })
    server.persist_events(sid)
    if isinstance(result, ErrorEvent):
        return JSONResponse({"error": result.message}, status_code=400)
    return JSONResponse({
        "type": type(result).__name__,
        "data": event.get("data", {}),
        "status": server.status(sid),
    })


async def close_session(request: Request) -> JSONResponse:
    server = request.app.state.server
    sid = request.path_params["sid"]
    await server.close_session(sid)
    return JSONResponse({"closed": True})
