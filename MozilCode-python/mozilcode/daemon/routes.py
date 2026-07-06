from __future__ import annotations

from starlette.routing import BaseRoute, Route, WebSocketRoute

from mozilcode.daemon.a2a_routes import (
    a2a_agent_card,
    a2a_message_send,
    a2a_rpc,
    a2a_task_cancel,
    a2a_task_get,
)
from mozilcode.daemon.session_routes import (
    cancel_active_task,
    cancel_background_task,
    close_session,
    create_session,
    health,
    list_background_tasks,
    list_sessions,
    manual_compact,
    resolve_askuser,
    resolve_permission,
    session_info,
    session_status,
    set_session_mode,
    start_task,
)
from mozilcode.daemon.stream_routes import stream_events
from mozilcode.daemon.workspace_routes import (
    create_worktree,
    enter_worktree,
    exit_worktree,
    list_files,
    list_worktrees,
)


def build_routes() -> list[BaseRoute]:
    return [
        Route("/.well-known/agent-card.json", a2a_agent_card, methods=["GET"]),
        Route("/a2a/agent-card.json", a2a_agent_card, methods=["GET"]),
        Route("/a2a/rpc", a2a_rpc, methods=["POST"]),
        Route("/a2a/message:send", a2a_message_send, methods=["POST"]),
        Route("/a2a/tasks/{task_id}", a2a_task_get, methods=["GET"]),
        Route("/a2a/tasks/{task_id}:cancel", a2a_task_cancel, methods=["POST"]),
        Route("/api/health", health, methods=["GET"]),
        Route("/api/session", create_session, methods=["POST"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/task", start_task, methods=["POST"]),
        Route("/api/session/{sid}/status", session_status, methods=["GET"]),
        Route("/api/session/{sid}/mode", set_session_mode, methods=["POST"]),
        Route("/api/session/{sid}/cancel", cancel_active_task, methods=["POST"]),
        Route("/api/session/{sid}/tasks", list_background_tasks, methods=["GET"]),
        Route("/api/session/{sid}/tasks/{task_id}/cancel", cancel_background_task, methods=["POST"]),
        Route("/api/session/{sid}/worktrees", list_worktrees, methods=["GET"]),
        Route("/api/session/{sid}/worktrees", create_worktree, methods=["POST"]),
        Route("/api/session/{sid}/worktrees/{name:path}/enter", enter_worktree, methods=["POST"]),
        Route("/api/session/{sid}/worktrees/exit", exit_worktree, methods=["POST"]),
        Route("/api/permission/{sid}", resolve_permission, methods=["POST"]),
        Route("/api/askuser/{sid}", resolve_askuser, methods=["POST"]),
        Route("/api/compact/{sid}", manual_compact, methods=["POST"]),
        Route("/api/session/{sid}", session_info, methods=["GET"]),
        Route("/api/session/{sid}", close_session, methods=["DELETE"]),
        Route("/api/fs/{sid}", list_files, methods=["GET"]),
        WebSocketRoute("/api/stream/{sid}", stream_events),
    ]
