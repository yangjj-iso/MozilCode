from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class HttpRouteSpec:
    path: str
    endpoint: Callable[..., Any]
    methods: tuple[str, ...]


@dataclass(frozen=True)
class WebSocketRouteSpec:
    path: str
    endpoint: Callable[..., Any]


HTTP_ROUTES: tuple[HttpRouteSpec, ...] = (
    HttpRouteSpec("/.well-known/agent-card.json", a2a_agent_card, ("GET",)),
    HttpRouteSpec("/a2a/agent-card.json", a2a_agent_card, ("GET",)),
    HttpRouteSpec("/a2a/rpc", a2a_rpc, ("POST",)),
    HttpRouteSpec("/a2a/message:send", a2a_message_send, ("POST",)),
    HttpRouteSpec("/a2a/tasks/{task_id}", a2a_task_get, ("GET",)),
    HttpRouteSpec("/a2a/tasks/{task_id}:cancel", a2a_task_cancel, ("POST",)),
    HttpRouteSpec("/api/health", health, ("GET",)),
    HttpRouteSpec("/api/session", create_session, ("POST",)),
    HttpRouteSpec("/api/sessions", list_sessions, ("GET",)),
    HttpRouteSpec("/api/task", start_task, ("POST",)),
    HttpRouteSpec("/api/session/{sid}/status", session_status, ("GET",)),
    HttpRouteSpec("/api/session/{sid}/mode", set_session_mode, ("POST",)),
    HttpRouteSpec("/api/session/{sid}/cancel", cancel_active_task, ("POST",)),
    HttpRouteSpec("/api/session/{sid}/tasks", list_background_tasks, ("GET",)),
    HttpRouteSpec(
        "/api/session/{sid}/tasks/{task_id}/cancel",
        cancel_background_task,
        ("POST",),
    ),
    HttpRouteSpec("/api/session/{sid}/worktrees", list_worktrees, ("GET",)),
    HttpRouteSpec("/api/session/{sid}/worktrees", create_worktree, ("POST",)),
    HttpRouteSpec(
        "/api/session/{sid}/worktrees/{name:path}/enter",
        enter_worktree,
        ("POST",),
    ),
    HttpRouteSpec("/api/session/{sid}/worktrees/exit", exit_worktree, ("POST",)),
    HttpRouteSpec("/api/permission/{sid}", resolve_permission, ("POST",)),
    HttpRouteSpec("/api/askuser/{sid}", resolve_askuser, ("POST",)),
    HttpRouteSpec("/api/compact/{sid}", manual_compact, ("POST",)),
    HttpRouteSpec("/api/session/{sid}", session_info, ("GET",)),
    HttpRouteSpec("/api/session/{sid}", close_session, ("DELETE",)),
    HttpRouteSpec("/api/fs/{sid}", list_files, ("GET",)),
)

WEBSOCKET_ROUTES: tuple[WebSocketRouteSpec, ...] = (
    WebSocketRouteSpec("/api/stream/{sid}", stream_events),
)


def build_routes() -> list[BaseRoute]:
    routes: list[BaseRoute] = [
        Route(spec.path, spec.endpoint, methods=list(spec.methods))
        for spec in HTTP_ROUTES
    ]
    routes.extend(
        WebSocketRoute(spec.path, spec.endpoint)
        for spec in WEBSOCKET_ROUTES
    )
    return routes
