"""Daemon HTTP 路由包（A2A、stream、workspace 等）。"""

from mozilcode.daemon.routes.core import (
    HTTP_ROUTES,
    WEBSOCKET_ROUTES,
    build_routes,
)

__all__ = ["HTTP_ROUTES", "WEBSOCKET_ROUTES", "build_routes"]
