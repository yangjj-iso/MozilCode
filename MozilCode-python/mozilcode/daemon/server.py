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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from mozilcode.config import load_config, AppConfig, WorktreeConfig
from mozilcode.validator import ConfigError, validate_config_structure
from mozilcode.client import LLMError, create_client, resolve_context_window
from mozilcode.context import compute_compact_threshold
from mozilcode.conversation import ConversationManager
from mozilcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from mozilcode.tools import create_default_registry
from mozilcode.tools.impl.tool_search import ToolSearchTool
from mozilcode.tools.ask_user import AskUserTool
from mozilcode.agents.loader import AgentLoader
from mozilcode.agents.task_manager import TaskManager
from mozilcode.agents.trace import TraceManager
from mozilcode.tools.agent_tool import AgentTool
from mozilcode.teams.manager import TeamManager
from mozilcode.tools.team_create import TeamCreateTool
from mozilcode.tools.team_delete import TeamDeleteTool
from mozilcode.worktree import WorktreeManager
from mozilcode.memory.instructions import load_instructions
from mozilcode.memory.providers import build_memory_hub
from mozilcode.hooks import HookEngine, load_hooks
from mozilcode.agent import Agent, ErrorEvent, PermissionResponse

from mozilcode.daemon.serialize import serialize_event
from mozilcode.daemon.session import SessionManager
from mozilcode.a2a.bridge import A2ABridge, A2AError
from mozilcode.a2a.qq_official import DEFAULT_INTENTS, OfficialQQConfig, create_official_qq_gateway
from mozilcode.a2a.telegram_official import TelegramBotConfig, create_telegram_bot_runner

log = logging.getLogger(__name__)

# On-disk store so conversations survive daemon restarts. Each session lives in
# its own folder: meta.json (id/work_dir/created_at/title) + events.jsonl
# (append-only serialized events used to replay the conversation on connect).
_SESSIONS_DIR = Path.home() / ".mozilcode" / "daemon_sessions"

# GUI-managed settings (MCP servers added via the UI, disabled skills, ...).
_GUI_SETTINGS_FILE = Path.home() / ".mozilcode" / "gui_settings.json"

# First-run model configuration written by the GUI.
_USER_CONFIG_FILE = Path.home() / ".mozilcode" / "config.yaml"

_QQBOT_PROVIDER = "official"
_TELEGRAMBOT_PROVIDER = "telegram-official"


def _session_dir(sid: str) -> Path:
    return _SESSIONS_DIR / sid


def _load_gui_settings() -> dict:
    try:
        d = json.loads(_GUI_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("mcp_servers", [])
            d.setdefault("disabled_skills", [])
            d.setdefault("qqbot", {})
            d.setdefault("telegrambot", {})
            return d
    except Exception:
        pass
    return {"mcp_servers": [], "disabled_skills": [], "qqbot": {}, "telegrambot": {}}


def _save_gui_settings(data: dict) -> None:
    try:
        _GUI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GUI_SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Failed to save gui settings: %s", e)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _coerce_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    return number


def _split_id_list(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        raw = str(value)
        for sep in [",", ";", "，", "；", "\r", "\n", "\t"]:
            raw = raw.replace(sep, " ")
        items = [item.strip() for item in raw.split(" ")]
    clean = {item for item in items if item}
    return clean or None


def _id_list_text(value: Any) -> str:
    ids = _split_id_list(value)
    if not ids:
        return ""
    return "\n".join(sorted(ids))


def _normalize_qqbot_settings(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "provider": _QQBOT_PROVIDER,
        "enabled": _coerce_bool(raw.get("enabled"), False),
        "app_id": str(raw.get("app_id") or "").strip(),
        "app_secret": str(raw.get("app_secret") or "").strip(),
        "command_prefix": str(raw.get("command_prefix") or "/mew").strip(),
        "allowed_users": _id_list_text(raw.get("allowed_users")),
        "allowed_groups": _id_list_text(raw.get("allowed_groups")),
        "intents": _coerce_int(raw.get("intents"), DEFAULT_INTENTS, minimum=0),
    }


def _qqbot_settings_from_payload(body: dict, current: dict | None = None) -> dict:
    current = current if isinstance(current, dict) else {}
    merged = {**current, **(body or {})}
    secret = body.get("app_secret") if isinstance(body, dict) else None
    if secret is None or not str(secret).strip():
        merged["app_secret"] = str(current.get("app_secret") or "").strip()
    return _normalize_qqbot_settings(merged)


def _resolve_qqbot_config(settings: dict | None = None) -> tuple[bool, OfficialQQConfig, dict]:
    data = settings if isinstance(settings, dict) else _load_gui_settings()
    raw = data.get("qqbot") if isinstance(data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    saved = bool(raw)
    normalized = _normalize_qqbot_settings(raw)
    env_cfg = OfficialQQConfig.from_env()
    enabled = _coerce_bool(raw.get("enabled"), False) if saved else OfficialQQConfig.enabled_from_env()

    cfg = OfficialQQConfig.from_env()
    cfg.app_id = normalized["app_id"] or env_cfg.app_id
    cfg.app_secret = normalized["app_secret"] or env_cfg.app_secret
    if saved and "command_prefix" in raw:
        cfg.command_prefix = normalized["command_prefix"]
    if saved and "allowed_users" in raw:
        cfg.allowed_users = _split_id_list(normalized["allowed_users"])
    if saved and "allowed_groups" in raw:
        cfg.allowed_groups = _split_id_list(normalized["allowed_groups"])
    if saved and "intents" in raw:
        cfg.intents = normalized["intents"]
    return enabled, cfg, normalized


def _public_qqbot_status(app: Starlette | None = None, settings: dict | None = None) -> dict:
    enabled, cfg, _normalized = _resolve_qqbot_config(settings)
    gateway = getattr(app.state, "qq_official_gateway", None) if app is not None else None
    status = gateway.status() if gateway is not None else {}
    return {
        "provider": _QQBOT_PROVIDER,
        "enabled": enabled,
        "configured": cfg.is_configured(),
        "running": False,
        "session_ready": False,
        "bot_username": "",
        "last_sequence": None,
        "last_error": "",
        "app_id": cfg.app_id,
        "app_secret_set": bool(cfg.app_secret),
        "command_prefix": cfg.command_prefix,
        "allowed_users": _id_list_text(cfg.allowed_users),
        "allowed_groups": _id_list_text(cfg.allowed_groups),
        "intents": cfg.intents,
        "shard": [cfg.shard_id, cfg.shard_count],
        "config_path": str(_GUI_SETTINGS_FILE),
        **status,
    }


def _normalize_telegrambot_settings(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "provider": _TELEGRAMBOT_PROVIDER,
        "enabled": _coerce_bool(raw.get("enabled"), False),
        "bot_token": str(raw.get("bot_token") or "").strip(),
        "command_prefix": str(raw.get("command_prefix") or "/mew").strip(),
        "allowed_users": _id_list_text(raw.get("allowed_users")),
        "allowed_chats": _id_list_text(raw.get("allowed_chats")),
    }


def _telegrambot_settings_from_payload(body: dict, current: dict | None = None) -> dict:
    current = current if isinstance(current, dict) else {}
    merged = {**current, **(body or {})}
    token = body.get("bot_token") if isinstance(body, dict) else None
    if token is None or not str(token).strip():
        merged["bot_token"] = str(current.get("bot_token") or "").strip()
    return _normalize_telegrambot_settings(merged)


def _resolve_telegrambot_config(settings: dict | None = None) -> tuple[bool, TelegramBotConfig, dict]:
    data = settings if isinstance(settings, dict) else _load_gui_settings()
    raw = data.get("telegrambot") if isinstance(data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    saved = bool(raw)
    normalized = _normalize_telegrambot_settings(raw)
    env_cfg = TelegramBotConfig.from_env()
    enabled = _coerce_bool(raw.get("enabled"), False) if saved else TelegramBotConfig.enabled_from_env()

    cfg = TelegramBotConfig.from_env()
    cfg.bot_token = normalized["bot_token"] or env_cfg.bot_token
    if saved and "command_prefix" in raw:
        cfg.command_prefix = normalized["command_prefix"]
    if saved and "allowed_users" in raw:
        cfg.allowed_users = _split_id_list(normalized["allowed_users"])
    if saved and "allowed_chats" in raw:
        cfg.allowed_chats = _split_id_list(normalized["allowed_chats"])
    return enabled, cfg, normalized


def _public_telegrambot_status(app: Starlette | None = None, settings: dict | None = None) -> dict:
    enabled, cfg, _normalized = _resolve_telegrambot_config(settings)
    gateway = getattr(app.state, "telegram_bot_runner", None) if app is not None else None
    status = gateway.status() if gateway is not None else {}
    return {
        "provider": _TELEGRAMBOT_PROVIDER,
        "enabled": enabled,
        "configured": cfg.is_configured(),
        "running": False,
        "session_ready": False,
        "bot_username": "",
        "last_update_id": None,
        "last_error": "",
        "bot_token_set": bool(cfg.bot_token),
        "command_prefix": cfg.command_prefix,
        "allowed_users": _id_list_text(cfg.allowed_users),
        "allowed_chats": _id_list_text(cfg.allowed_chats),
        "config_path": str(_GUI_SETTINGS_FILE),
        **status,
    }


def _default_base_url(protocol: str) -> str:
    if protocol == "anthropic":
        return "https://api.anthropic.com"
    if protocol == "openai":
        return "https://api.openai.com/v1"
    return ""


def _normalize_base_url(protocol: str, base_url: str) -> str:
    if protocol not in {"openai", "openai-compat"}:
        return base_url
    parsed = urlparse(base_url)
    if (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
        and parsed.path in {"", "/"}
    ):
        return base_url.rstrip("/") + "/v1"
    return base_url


def _public_config(config: AppConfig | None, error: str = "") -> dict:
    providers = []
    if config is not None:
        for provider in config.providers:
            providers.append({
                "name": provider.name,
                "protocol": provider.protocol,
                "base_url": provider.base_url,
                "model": provider.model,
                "api_key_set": bool(provider.api_key),
                "thinking": provider.thinking,
                "context_window": provider.context_window,
                "max_output_tokens": provider.max_output_tokens,
            })
    return {
        "configured": config is not None and bool(config.providers),
        "config_path": str(_USER_CONFIG_FILE),
        "error": error,
        "providers": providers,
        "permission_mode": config.permission_mode if config is not None else "default",
    }


def _config_from_gui_payload(body: dict, current: AppConfig | None = None) -> dict:
    protocol = (body.get("protocol") or "openai").strip()
    base_url = _normalize_base_url(
        protocol,
        (body.get("base_url") or _default_base_url(protocol)).strip(),
    )
    model = (body.get("model") or "").strip()
    name = (body.get("name") or protocol or "default").strip()
    api_key = (body.get("api_key") or "").strip()
    if not api_key and current is not None and current.providers:
        api_key = current.providers[0].api_key

    raw = {
        "providers": [{
            "name": name,
            "protocol": protocol,
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "thinking": bool(body.get("thinking", False)),
            "context_window": int(body.get("context_window") or 0),
            "max_output_tokens": int(body.get("max_output_tokens") or 0),
        }],
        "permission_mode": (body.get("permission_mode") or "default").strip(),
        "mcp_servers": [],
        "hooks": [],
        "enable_fork": bool(body.get("enable_fork", False)),
        "enable_verification_agent": bool(body.get("enable_verification_agent", False)),
        "worktree": {
            "symlink_directories": ["node_modules", ".venv", "vendor"],
            "stale_cleanup_interval": 3600,
            "stale_cutoff_hours": 24,
        },
        "teammate_mode": "",
        "enable_coordinator_mode": bool(body.get("enable_coordinator_mode", False)),
    }
    validate_config_structure(raw)
    return raw


def _write_user_config(raw: dict) -> AppConfig:
    _USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USER_CONFIG_FILE.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return load_config(_USER_CONFIG_FILE)


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
            user_rules_path=home / ".mozilcode" / "permissions.yaml",
            project_rules_path=Path(work_dir) / ".mozilcode" / "permissions.yaml",
            local_rules_path=Path(work_dir) / ".mozilcode" / "permissions.local.yaml",
        ),
        mode=permission_mode,
    )

    instructions = load_instructions(work_dir)
    memory_hub = build_memory_hub(config.memory, work_dir)
    registry = create_default_registry()
    registry.register(ToolSearchTool(registry, protocol=provider.protocol))
    registry.register(AskUserTool())

    from mozilcode.tools.exit_plan_mode import ExitPlanModeTool
    registry.register(ExitPlanModeTool())

    agent = Agent(
        client=client,
        registry=registry,
        protocol=provider.protocol,
        work_dir=work_dir,
        permission_checker=checker,
        context_window=provider.get_context_window(),
        instructions_content=instructions,
        memory_hub=memory_hub,
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

    _COMMAND_ACCEPTANCE_MODES = {
        PermissionMode.DEFAULT,
        PermissionMode.ACCEPT_EDITS,
        PermissionMode.BYPASS,
    }

    def __init__(self, config: AppConfig | None, work_dir: str, hook_engine: HookEngine | None = None):
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
        self._active_task_ids: dict[str, str] = {}
        self._pre_plan_modes: dict[str, PermissionMode] = {}
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
        if self.config is None:
            raise ValueError("model provider is not configured")
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
        if self.config is None:
            return False
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
            except asyncio.CancelledError:
                self._emit(sid, {
                    "type": "TaskCancelled",
                    "task_id": task_id,
                    "data": {"message": "Task cancelled"},
                })
                self._emit(sid, {"type": "LoopComplete", "task_id": task_id, "data": {}})
            except Exception as e:
                log.exception("Agent task %s failed", task_id)
                self._emit(sid, {
                    "type": "ErrorEvent",
                    "task_id": task_id,
                    "data": {"message": str(e)},
                })
            finally:
                current = self._tasks.get(sid)
                task = asyncio.current_task()
                if current is task:
                    self._tasks.pop(sid, None)
                    self._active_task_ids.pop(sid, None)
                # Flush this turn's events to disk so the conversation survives a
                # daemon restart.
                self._persist_events(sid)

        task = asyncio.create_task(run_agent(), name=f"agent-{sid}-{task_id}")
        self._tasks[sid] = task
        self._active_task_ids[sid] = task_id
        return task_id

    async def set_permission_mode(self, sid: str, mode: str) -> dict:
        """Switch a session's permission mode and return fresh status."""
        await self.ensure_agent(sid)
        agent = self.get_agent(sid)
        if agent is None:
            raise ValueError(f"Session {sid} not found")

        if mode == "do":
            next_mode = self._pre_plan_modes.pop(sid, None) or PermissionMode.DEFAULT
        else:
            requested_mode = PermissionMode(mode)
            if requested_mode == PermissionMode.PLAN:
                next_mode = PermissionMode.PLAN
                if agent.permission_mode != PermissionMode.PLAN:
                    self._pre_plan_modes[sid] = self._command_acceptance_mode(sid, agent)
            elif requested_mode in self._COMMAND_ACCEPTANCE_MODES and agent.permission_mode == PermissionMode.PLAN:
                self._pre_plan_modes[sid] = requested_mode
                next_mode = PermissionMode.PLAN
            else:
                self._pre_plan_modes.pop(sid, None)
                next_mode = requested_mode

        agent.set_permission_mode(next_mode)
        status = self.status(sid)
        self._emit(sid, {
            "type": "ModeChanged",
            "data": {
                "mode": status["permission_mode"],
                "permission_mode": status["permission_mode"],
                "command_acceptance_mode": status["command_acceptance_mode"],
                "plan_mode": status["plan_mode"],
            },
        })
        return status

    def _command_acceptance_mode(self, sid: str, agent: Agent | None) -> PermissionMode:
        """Return the GUI-facing command acceptance state, excluding plan mode."""
        if agent is not None:
            if agent.permission_mode == PermissionMode.PLAN:
                pre_plan = self._pre_plan_modes.get(sid)
                if pre_plan in self._COMMAND_ACCEPTANCE_MODES:
                    return pre_plan
                return PermissionMode.DEFAULT
            if agent.permission_mode in self._COMMAND_ACCEPTANCE_MODES:
                return agent.permission_mode
            return PermissionMode.DEFAULT

        if self.config is not None:
            configured_mode = PermissionMode(self.config.permission_mode)
            if configured_mode in self._COMMAND_ACCEPTANCE_MODES:
                return configured_mode
        return PermissionMode.DEFAULT

    def status(self, sid: str) -> dict:
        agent = self.get_agent(sid)
        deps = self.get_deps(sid)
        conv = self.get_conversation(sid)
        meta = self._session_meta.get(sid, {})
        task = self._tasks.get(sid)
        running = bool(task and not task.done())

        enabled_tools: list[str] = []
        if agent is not None:
            enabled_tools = [
                t.name for t in agent.registry.list_tools()
                if agent.registry.is_enabled(t.name)
            ]

        provider = deps.provider if deps is not None else (self.config.providers[0] if self.config and self.config.providers else None)
        context_window = agent.context_window if agent is not None else (provider.get_context_window() if provider else 0)
        auto_compact_threshold = max(0, compute_compact_threshold(context_window)) if context_window else 0
        if conv is not None and hasattr(conv, "current_tokens"):
            input_tokens = conv.current_tokens()
        else:
            input_tokens = agent.total_input_tokens if agent is not None else 0
        output_tokens = agent.total_output_tokens if agent is not None else 0

        return {
            "id": sid,
            "work_dir": meta.get("work_dir", self.work_dir),
            "title": meta.get("title", ""),
            "permission_mode": agent.permission_mode.value if agent else (self.config.permission_mode if self.config else "default"),
            "command_acceptance_mode": self._command_acceptance_mode(sid, agent).value,
            "plan_mode": bool(agent.plan_mode) if agent else False,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "context_window": context_window,
            "auto_compact_threshold": auto_compact_threshold,
            "token_percent": int(input_tokens / context_window * 100) if context_window else 0,
            "tool_count": len(enabled_tools),
            "tools": enabled_tools,
            "active_task": {
                "id": self._active_task_ids.get(sid, ""),
                "running": running,
            },
            "provider": {
                "name": provider.name if provider else "",
                "protocol": provider.protocol if provider else "",
                "model": provider.model if provider else "",
            },
        }

    def cancel_active_task(self, sid: str) -> bool:
        task = self._tasks.get(sid)
        if task is None or task.done():
            return False
        task.cancel()
        return True

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

    async def invalidate_idle_agents(self) -> None:
        """Drop cached Agent instances so updated provider config applies."""
        for sid in list(self._agents.keys()):
            task = self._tasks.get(sid)
            if task and not task.done():
                continue
            self._agents.pop(sid, None)
            await self.session_mgr.close_session(sid)
            self._pre_plan_modes.pop(sid, None)

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
        self._active_task_ids.pop(sid, None)
        self._pre_plan_modes.pop(sid, None)
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
        {
            "status": "ok",
            "service": "mozilcode-daemon",
            "work_dir": server.work_dir,
            "configured": server.config is not None,
            "config_path": str(_USER_CONFIG_FILE),
        }
    )


async def config_status(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    return JSONResponse(_public_config(server.config))


async def save_config(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    try:
        body = await request.json()
        raw = _config_from_gui_payload(body or {}, server.config)
        server.config = _write_user_config(raw)
        await server.invalidate_idle_agents()
    except (ConfigError, ValueError, TypeError) as e:
        return JSONResponse(_public_config(server.config, str(e)), status_code=400)
    except Exception as e:
        log.exception("Failed to save config")
        return JSONResponse(_public_config(server.config, str(e)), status_code=500)
    return JSONResponse(_public_config(server.config))


async def create_session(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    body = await request.json()
    session_id = body.get("session_id") if body else None
    work_dir = body.get("work_dir") if body else None
    try:
        sid = await server.init_session(session_id, work_dir)
    except ValueError as e:
        return JSONResponse({"error": str(e), "configured": server.config is not None}, status_code=400)
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


async def session_status(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    try:
        ok = await server.ensure_agent(sid)
    except LLMError as e:
        status = server.status(sid)
        status["agent_ready"] = False
        status["error"] = str(e)
        return JSONResponse(status)
    if not ok:
        return JSONResponse({"error": "session not found"}, status_code=404)
    status = server.status(sid)
    status["agent_ready"] = True
    return JSONResponse(status)


async def set_session_mode(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    mode = (body.get("mode") or "").strip()
    if not mode:
        return JSONResponse({"error": "mode is required"}, status_code=400)
    try:
        status = await server.set_permission_mode(sid, mode)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(status)


async def cancel_active_task(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    if sid not in server._event_logs:
        return JSONResponse({"error": "session not found"}, status_code=404)
    cancelled = server.cancel_active_task(sid)
    return JSONResponse({"cancelled": cancelled})


def _task_to_dict(task: Any) -> dict:
    elapsed = (task.end_time or time.monotonic()) - task.start_time
    return {
        "id": task.id,
        "name": task.name,
        "task": task.task,
        "status": task.status,
        "result": task.result,
        "elapsed": elapsed,
        "input_tokens": task.progress.input_tokens,
        "output_tokens": task.progress.output_tokens,
        "tool_call_count": task.progress.tool_call_count,
        "last_activity": task.progress.last_activity,
    }


async def list_background_tasks(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    tasks = deps.task_manager.list_tasks() if deps else []
    return JSONResponse({"tasks": [_task_to_dict(t) for t in tasks]})


async def cancel_background_task(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    task_id = request.path_params["task_id"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    if deps is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return JSONResponse({"cancelled": deps.task_manager.cancel(task_id)})


def _worktree_to_dict(wt: Any, current_name: str | None = None) -> dict:
    return {
        "name": wt.name,
        "path": wt.path,
        "branch": wt.branch,
        "based_on": wt.based_on,
        "head_commit": wt.head_commit,
        "created": wt.created.isoformat() if getattr(wt, "created", None) else "",
        "current": wt.name == current_name,
    }


async def list_worktrees(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    if deps is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    manager = deps.worktree_manager
    session = manager.get_current_session()
    current_name = session.worktree_name if session else None
    return JSONResponse({
        "current": current_name,
        "worktrees": [_worktree_to_dict(wt, current_name) for wt in manager.list_worktrees()],
    })


async def create_worktree(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    name = (body.get("name") or "").strip()
    base_branch = (body.get("base_branch") or "HEAD").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    agent = server.get_agent(sid)
    if deps is None or agent is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    try:
        wt = await deps.worktree_manager.create(name, base_branch)
        session = await deps.worktree_manager.enter(name)
        agent.work_dir = session.worktree_path
        server._session_meta.setdefault(sid, {})["work_dir"] = session.worktree_path
        server._persist_meta(sid)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"worktree": _worktree_to_dict(wt, name), "status": server.status(sid)})


async def enter_worktree(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    name = request.path_params["name"]
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    agent = server.get_agent(sid)
    if deps is None or agent is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    try:
        session = await deps.worktree_manager.enter(name)
        agent.work_dir = session.worktree_path
        server._session_meta.setdefault(sid, {})["work_dir"] = session.worktree_path
        server._persist_meta(sid)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"entered": True, "status": server.status(sid)})


async def exit_worktree(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    sid = request.path_params["sid"]
    body = await request.json()
    remove = bool(body.get("remove", False))
    discard = bool(body.get("discard", False))
    if not await server.ensure_agent(sid):
        return JSONResponse({"error": "session not found"}, status_code=404)
    deps = server.get_deps(sid)
    agent = server.get_agent(sid)
    if deps is None or agent is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    manager = deps.worktree_manager
    session = manager.get_current_session()
    if session is None:
        return JSONResponse({"error": "not in a worktree"}, status_code=400)
    try:
        await manager.exit(
            session.worktree_name,
            action="remove" if remove else "keep",
            discard_changes=discard,
        )
        agent.work_dir = session.original_cwd
        server._session_meta.setdefault(sid, {})["work_dir"] = session.original_cwd
        server._persist_meta(sid)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"exited": True, "status": server.status(sid)})


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
    await server.ensure_agent(sid)
    agent = server.get_agent(sid)
    conv = server.get_conversation(sid)
    if agent is None or conv is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    before_tokens = conv.current_tokens()
    server._emit(sid, {
        "type": "CompactStarted",
        "data": {
            "current_tokens": before_tokens,
            "threshold": max(0, compute_compact_threshold(agent.context_window, manual=True)),
            "context_window": agent.context_window,
            "message": "正在压缩上下文",
        },
    })
    result = await agent.manual_compact(conv)
    event = serialize_event(result)
    server._emit(sid, event)
    if not isinstance(result, ErrorEvent):
        server._emit(sid, {
            "type": "UsageEvent",
            "data": {
                "input_tokens": agent.total_input_tokens,
                "output_tokens": agent.total_output_tokens,
                "context_tokens": conv.current_tokens(),
            },
        })
    server._persist_events(sid)
    if isinstance(result, ErrorEvent):
        return JSONResponse({"error": result.message}, status_code=400)
    return JSONResponse({
        "type": type(result).__name__,
        "data": event.get("data", {}),
        "status": server.status(sid),
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


async def memory_settings_get(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    cfg = server.config.memory if server.config is not None else None
    if cfg is None:
        return JSONResponse({"enabled": False, "providers": []})
    return JSONResponse({
        "enabled": cfg.enabled,
        "providers": [
            {
                "name": p.name,
                "type": p.type,
                "enabled": p.enabled,
                "module": p.module,
                "class": p.class_name,
            }
            for p in cfg.providers
        ],
    })


async def skills_list(request: Request) -> JSONResponse:
    server: DaemonServer = request.app.state.server
    disabled = set(_load_gui_settings().get("disabled_skills", []))
    out = []
    try:
        from mozilcode.skills.loader import SkillLoader
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
    from mozilcode.skills.parser import VALID_NAME_RE
    if not VALID_NAME_RE.match(name):
        return JSONResponse(
            {"error": "名称需为小写字母/数字/连字符，且以字母开头"}, status_code=400
        )
    if not desc:
        return JSONResponse({"error": "描述必填"}, status_code=400)
    skill_dir = Path.home() / ".mozilcode" / "skills" / name
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
    skill_dir = Path.home() / ".mozilcode" / "skills" / name
    if not skill_dir.is_dir():
        return JSONResponse({"error": "只能删除用户创建的技能"}, status_code=400)
    try:
        import shutil
        shutil.rmtree(skill_dir, ignore_errors=True)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"ok": True})


def _public_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


async def a2a_agent_card(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    return JSONResponse(bridge.agent_card(_public_base_url(request)))


async def a2a_rpc(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )
    return JSONResponse(await bridge.handle_json_rpc(payload))


async def a2a_message_send(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        body = await request.json()
        result = await bridge.send_message(body or {})
    except A2AError as e:
        return JSONResponse({"error": e.message, "code": e.code}, status_code=400)
    return JSONResponse(result)


async def a2a_task_get(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        task = bridge.get_task(request.path_params["task_id"])
    except A2AError as e:
        return JSONResponse({"error": e.message, "code": e.code}, status_code=404)
    return JSONResponse(bridge.task_to_a2a(task))


async def a2a_task_cancel(request: Request) -> JSONResponse:
    bridge: A2ABridge = request.app.state.a2a_bridge
    try:
        task = await bridge.cancel_task(request.path_params["task_id"])
    except A2AError as e:
        return JSONResponse({"error": e.message, "code": e.code}, status_code=404)
    return JSONResponse(bridge.task_to_a2a(task))


async def qq_official_status(request: Request) -> JSONResponse:
    return JSONResponse(_public_qqbot_status(request.app))


async def _apply_qq_official_gateway(app: Starlette, bridge: A2ABridge, *, restart: bool = False) -> None:
    gateway = getattr(app.state, "qq_official_gateway", None)
    enabled, cfg, _settings = _resolve_qqbot_config()

    if gateway is not None and (restart or not enabled or not cfg.is_configured()):
        await gateway.stop()
        app.state.qq_official_gateway = None
        gateway = None

    if not enabled:
        return
    if not cfg.is_configured():
        log.warning("Official QQ Gateway requested but AppID/AppSecret are not configured")
        return
    if gateway is not None:
        return

    gateway = create_official_qq_gateway(bridge, cfg)
    app.state.qq_official_gateway = gateway
    await gateway.start()
    log.info("Official QQ Gateway adapter enabled")


async def qqbot_settings_get(request: Request) -> JSONResponse:
    return JSONResponse(_public_qqbot_status(request.app))


async def qqbot_settings_save(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON object is required"}, status_code=400)

    data = _load_gui_settings()
    data["qqbot"] = _qqbot_settings_from_payload(body, data.get("qqbot"))
    enabled, cfg, _settings = _resolve_qqbot_config(data)
    if enabled and not cfg.is_configured():
        return JSONResponse({"error": "启用 QQ Bot 需要 AppID 和 AppSecret"}, status_code=400)

    _save_gui_settings(data)
    await _apply_qq_official_gateway(request.app, request.app.state.a2a_bridge, restart=True)
    return JSONResponse({"ok": True, **_public_qqbot_status(request.app)})


async def telegrambot_status(request: Request) -> JSONResponse:
    return JSONResponse(_public_telegrambot_status(request.app))


async def _apply_telegram_bot_runner(app: Starlette, bridge: A2ABridge, *, restart: bool = False) -> None:
    runner = getattr(app.state, "telegram_bot_runner", None)
    enabled, cfg, _settings = _resolve_telegrambot_config()

    if runner is not None and (restart or not enabled or not cfg.is_configured()):
        await runner.stop()
        app.state.telegram_bot_runner = None
        runner = None

    if not enabled:
        return
    if not cfg.is_configured():
        log.warning("Telegram Bot requested but Bot token is not configured")
        return
    if runner is not None:
        return

    runner = create_telegram_bot_runner(bridge, cfg)
    app.state.telegram_bot_runner = runner
    await runner.start()
    log.info("Telegram Bot adapter enabled")


async def telegrambot_settings_get(request: Request) -> JSONResponse:
    return JSONResponse(_public_telegrambot_status(request.app))


async def telegrambot_settings_save(request: Request) -> JSONResponse:
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON object is required"}, status_code=400)

    data = _load_gui_settings()
    data["telegrambot"] = _telegrambot_settings_from_payload(body, data.get("telegrambot"))
    enabled, cfg, _settings = _resolve_telegrambot_config(data)
    if enabled and not cfg.is_configured():
        return JSONResponse({"error": "启用 Telegram Bot 需要 Bot Token"}, status_code=400)

    _save_gui_settings(data)
    await _apply_telegram_bot_runner(request.app, request.app.state.a2a_bridge, restart=True)
    return JSONResponse({"ok": True, **_public_telegrambot_status(request.app)})


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

def create_app(config: AppConfig | None, work_dir: str, hook_engine: HookEngine | None = None) -> Starlette:
    """Create the Starlette application with all routes wired."""
    server = DaemonServer(config, work_dir, hook_engine)
    a2a_bridge = A2ABridge(server)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.qq_official_gateway = None
        app.state.telegram_bot_runner = None
        await _apply_qq_official_gateway(app, a2a_bridge)
        await _apply_telegram_bot_runner(app, a2a_bridge)
        try:
            yield
        finally:
            gateway = getattr(app.state, "qq_official_gateway", None)
            if gateway is not None:
                await gateway.stop()
            runner = getattr(app.state, "telegram_bot_runner", None)
            if runner is not None:
                await runner.stop()

    routes = [
        Route("/", serve_gui, methods=["GET"]),
        Route("/.well-known/agent-card.json", a2a_agent_card, methods=["GET"]),
        Route("/a2a/agent-card.json", a2a_agent_card, methods=["GET"]),
        Route("/a2a/rpc", a2a_rpc, methods=["POST"]),
        Route("/a2a/message:send", a2a_message_send, methods=["POST"]),
        Route("/a2a/tasks/{task_id}", a2a_task_get, methods=["GET"]),
        Route("/a2a/tasks/{task_id}:cancel", a2a_task_cancel, methods=["POST"]),
        Route("/api/qq/official/status", qq_official_status, methods=["GET"]),
        Route("/api/telegram/status", telegrambot_status, methods=["GET"]),
        Route("/api/settings/qqbot", qqbot_settings_get, methods=["GET"]),
        Route("/api/settings/qqbot", qqbot_settings_save, methods=["POST"]),
        Route("/api/settings/telegrambot", telegrambot_settings_get, methods=["GET"]),
        Route("/api/settings/telegrambot", telegrambot_settings_save, methods=["POST"]),
        Route("/api/health", health, methods=["GET"]),
        Route("/api/config", config_status, methods=["GET"]),
        Route("/api/config", save_config, methods=["POST"]),
        Route("/api/session", create_session, methods=["POST"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/task", start_task, methods=["POST"]),
        Route("/api/session/{sid}/status", session_status, methods=["GET"]),
        Route("/api/session/{sid}/mode", set_session_mode, methods=["POST"]),
        Route("/api/session/{sid}/cancel", cancel_active_task, methods=["POST"]),
        Route("/api/session/{sid}/tasks", list_background_tasks, methods=["GET"]),
        Route("/api/session/{sid}/tasks/{task_id}/cancel", cancel_background_task, methods=["POST"]),
        Route("/api/session/{sid}/worktrees", list_worktrees, methods=["GET"]),
        Route("/api/session/{sid}/worktrees", create_worktree, methods=["POST"]),
        Route("/api/session/{sid}/worktrees/{name}/enter", enter_worktree, methods=["POST"]),
        Route("/api/session/{sid}/worktrees/exit", exit_worktree, methods=["POST"]),
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
        Route("/api/settings/memory", memory_settings_get, methods=["GET"]),
        Route("/api/skills", skills_list, methods=["GET"]),
        Route("/api/skills", skill_create, methods=["POST"]),
        Route("/api/skills/{name}/toggle", skill_toggle, methods=["POST"]),
        Route("/api/skills/{name}", skill_delete, methods=["DELETE"]),
        WebSocketRoute("/api/stream/{sid}", stream_events),
    ]

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.server = server
    app.state.a2a_bridge = a2a_bridge

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
