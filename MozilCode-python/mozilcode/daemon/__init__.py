"""MozilCode local daemon: exposes the headless Agent over HTTP + WebSocket.

This package wraps mozilcode-core (which is already headless) in a local
server that CLI helpers, A2A adapters, mobile clients, or other tools can connect to.

Architecture:

    Client (CLI/A2A/Mobile)
        │  HTTP POST /api/task        → start a task
        │  WS   /api/stream/{task_id} → stream events
        │  HTTP POST /api/permission  → resolve permission request
        │  HTTP POST /api/askuser     → resolve ask_user request
        ▼
    DaemonServer (this package)
        │  creates Agent, drives run(), serializes events
        ▼
    mozilcode-core (agent.py, already headless)
"""

from mozilcode.daemon.server import create_app, run_daemon
from mozilcode.daemon.server_state import DaemonServer

__all__ = ["DaemonServer", "create_app", "run_daemon"]
