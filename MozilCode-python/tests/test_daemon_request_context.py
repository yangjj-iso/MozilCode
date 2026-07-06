from __future__ import annotations

from types import SimpleNamespace

from mozilcode.daemon.request_context import (
    a2a_bridge,
    daemon_server,
    path_param,
    query_param,
)


def _scope(**kwargs):
    state = SimpleNamespace(
        server=object(),
        a2a_bridge=object(),
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=state),
        path_params=kwargs.get("path_params", {}),
        query_params=kwargs.get("query_params", {}),
    )


def test_request_context_returns_daemon_state_objects() -> None:
    scope = _scope()

    assert daemon_server(scope) is scope.app.state.server
    assert a2a_bridge(scope) is scope.app.state.a2a_bridge


def test_request_context_reads_path_and_query_params() -> None:
    scope = _scope(
        path_params={"sid": 123},
        query_params={"path": "src", "empty": ""},
    )

    assert path_param(scope, "sid") == "123"
    assert query_param(scope, "path") == "src"
    assert query_param(scope, "empty", "fallback") == ""
    assert query_param(scope, "missing", "fallback") == "fallback"
