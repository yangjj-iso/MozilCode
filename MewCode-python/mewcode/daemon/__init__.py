"""MewCode local daemon: exposes the headless Agent over HTTP + WebSocket.

This package wraps mewcode-core (which is already headless) in a local
server that GUI clients, mobile clients, or other tools can connect to.

Architecture:

    Client (GUI/TUI/Mobile)
        │  HTTP POST /api/task        → start a task
        │  WS   /api/stream/{task_id} → stream events
        │  HTTP POST /api/permission  → resolve permission request
        │  HTTP POST /api/askuser     → resolve ask_user request
        ▼
    DaemonServer (this package)
        │  creates Agent, drives run(), serializes events
        ▼
    mewcode-core (agent.py, already headless)
"""

from mewcode.daemon.server import DaemonServer, create_app, run_daemon

__all__ = ["DaemonServer", "create_app", "run_daemon"]
