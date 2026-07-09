"""Daemon HTTP route handlers — A2A, stream, workspace, and core routing."""

from mozilcode.daemon.routes.core import (
    HTTP_ROUTES,
    WEBSOCKET_ROUTES,
    build_routes,
)

__all__ = ["HTTP_ROUTES", "WEBSOCKET_ROUTES", "build_routes"]
