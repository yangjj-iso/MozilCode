"""Starlette 请求上下文取值辅助。

取 daemon server、A2A bridge、path/query 参数。"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request


def daemon_server(scope: Any) -> Any:
    return scope.app.state.server


def a2a_bridge(scope: Any) -> Any:
    return scope.app.state.a2a_bridge


def path_param(scope: Any, name: str) -> str:
    return str(scope.path_params[name])


def query_param(request: Request, name: str, default: str = "") -> str:
    value = request.query_params.get(name)
    return default if value is None else value
