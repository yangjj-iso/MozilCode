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

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from mewcode.config import load_config, AppConfig, WorktreeConfig
from mewcode.client import create_client, resolve_context_window
from mewcode.conversation import ConversationManager
from mewcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from mewcode.tools import create_default_registry
from mewcode.tools.impl.tool_search import ToolSearchTool
from mewcode.tools.ask_user import AskUserTool
from mewcode.agents.loader import AgentLoader
from mewcode.agents.task_manager import TaskManager
from mewcode.agents.trace import TraceManager
from mewcode.tools.agent_tool import AgentTool
from mewcode.teams.manager import TeamManager
from mewcode.tools.team_create import TeamCreateTool
from mewcode.tools.team_delete import TeamDeleteTool
from mewcode.worktree import WorktreeManager
from mewcode.memory.instructions import load_instructions
from mewcode.hooks import HookEngine, load_hooks
from mewcode.agent import Agent, PermissionResponse

from mewcode.daemon.serialize import serialize_event
from mewcode.daemon.session import SessionManager

log = logging.getLogger(__name__)

# On-disk store so conversations survive daemon restarts. Each session lives in
# its own folder: meta.json (id/work_dir/created_at/title) + events.jsonl
# (append-only serialized events used to replay the conversation on connect).
_SESSIONS_DIR = Path.home() / ".mewcode" / "daemon_sessions"

# GUI-managed settings (MCP servers added via the UI, disabled skills, ...).
_GUI_SETTINGS_FILE = Path.home() / ".mewcode" / "gui_settings.json"


def _session_dir(sid: str) -> Path:
    return _SESSIONS_DIR / sid


def _load_gui_settings() -> dict:
    try:
        d = json.loads(_GUI_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("mcp_servers", [])
            d.setdefault("disabled_skills", [])
            return d
    except Exception:
        pass
    return {"mcp_servers": [], "disabled_skills": []}


def _save_gui_settings(data: dict) -> None:
    try:
        _GUI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GUI_SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Failed to save gui settings: %s", e)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

@dataclass
class AgentDeps:
    """Container for subsystem references created alongside an Agent."""

    task_manager: TaskManager
    team_manager: TeamManager
    trace_manager: TraceManager
    agent_loader: AgentLoader
    worktree_manager: WorktreeManager
    provider: Any


async def create_agent_from_config(
    config: AppConfig,
    work_dir: str,
    permission_mode: PermissionMode,
    hook_engine: HookEngine | None = None,
) -> tuple[Agent, AgentDeps]:
    """Create a fully-wired Agent from AppConfig. Returns (agent, deps)."""
    provider = config.providers[0]
    client = create_client(provider)
    await resolve_context_window(provider)

    home = Path.home()
    checker = PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(work_dir),
        rule_engine=RuleEngine(
            user_rules_path=home / ".mewcode" / "permissions.yaml",
            project_rules_path=Path(work_dir) / ".mewcode" / "permissions.yaml",
            local_rules_path=Path(work_dir) / ".mewcode" / "permissions.local.yaml",
        ),
        mode=permission_mode,
    )

    instructions = load_instructions(work_dir)
    registry = create_default_registry()
    registry.register(ToolSearchTool(registry, protocol=provider.protocol))
    registry.register(AskUserTool())

    from mewcode.tools.exit_plan_mode import ExitPlanModeTool
    registry.register(ExitPlanModeTool())

    agent = Agent(
        client=client,
        registry=registry,
        protocol=provider.protocol,
        work_dir=work_dir,
        permission_checker=checker,
        context_window=provider.get_context_window(),
        instructions_content=instructions,
        hook_engine=hook_engine,
    )

    wt_cfg = config.worktree or WorktreeConfig()
    wt_manager = WorktreeManager(
        repo_root=work_dir,
        symlink_directories=wt_cfg.symlink_directories,
    )
    trace_manager = TraceManager()
    task_manager = TaskManager()
    agent_loader = AgentLoader(work_dir, enable_verification=config.enable_verification_agent)
    agent_loader.load_all()
    team_manager = TeamManager(worktree_manager=wt_manager, trace_manager=trace_manager)

    agent_tool = AgentTool(
        agent_loader=agent_loader,
        task_manager=task_manager,
        trace_manager=trace_manager,
        parent_agent=agent,
        enable_fork=config.enable_fork,
        provider_config=provider,
        worktree_manager=wt_manager,
        team_manager=team_manager,
    )
    registry.register(agent_tool)
    registry.register(TeamCreateTool(
        team_manager=team_manager,
        parent_agent=agent,
        teammate_mode="in-process",
        is_interactive=False,
        enable_coordinator_mode=config.enable_coordinator_mode,
    ))
    registry.register(TeamDeleteTool(team_manager=team_manager, parent_agent=agent))

    def drain_mailbox() -> list[str]:
        return team_manager.drain_lead_mailbox()

    agent.notification_fn = drain_mailbox

    deps = AgentDeps(
        task_manager=task_manager,
        team_manager=team_manager,
        trace_manager=trace_manager,
        agent_loader=agent_loader,
        worktree_manager=wt_manager,
        provider=provider,
    )
    return agent, deps


# ---------------------------------------------------------------------------
# Daemon server
# ---------------------------------------------------------------------------

class DaemonServer:
    """Holds shared state across HTTP/WS requests."""

    def __init__(self, config: AppConfig, work_dir: str, hook_engine: HookEngine | None = None):
        self.config = config
        self.work_dir = work_dir
        self.hook_engine = hook_engine
        self.session_mgr = SessionManager()
        # Cache: session_id → (agent, deps, conversation)
        self._agents: dict[str, tuple[Agent, AgentDeps, ConversationManager]] = {}
        # Per-session append-only event log (serialized events). WS streamers
        # replay it from the start on connect (so switching/reopening a session
        # shows its full history) then tail it live. A shared log also lets
        # multiple clients watch the same session without cancelling each other
        # (which previously caused a reconnect ping-pong storm).
        self._event_logs: dict[str, list[dict | None]] = {}
        # Active agent task tracking: session_id → asyncio.Task
        self._tasks: dict[str, asyncio.Task] = {}
        # Per-session metadata (work_dir/created_at/title), for live and
        # disk-loaded sessions alike.
        self._session_meta: dict[str, dict] = {}
        # How many events of each session's log are already flushed to disk.
        self._persisted_count: dict[str, int] = {}
        # Currently-pending permission/askuser prompt events, keyed by request_id.
        # Used to re-show genuinely-open prompts to a (re)connecting client while
        # NOT re-showing historical (already-answered) ones during log replay.
        self._pending_prompts: dict[str, dict[str, dict]] = {}
        self._load_persisted_sessions()

    def _load_persisted_sessions(self) -> None:
        """Load previously persisted sessions from disk so past conversations
        survive a daemon restart. Agents are created lazily on first use."""
        try:
            _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.warning("Cannot create sessions dir: %s", e)
            return
        for d in sorted(_SESSIONS_DIR.iterdir(), key=lambda p: p.name):
            if not d.is_dir():
                continue
            sid = d.name
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                events: list[dict | None] = []
                ev_path = d / "events.jsonl"
                if ev_path.exists():
                    for line in ev_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line:
                            events.append(json.loads(line))
                self._event_logs[sid] = events
                self._session_meta[sid] = meta
                self._persisted_count[sid] = len(events)
            except Exception as e:
                log.warning("Failed to load session %s: %s", sid, e)
        if self._session_meta:
            log.info("Loaded %d persisted session(s)", len(self._session_meta))

    def _persist_meta(self, sid: str) -> None:
        try:
            d = _session_dir(sid)
            d.mkdir(parents=True, exist_ok=True)
            (d / "meta.json").write_text(
                json.dumps(self._session_meta.get(sid, {}), ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("Persist meta failed for %s: %s", sid, e)

    def _persist_events(self, sid: str) -> None:
        """Append newly-produced events for a session to its events.jsonl."""
        log_list = self._event_logs.get(sid)
        if log_list is None:
            return
        start = self._persisted_count.get(sid, 0)
        new = [e for e in log_list[start:] if e is not None]
        if not new:
            self._persisted_count[sid] = len(log_list)
            return
        try:
            d = _session_dir(sid)
            d.mkdir(parents=True, exist_ok=True)
            with (d / "events.jsonl").open("a", encoding="utf-8") as f:
                for e in new:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            self._persisted_count[sid] = len(log_list)
        except Exception as e:
            log.warning("Persist events failed for %s: %s", sid, e)

    async def init_session(
        self, session_id: str | None = None, work_dir: str | None = None
    ) -> str:
        """Create a new Agent session in the given workspace. Returns session_id."""
        sid = session_id or uuid.uuid4().hex[:12]
        wd = work_dir or self.work_dir
        if not Path(wd).is_dir():
            raise ValueError(f"workspace not found: {wd}")
        mode = PermissionMode(self.config.permission_mode)
        agent, deps = await create_agent_from_config(
            self.config, wd, mode, self.hook_engine
        )
        conv = ConversationManager()
        self._agents[sid] = (agent, deps, conv)
        self._event_logs[sid] = []
        self._session_meta[sid] = {"work_dir": wd, "created_at": time.time(), "title": ""}
        self._persisted_count[sid] = 0
        self._persist_meta(sid)
        await self.session_mgr.create_session(sid, agent, conv)
        log.info("Session %s initialized (work_dir=%s)", sid, wd)
        return sid

    async def ensure_agent(self, sid: str) -> bool:
        """Make sure an Agent exists for a session, creating one lazily for
        sessions that were loaded from disk. Returns True if usable."""
        if sid in self._agents:
            return True
        meta = self._session_meta.get(sid)
        if meta is None:
            return False
        wd = meta.get("work_dir") or self.work_dir
        if not Path(wd).is_dir():
            wd = self.work_dir
        mode = PermissionMode(self.config.permission_mode)
        agent, deps = await create_agent_from_config(
            self.config, wd, mode, self.hook_engine
        )
        conv = ConversationManager()
        self._agents[sid] = (agent, deps, conv)
        if sid not in self._event_logs:
            self._event_logs[sid] = []
        await self.session_mgr.create_session(sid, agent, conv)
        log.info("Session %s reactivated (work_dir=%s)", sid, wd)
        return True

    def session_info(self, sid: str) -> dict:
        meta = self._session_meta.get(sid, {})
        return {"id": sid, "work_dir": meta.get("work_dir", self.work_dir), "title": meta.get("title", "")}

    def get_agent(self, sid: str) -> Agent | None:
        entry = self._agents.get(sid)
        return entry[0] if entry else None

    def get_conversation(self, sid: str) -> ConversationManager | None:
        entry = self._agents.get(sid)
        return entry[2] if entry else None

    def get_deps(self, sid: str) -> AgentDeps | None:
        entry = self._agents.get(sid)
        return entry[1] if entry else None

    def get_event_log(self, sid: str) -> list[dict | None] | None:
        return self._event_logs.get(sid)

    def _emit(self, sid: str, event: dict | None) -> None:
        """Append a serialized event to the session log. WS streamers tail it."""
        log_list = self._event_logs.get(sid)
        if log_list is not None:
            log_list.append(event)

    async def start_task(self, sid: str, prompt: str) -> str:
        """Start agent.run() as a background task. Returns task_id."""
        # Lazily reactivate a session loaded from disk.
        await self.ensure_agent(sid)
        agent = self.get_agent(sid)
        conv = self.get_conversation(sid)
        log_list = self.get_event_log(sid)
        if agent is None or conv is None or log_list is None:
            raise ValueError(f"Session {sid} not found")

        # Use the first prompt as the session title (for the sidebar).
        meta = self._session_meta.get(sid)
        if meta is not None and not meta.get("title"):
            meta["title"] = prompt[:40]
            self._persist_meta(sid)

        task_id = uuid.uuid4().hex[:8]

        async def run_agent():
            """Drive agent.run(), append serialized events to the session log."""
            try:
                conv.add_user_message(prompt)
                # Record the user's prompt in the log too, so replay (history)
                # reconstructs both sides of the conversation, not just the agent.
                self._emit(sid, {"type": "UserMessage", "task_id": task_id, "data": {"content": prompt}})
                async for event in agent.run(conv):
                    # Track permission futures for later resolution
                    if hasattr(event, "future") and event.future is not None:
                        request_id = str(id(event.future))
                        session = await self.session_mgr.get_session(sid)
                        if session:
                            session.register_future(request_id, event.future)

                    msg = serialize_event(event, task_id=task_id)
                    # Track open prompts so a (re)connecting client can be shown
                    # the ones still awaiting an answer (not the answered history).
                    if msg.get("type") in ("PermissionRequest", "AskUserRequest"):
                        rid = (msg.get("data") or {}).get("request_id")
                        if rid:
                            self._pending_prompts.setdefault(sid, {})[rid] = msg
                    self._emit(sid, msg)

                self._emit(sid, {"type": "LoopComplete", "task_id": task_id, "data": {}})
            except Exception as e:
                log.exception("Agent task %s failed", task_id)
                self._emit(sid, {
                    "type": "ErrorEvent",
                    "task_id": task_id,
                    "data": {"message": str(e)},
                })
            finally:
                # Flush this turn's events to disk so the conversation survives a
                # daemon restart.
                self._persist_events(sid)

        task = asyncio.create_task(run_agent(), name=f"agent-{sid}-{task_id}")
        self._tasks[sid] = task
        return task_id

    async def resolve_permission(
        self, sid: str, request_id: str, response: str
    ) -> bool:
        """Resolve a pending permission request. response: allow|deny|allow_always."""
        session = await self.session_mgr.get_session(sid)
        if session is None:
            return False
        perm_response = PermissionResponse(response)
        ok = session.resolve_future(request_id, perm_response)
        if ok:
            self._pending_prompts.get(sid, {}).pop(request_id, None)
            # Notify any live clients so the inline prompt clears everywhere.
            self._emit(sid, {"type": "PermissionResolved", "data": {"request_id": request_id}})
        return ok

    async def resolve_askuser(
        self, sid: str, request_id: str, answers: dict[str, str]
    ) -> bool:
        """Resolve a pending ask_user request."""
        session = await self.session_mgr.get_session(sid)
        if session is None:
            return False
        ok = session.resolve_future(request_id, answers)
        if ok:
            self._pending_prompts.get(sid, {}).pop(request_id, None)
            self._emit(sid, {"type": "AskUserResolved", "data": {"request_id": request_id}})
        return ok

    async def close_session(self, sid: str) -> None:
        """Clean up a session."""
        task = self._tasks.pop(sid, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Detach the log and append a None sentinel so any live streamers (which
        # hold a reference to the list object) break out; new connects then see
        # the session as gone and receive a SessionNotFound signal.
        log_list = self._event_logs.pop(sid, None)
        if log_list is not None:
            log_list.append(None)

        await self.session_mgr.close_session(sid)
        self._agents.pop(sid, None)
        self._session_meta.pop(sid, None)
        self._persisted_count.pop(sid, None)
        # Remove the on-disk record so a deleted conversation stays deleted.
        try:
            import shutil
            shutil.rmtree(_session_dir(sid), ignore_errors=True)
        except Exception:
            pass
        log.info("Session %s closed", sid)


# ---------------------------------------------------------------------------
# HTTP / WS handlers
# ---------------------------------------------------------------------------

async def health(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    return JSONResponse(
        {"status": "ok", "service": "mewcode-daemon", "work_dir": server.work_dir}
    )


async def create_session(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    body = await request.json()
    session_id = body.get("session_id") if body else None
    work_dir = body.get("work_dir") if body else None
    try:
        sid = await server.init_session(session_id, work_dir)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"session_id": sid, **server.session_info(sid)})


async def list_sessions(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    # Include disk-loaded (not-yet-reactivated) sessions, newest first.
    sids = list(server._event_logs.keys())
    sids.sort(key=lambda s: server._session_meta.get(s, {}).get("created_at", 0), reverse=True)
    return JSONResponse({"sessions": [server.session_info(s) for s in sids]})


async def session_info(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    if sid not in server._event_logs:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return JSONResponse(server.session_info(sid))


async def list_files(request: Request) -> JSONResponse:
    """List a directory inside a session's workspace (for the file-tree panel).

    Query param ``path`` is relative to the session's work_dir; the resolved
    target must stay within the workspace (no arbitrary filesystem browsing).
    """
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    meta = server._session_meta.get(sid)
    if meta is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    root = Path(meta.get("work_dir") or server.work_dir).resolve()
    rel = request.query_params.get("path", "") or ""
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return JSONResponse({"error": "path outside workspace"}, status_code=400)
    if not target.is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    entries = []
    try:
        for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            entries.append({"name": p.name, "is_dir": p.is_dir()})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"root": str(root), "entries": entries})


async def start_task(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    body = await request.json()
    sid = body.get("session_id")
    prompt = body.get("prompt", "")
    if not sid or not prompt:
        return JSONResponse(
            {"error": "session_id and prompt are required"}, status_code=400
        )
    try:
        task_id = await server.start_task(sid, prompt)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return JSONResponse({"task_id": task_id, "session_id": sid})


async def resolve_permission(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    request_id = body.get("request_id", "")
    response = body.get("response", "deny")
    ok = await server.resolve_permission(sid, request_id, response)
    if not ok:
        return JSONResponse({"error": "request not found"}, status_code=404)
    return JSONResponse({"resolved": True})


async def resolve_askuser(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    request_id = body.get("request_id", "")
    answers = body.get("answers", {})
    ok = await server.resolve_askuser(sid, request_id, answers)
    if not ok:
        return JSONResponse({"error": "request not found"}, status_code=404)
    return JSONResponse({"resolved": True})


async def manual_compact(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    agent = server.get_agent(sid)
    conv = server.get_conversation(sid)
    if agent is None or conv is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    result = await agent.manual_compact(conv)
    return JSONResponse({
        "type": type(result).__name__,
        "data": str(result),
    })


async def close_session(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    await server.close_session(sid)
    return JSONResponse({"closed": True})


async def stream_events(websocket: WebSocket) -> None:
    """WebSocket: replay a session's full event history, then tail it live.

    On connect the client receives every event recorded for the session so far
    (so switching to / reopening a conversation shows its full content), then
    continues to receive new events as they are produced. The event log is
    shared and append-only, so multiple clients can watch the same session
    concurrently — no connection cancels another (which previously caused a
    reconnect ping-pong storm). Client may send {"action": "cancel"} to abort
    the running task.
    """
    await websocket.accept()
    sid = websocket.path_params["sid"]
    server: DaemonServer = websocket.app.state.server

    log_list = server.get_event_log(sid)
    if log_list is None:
        # Session unknown (typically the daemon was restarted since the client
        # last connected). Emit an explicit, typed signal plus an application
        # close code so the client can self-heal (recreate a session) instead of
        # hammering blind reconnects forever.
        await websocket.send_json(
            {"type": "SessionNotFound", "data": {"session_id": sid}}
        )
        await websocket.close(code=4404)
        return

    log.info("WS client connected to session %s", sid)
    disconnected = asyncio.Event()

    async def _listen_client() -> None:
        # Watch for client → server messages (cancel) and detect disconnects.
        try:
            while True:
                raw = await websocket.receive_text()
                if not raw:
                    continue
                try:
                    if json.loads(raw).get("action") == "cancel":
                        t = server._tasks.get(sid)
                        if t and not t.done():
                            t.cancel()
                except (json.JSONDecodeError, AttributeError):
                    pass
        except WebSocketDisconnect:
            disconnected.set()
        except Exception:
            disconnected.set()

    listener = asyncio.create_task(_listen_client())
    idx = 0
    replay_marked = False
    try:
        while not disconnected.is_set():
            if idx < len(log_list):
                # Send everything appended since we last looked (replay + live).
                batch = log_list[idx:]
                idx = len(log_list)
                stop = False
                for ev in batch:
                    if ev is None:  # sentinel（会话销毁）
                        stop = True
                        break
                    await websocket.send_json(ev)
                if stop:
                    break
            else:
                if not replay_marked:
                    # History fully replayed. Mark the boundary so the client can
                    # ignore historical permission/askuser prompts, then re-send
                    # any prompt that is *still* awaiting an answer as a live one.
                    replay_marked = True
                    try:
                        await websocket.send_json({"type": "ReplayDone", "data": {}})
                        for ev in list(server._pending_prompts.get(sid, {}).values()):
                            await websocket.send_json(ev)
                    except Exception:
                        pass
                # Idle: poll for new events. 20ms keeps streaming smooth (each
                # tick flushes ALL pending events, so throughput is unbounded)
                # while remaining responsive to disconnects.
                await asyncio.sleep(0.02)
    except WebSocketDisconnect:
        log.info("WS client disconnected from session %s", sid)
    except Exception:
        log.exception("WS stream error for session %s", sid)
    finally:
        listener.cancel()
        try:
            await listener
        except (asyncio.CancelledError, Exception):
            pass
        log.info("WS stream ended for session %s", sid)


async def mcp_list(request: Request) -> JSONResponse:
    return JSONResponse({"servers": _load_gui_settings().get("mcp_servers", [])})


async def mcp_add(request: Request) -> JSONResponse:
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    d = _load_gui_settings()
    servers = [s for s in d.get("mcp_servers", []) if s.get("name") != name]
    servers.append({
        "name": name,
        "command": (body.get("command") or "").strip(),
        "args": (body.get("args") or "").strip(),
        "url": (body.get("url") or "").strip(),
        "enabled": True,
    })
    d["mcp_servers"] = servers
    _save_gui_settings(d)
    return JSONResponse({"ok": True, "servers": servers})


async def mcp_delete(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    d = _load_gui_settings()
    d["mcp_servers"] = [s for s in d.get("mcp_servers", []) if s.get("name") != name]
    _save_gui_settings(d)
    return JSONResponse({"ok": True})


async def mcp_toggle(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    d = _load_gui_settings()
    for s in d.get("mcp_servers", []):
        if s.get("name") == name:
            s["enabled"] = not s.get("enabled", True)
    _save_gui_settings(d)
    return JSONResponse({"ok": True})


async def skills_list(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    disabled = set(_load_gui_settings().get("disabled_skills", []))
    out = []
    try:
        from mewcode.skills.loader import SkillLoader
        loader = SkillLoader(server.work_dir)
        for name, sk in loader.load_all().items():
            out.append({
                "name": name,
                "description": getattr(sk, "description", "") or "",
                "source": loader.get_source_label(name),
                "enabled": name not in disabled,
            })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    out.sort(key=lambda x: x["name"])
    return JSONResponse({"skills": out})


async def skill_toggle(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    d = _load_gui_settings()
    disabled = set(d.get("disabled_skills", []))
    disabled.discard(name) if name in disabled else disabled.add(name)
    d["disabled_skills"] = sorted(disabled)
    _save_gui_settings(d)
    return JSONResponse({"ok": True})


async def skill_create(request: Request) -> JSONResponse:
    body = await request.json()
    name = (body.get("name") or "").strip()
    desc = (body.get("description") or "").strip()
    prompt = body.get("body") or ""
    from mewcode.skills.parser import VALID_NAME_RE
    if not VALID_NAME_RE.match(name):
        return JSONResponse(
            {"error": "名称需为小写字母/数字/连字符，且以字母开头"}, status_code=400
        )
    if not desc:
        return JSONResponse({"error": "描述必填"}, status_code=400)
    skill_dir = Path.home() / ".mewcode" / "skills" / name
    if skill_dir.exists():
        return JSONResponse({"error": "同名技能已存在"}, status_code=400)
    try:
        import yaml
        front = yaml.safe_dump({"name": name, "description": desc}, allow_unicode=True, sort_keys=False).strip()
        content = f"---\n{front}\n---\n\n{prompt.strip()}\n"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


async def skill_delete(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    skill_dir = Path.home() / ".mewcode" / "skills" / name
    if not skill_dir.is_dir():
        return JSONResponse({"error": "只能删除用户创建的技能"}, status_code=400)
    try:
        import shutil
        shutil.rmtree(skill_dir, ignore_errors=True)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


async def serve_gui(request: Request) -> JSONResponse:
    """Serve the embedded GUI HTML at /."""
    from pathlib import Path
    gui_path = Path(__file__).parent.parent / "gui" / "index.html"
    if not gui_path.exists():
        return JSONResponse({"error": "GUI not found"}, status_code=404)
    from starlette.responses import HTMLResponse
    return HTMLResponse(gui_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(config: AppConfig, work_dir: str, hook_engine: HookEngine | None = None) -> Starlette:
    """Create the Starlette application with all routes wired."""
    server = DaemonServer(config, work_dir, hook_engine)

    routes = [
        Route("/", serve_gui, methods=["GET"]),
        Route("/api/health", health, methods=["GET"]),
        Route("/api/session", create_session, methods=["POST"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/task", start_task, methods=["POST"]),
        Route("/api/permission/{sid}", resolve_permission, methods=["POST"]),
        Route("/api/askuser/{sid}", resolve_askuser, methods=["POST"]),
        Route("/api/compact/{sid}", manual_compact, methods=["POST"]),
        Route("/api/session/{sid}", session_info, methods=["GET"]),
        Route("/api/session/{sid}", close_session, methods=["DELETE"]),
        Route("/api/fs/{sid}", list_files, methods=["GET"]),
        Route("/api/settings/mcp", mcp_list, methods=["GET"]),
        Route("/api/settings/mcp", mcp_add, methods=["POST"]),
        Route("/api/settings/mcp/{name}/toggle", mcp_toggle, methods=["POST"]),
        Route("/api/settings/mcp/{name}", mcp_delete, methods=["DELETE"]),
        Route("/api/skills", skills_list, methods=["GET"]),
        Route("/api/skills", skill_create, methods=["POST"]),
        Route("/api/skills/{name}/toggle", skill_toggle, methods=["POST"]),
        Route("/api/skills/{name}", skill_delete, methods=["DELETE"]),
        WebSocketRoute("/api/stream/{sid}", stream_events),
    ]

    app = Starlette(routes=routes)
    app.state.server = server

    # CORS: allow Tauri (tauri://localhost) and browser access
    from starlette.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    config = load_config()

    try:
        hooks = load_hooks(config.raw_hooks)
    except Exception as e:
        log.warning("Hook loading failed: %s", e)
        hooks = []

    hook_engine = HookEngine(hooks) if hooks else None

    app = create_app(config, wd, hook_engine)

    log.info("Starting MewCode daemon on %s:%d (work_dir=%s)", host, port, wd)
    uvicorn.run(app, host=host, port=port, log_level="info")
