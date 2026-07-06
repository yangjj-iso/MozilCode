from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from mozilcode.agent import Agent, PermissionResponse
from mozilcode.config import AppConfig
from mozilcode.context import compute_compact_threshold
from mozilcode.conversation import ConversationManager
from mozilcode.agent_factory import AgentDeps, create_agent_from_config
from mozilcode.daemon.serialize import serialize_event
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session_store import SessionStore
from mozilcode.hooks import HookEngine
from mozilcode.permissions import PermissionMode

log = logging.getLogger(__name__)


class DaemonServer:
    """Holds shared daemon state across HTTP and WebSocket requests."""

    _COMMAND_ACCEPTANCE_MODES = {
        PermissionMode.DEFAULT,
        PermissionMode.ACCEPT_EDITS,
        PermissionMode.BYPASS,
    }

    def __init__(
        self,
        config: AppConfig | None,
        work_dir: str,
        hook_engine: HookEngine | None = None,
        session_store: SessionStore | None = None,
    ):
        self.config = config
        self.work_dir = work_dir
        self.hook_engine = hook_engine
        self.session_store = session_store or SessionStore()
        self.session_mgr = SessionManager()
        self._agents: dict[str, tuple[Agent, AgentDeps, ConversationManager]] = {}
        self._event_logs: dict[str, list[dict | None]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_task_ids: dict[str, str] = {}
        self._pre_plan_modes: dict[str, PermissionMode] = {}
        self._session_meta: dict[str, dict] = {}
        self._persisted_count: dict[str, int] = {}
        self._pending_prompts: dict[str, dict[str, dict]] = {}
        self._load_persisted_sessions()

    def _load_persisted_sessions(self) -> None:
        """Load persisted sessions from disk; agents are created lazily."""
        for session in self.session_store.load_sessions():
            self._event_logs[session.sid] = session.events
            self._session_meta[session.sid] = session.meta
            self._persisted_count[session.sid] = len(session.events)
        if self._session_meta:
            log.info("Loaded %d persisted session(s)", len(self._session_meta))

    def _persist_meta(self, sid: str) -> None:
        self.session_store.persist_meta(sid, self._session_meta.get(sid, {}))

    def _persist_events(self, sid: str) -> None:
        """Append newly-produced events for a session to its events.jsonl."""
        log_list = self._event_logs.get(sid)
        if log_list is None:
            return
        self._persisted_count[sid] = self.session_store.persist_events(
            sid,
            log_list,
            self._persisted_count.get(sid, 0),
        )

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
        agent.session_id = sid
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
        """Make sure an Agent exists for a session, creating one lazily."""
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
        agent.session_id = sid
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

    def has_session(self, sid: str) -> bool:
        return sid in self._event_logs

    def list_session_infos(self) -> list[dict]:
        sids = list(self._event_logs.keys())
        sids.sort(key=lambda s: self._session_meta.get(s, {}).get("created_at", 0), reverse=True)
        return [self.session_info(s) for s in sids]

    def session_work_dir(self, sid: str) -> str | None:
        meta = self._session_meta.get(sid)
        if meta is None:
            return None
        return meta.get("work_dir") or self.work_dir

    def update_session_work_dir(self, sid: str, work_dir: str) -> None:
        self._session_meta.setdefault(sid, {})["work_dir"] = work_dir
        self._persist_meta(sid)

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

    def emit_event(self, sid: str, event: dict | None) -> None:
        self._emit(sid, event)

    def persist_events(self, sid: str) -> None:
        self._persist_events(sid)

    def pending_prompt_events(self, sid: str) -> list[dict]:
        return list(self._pending_prompts.get(sid, {}).values())

    async def start_task(self, sid: str, prompt: str) -> str:
        """Start agent.run() as a background task. Returns task_id."""
        await self.ensure_agent(sid)
        agent = self.get_agent(sid)
        conv = self.get_conversation(sid)
        log_list = self.get_event_log(sid)
        if agent is None or conv is None or log_list is None:
            raise ValueError(f"Session {sid} not found")

        meta = self._session_meta.get(sid)
        if meta is not None and not meta.get("title"):
            meta["title"] = prompt[:40]
            self._persist_meta(sid)

        task_id = uuid.uuid4().hex[:8]

        async def run_agent():
            """Drive agent.run(), append serialized events to the session log."""
            try:
                conv.add_user_message(prompt)
                self._emit(sid, {"type": "UserMessage", "task_id": task_id, "data": {"content": prompt}})
                async for event in agent.run(conv):
                    if hasattr(event, "future") and event.future is not None:
                        request_id = str(id(event.future))
                        session = await self.session_mgr.get_session(sid)
                        if session:
                            session.register_future(request_id, event.future)

                    msg = serialize_event(event, task_id=task_id)
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
        """Return the command acceptance state, excluding plan mode."""
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
            entry = self._agents.pop(sid, None)
            if entry is not None and entry[0].memory_hub is not None:
                await entry[0].memory_hub.shutdown()
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

        log_list = self._event_logs.pop(sid, None)
        if log_list is not None:
            log_list.append(None)

        await self.session_mgr.close_session(sid)
        entry = self._agents.pop(sid, None)
        if entry is not None and entry[0].memory_hub is not None:
            await entry[0].memory_hub.shutdown()
        self._session_meta.pop(sid, None)
        self._persisted_count.pop(sid, None)
        self._active_task_ids.pop(sid, None)
        self._pre_plan_modes.pop(sid, None)
        self.session_store.delete_session(sid)
        log.info("Session %s closed", sid)
