"""Starlette Daemon 服务。

创建 app、鉴权/Origin 中间件，run_daemon 启动入口。"""

from __future__ import annotations

import logging
import os
import hmac
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware

from mozilcode.config import load_config, AppConfig
from mozilcode.config.validator import ConfigError
from mozilcode.hooks import HookEngine, load_hooks

from mozilcode.daemon.routes.core import build_routes
from mozilcode.daemon.server_state import DaemonServer
from mozilcode.daemon.session.store import SessionStore
from mozilcode.a2a.bridge import A2ABridge

log = logging.getLogger(__name__)


class OriginGuardMiddleware:
    """Reject browser HTTP/WebSocket requests from untrusted origins."""

    def __init__(self, app, allowed_origins: list[str]):
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("latin-1")
        if origin and origin not in self.allowed_origins:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send({
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error":"origin is not allowed"}',
                })
            return

        await self.app(scope, receive, send)


class DaemonTokenAuthMiddleware:
    """Protect daemon HTTP and WebSocket APIs with one local bearer token."""

    PUBLIC_PATHS = frozenset({
        "/api/health",
        "/.well-known/agent-card.json",
        "/a2a/agent-card.json",
    })

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        scope_type = scope["type"]
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if scope.get("path", "") in self.PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        supplied = self._http_token(scope) if scope_type == "http" else self._ws_token(scope)
        if not supplied or not hmac.compare_digest(supplied, self.token):
            if scope_type == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error":"daemon authentication required"}',
                })
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _http_token(scope) -> str:
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, _, value = authorization.partition(" ")
        return value if scheme.lower() == "bearer" else ""

    @staticmethod
    def _ws_token(scope) -> str:
        query = parse_qs(scope.get("query_string", b"").decode("ascii", errors="ignore"))
        values = query.get("token", [])
        return values[0] if values else ""

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    config: AppConfig | None,
    work_dir: str,
    hook_engine: HookEngine | None = None,
    session_store: SessionStore | None = None,
    cors_origins: list[str] | None = None,
    auth_token: str | None = None,
) -> Starlette:
    """Create the Starlette application with all routes wired."""
    server = DaemonServer(config, work_dir, hook_engine, session_store=session_store)
    a2a_bridge = A2ABridge(server)

    app = Starlette(routes=build_routes())
    configured_token = auth_token
    if configured_token is None:
        configured_token = os.environ.get("MOZILCODE_DAEMON_TOKEN", "").strip()
    if configured_token:
        app.add_middleware(DaemonTokenAuthMiddleware, token=configured_token)
    configured_origins = cors_origins
    if configured_origins is None:
        configured_origins = [
            origin.strip()
            for origin in os.environ.get("MOZILCODE_CORS_ORIGINS", "").split(",")
            if origin.strip()
        ]
    if configured_origins:
        app.add_middleware(OriginGuardMiddleware, allowed_origins=configured_origins)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=configured_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
            allow_credentials=False,
        )
    app.state.server = server
    app.state.a2a_bridge = a2a_bridge

    return app


def run_daemon(host: str = "127.0.0.1", port: int = 7800, work_dir: str | None = None) -> None:
    """Entry point: load config and start the daemon."""
    import uvicorn
    import os

    wd = work_dir or os.getcwd()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    try:
        config = load_config()
    except ConfigError as e:
        log.warning("Starting without model config: %s", e)
        config = None

    try:
        hooks = load_hooks(config.raw_hooks if config is not None else [])
    except Exception as e:
        log.warning("Hook loading failed: %s", e)
        hooks = []

    hook_engine = HookEngine(hooks) if hooks else None
    auth_token = os.environ.get("MOZILCODE_DAEMON_TOKEN", "").strip()
    if not _is_loopback_host(host) and not auth_token:
        raise RuntimeError(
            "MOZILCODE_DAEMON_TOKEN is required when daemon host is not localhost"
        )

    origins = os.environ.get(
        "MOZILCODE_CORS_ORIGINS",
        "http://localhost:1420,http://127.0.0.1:1420,tauri://localhost",
    )
    app = create_app(
        config,
        wd,
        hook_engine,
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        auth_token=auth_token,
    )

    log.info("Starting MozilCode daemon on %s:%d (work_dir=%s)", host, port, wd)
    uvicorn.run(app, host=host, port=port, log_level="info")


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    return normalized == "localhost" or normalized == "::1" or normalized.startswith("127.")
