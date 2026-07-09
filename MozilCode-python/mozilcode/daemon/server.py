"""Starlette-based daemon server that exposes the headless Agent over HTTP + WS.

Endpoints:
  GET  /api/health            → health check
  POST /api/session           → create a new session, returns session_id
  GET  /api/sessions          → list active sessions
  POST /api/task              → start a task (prompt), returns task_id
  WS   /api/stream/{sid}      → stream AgentEvents for a session
  POST /api/permission/{sid}  → resolve a permission request
  POST /api/askuser/{sid}     → resolve an ask_user request
  POST /api/compact/{sid}     → trigger manual compact
  DELETE /api/session/{sid}   → close a session
"""

from __future__ import annotations

import logging

from starlette.applications import Starlette

from mozilcode.config import load_config, AppConfig
from mozilcode.config.validator import ConfigError
from mozilcode.hooks import HookEngine, load_hooks

from mozilcode.daemon.routes.core import build_routes
from mozilcode.daemon.server_state import DaemonServer
from mozilcode.daemon.session.store import SessionStore
from mozilcode.a2a.bridge import A2ABridge

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    config: AppConfig | None,
    work_dir: str,
    hook_engine: HookEngine | None = None,
    session_store: SessionStore | None = None,
) -> Starlette:
    """Create the Starlette application with all routes wired."""
    server = DaemonServer(config, work_dir, hook_engine, session_store=session_store)
    a2a_bridge = A2ABridge(server)

    app = Starlette(routes=build_routes())
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

    app = create_app(config, wd, hook_engine)

    log.info("Starting MozilCode daemon on %s:%d (work_dir=%s)", host, port, wd)
    uvicorn.run(app, host=host, port=port, log_level="info")
