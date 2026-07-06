from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from mozilcode.agent import (
    Agent,
    CompactStarted,
    ErrorEvent,
    PermissionResponse,
    UsageEvent,
)
from mozilcode.config import AppConfig
from mozilcode.conversation import ConversationManager
from mozilcode.agent_factory import AgentDeps, create_agent_from_config
from mozilcode.context import compute_compact_threshold
from mozilcode.daemon.serialize import serialize_event
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session_status import (
    build_session_status,
    command_acceptance_mode,
    resolve_mode_transition,
)
from mozilcode.daemon.session_store import SessionStore
from mozilcode.daemon.task_events import (
    loop_complete_event,
    serialize_task_event,
    task_cancelled_event,
    task_error_event,
    user_message_event,
)
from mozilcode.daemon.responses import DaemonActionResult
from mozilcode.daemon.workspace_payloads import task_to_dict, worktree_to_dict
from mozilcode.hooks import HookEngine
from mozilcode.permissions import PermissionMode

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DaemonSessionRuntime:
    agent: Agent
    deps: AgentDeps
    conversation: ConversationManager


class DaemonServer:
    """Holds shared daemon state across HTTP and WebSocket requests."""

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
        self._agents: dict[str, DaemonSessionRuntime] = {}
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
        self._agents[sid] = DaemonSessionRuntime(agent, deps, conv)
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
        self._agents[sid] = DaemonSessionRuntime(agent, deps, conv)
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
        return entry.agent if entry else None

    def get_conversation(self, sid: str) -> ConversationManager | None:
        entry = self._agents.get(sid)
        return entry.conversation if entry else None

    def get_deps(self, sid: str) -> AgentDeps | None:
        entry = self._agents.get(sid)
        return entry.deps if entry else None

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

    def _session_not_found(self) -> DaemonActionResult:
        return DaemonActionResult({"error": "session not found"}, status_code=404)

    async def _require_deps(
        self,
        sid: str,
    ) -> tuple[AgentDeps | None, DaemonActionResult | None]:
        if not await self.ensure_agent(sid):
            return None, self._session_not_found()
        deps = self.get_deps(sid)
        if deps is None:
            return None, self._session_not_found()
        return deps, None

    async def _require_agent_and_deps(
        self,
        sid: str,
    ) -> tuple[Agent | None, AgentDeps | None, DaemonActionResult | None]:
        deps, error = await self._require_deps(sid)
        if error is not None:
            return None, None, error
        agent = self.get_agent(sid)
        if agent is None or deps is None:
            return None, None, self._session_not_found()
        return agent, deps, None

    async def _require_agent_and_conversation(
        self,
        sid: str,
    ) -> tuple[Agent | None, ConversationManager | None, DaemonActionResult | None]:
        if not await self.ensure_agent(sid):
            return None, None, self._session_not_found()
        agent = self.get_agent(sid)
        conv = self.get_conversation(sid)
        if agent is None or conv is None:
            return None, None, self._session_not_found()
        return agent, conv, None

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
                self._emit(sid, user_message_event(task_id, prompt))
                async for event in agent.run(conv):
                    task_event = serialize_task_event(event, task_id)
                    if task_event.future is not None:
                        session = await self.session_mgr.get_session(sid)
                        if session:
                            session.register_future(
                                task_event.request_id,
                                task_event.future,
                            )
                    if task_event.pending_request_id:
                        self._pending_prompts.setdefault(sid, {})[
                            task_event.pending_request_id
                        ] = task_event.message
                    self._emit(sid, task_event.message)

                self._emit(sid, loop_complete_event(task_id))
            except asyncio.CancelledError:
                self._emit(sid, task_cancelled_event(task_id))
                self._emit(sid, loop_complete_event(task_id))
            except Exception as e:
                log.exception("Agent task %s failed", task_id)
                self._emit(sid, task_error_event(task_id, str(e)))
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

        transition = resolve_mode_transition(
            agent.permission_mode,
            mode,
            self._pre_plan_modes.get(sid),
        )
        next_mode = transition.next_mode
        if transition.pre_plan_mode is None:
            self._pre_plan_modes.pop(sid, None)
        else:
            self._pre_plan_modes[sid] = transition.pre_plan_mode

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

    async def manual_compact(self, sid: str) -> DaemonActionResult:
        """Run manual context compaction and persist the resulting event stream."""
        agent, conv, error = await self._require_agent_and_conversation(sid)
        if error is not None:
            return error
        assert agent is not None and conv is not None

        before_tokens = conv.current_tokens()
        self._emit(
            sid,
            serialize_event(
                CompactStarted(
                    current_tokens=before_tokens,
                    threshold=max(
                        0,
                        compute_compact_threshold(
                            agent.context_window,
                            manual=True,
                        ),
                    ),
                    context_window=agent.context_window,
                    message="正在压缩上下文",
                )
            ),
        )

        result = await agent.manual_compact(conv)
        event = serialize_event(result)
        self._emit(sid, event)
        if not isinstance(result, ErrorEvent):
            self._emit(
                sid,
                serialize_event(
                    UsageEvent(
                        input_tokens=agent.total_input_tokens,
                        output_tokens=agent.total_output_tokens,
                        context_tokens=conv.current_tokens(),
                    )
                ),
            )
        self._persist_events(sid)

        if isinstance(result, ErrorEvent):
            return DaemonActionResult(
                {"error": result.message},
                status_code=400,
            )
        return DaemonActionResult(
            {
                "type": type(result).__name__,
                "data": event.get("data", {}),
                "status": self.status(sid),
            }
        )

    async def list_worktrees(self, sid: str) -> DaemonActionResult:
        deps, error = await self._require_deps(sid)
        if error is not None:
            return error
        assert deps is not None

        manager = deps.worktree_manager
        session = manager.get_current_session()
        current_name = session.worktree_name if session else None
        return DaemonActionResult(
            {
                "current": current_name,
                "worktrees": [
                    worktree_to_dict(worktree, current_name)
                    for worktree in manager.list_worktrees()
                ],
            }
        )

    async def create_worktree(
        self,
        sid: str,
        name: str,
        base_branch: str = "HEAD",
    ) -> DaemonActionResult:
        name = name.strip()
        base_branch = (base_branch or "HEAD").strip()
        if not name:
            return DaemonActionResult({"error": "name is required"}, status_code=400)

        agent, deps, error = await self._require_agent_and_deps(sid)
        if error is not None:
            return error
        assert agent is not None and deps is not None

        try:
            worktree = await deps.worktree_manager.create(name, base_branch)
            session = await deps.worktree_manager.enter(name)
            agent.work_dir = session.worktree_path
            self.update_session_work_dir(sid, session.worktree_path)
        except Exception as e:
            return DaemonActionResult({"error": str(e)}, status_code=400)

        return DaemonActionResult(
            {
                "worktree": worktree_to_dict(worktree, name),
                "status": self.status(sid),
            }
        )

    async def enter_worktree(self, sid: str, name: str) -> DaemonActionResult:
        agent, deps, error = await self._require_agent_and_deps(sid)
        if error is not None:
            return error
        assert agent is not None and deps is not None

        try:
            session = await deps.worktree_manager.enter(name)
            agent.work_dir = session.worktree_path
            self.update_session_work_dir(sid, session.worktree_path)
        except Exception as e:
            return DaemonActionResult({"error": str(e)}, status_code=400)

        return DaemonActionResult({"entered": True, "status": self.status(sid)})

    async def exit_worktree(
        self,
        sid: str,
        *,
        remove: bool = False,
        discard: bool = False,
    ) -> DaemonActionResult:
        agent, deps, error = await self._require_agent_and_deps(sid)
        if error is not None:
            return error
        assert agent is not None and deps is not None

        manager = deps.worktree_manager
        session = manager.get_current_session()
        if session is None:
            return DaemonActionResult({"error": "not in a worktree"}, status_code=400)

        try:
            await manager.exit(
                session.worktree_name,
                action="remove" if remove else "keep",
                discard_changes=discard,
            )
            agent.work_dir = session.original_cwd
            self.update_session_work_dir(sid, session.original_cwd)
        except Exception as e:
            return DaemonActionResult({"error": str(e)}, status_code=400)

        return DaemonActionResult({"exited": True, "status": self.status(sid)})

    async def list_background_tasks(self, sid: str) -> DaemonActionResult:
        deps, error = await self._require_deps(sid)
        if error is not None:
            return error
        assert deps is not None
        return DaemonActionResult(
            {
                "tasks": [
                    task_to_dict(task)
                    for task in deps.task_manager.list_tasks()
                ]
            }
        )

    async def cancel_background_task(
        self,
        sid: str,
        task_id: str,
    ) -> DaemonActionResult:
        deps, error = await self._require_deps(sid)
        if error is not None:
            return error
        assert deps is not None
        return DaemonActionResult({"cancelled": deps.task_manager.cancel(task_id)})

    def _command_acceptance_mode(self, sid: str, agent: Agent | None) -> PermissionMode:
        configured_mode = (
            PermissionMode(self.config.permission_mode)
            if self.config is not None
            else None
        )
        return command_acceptance_mode(
            agent.permission_mode if agent is not None else None,
            self._pre_plan_modes.get(sid),
            configured_mode,
        )

    def status(self, sid: str) -> dict:
        agent = self.get_agent(sid)
        deps = self.get_deps(sid)
        conv = self.get_conversation(sid)
        meta = self._session_meta.get(sid, {})
        task = self._tasks.get(sid)
        running = bool(task and not task.done())
        provider = deps.provider if deps is not None else (self.config.providers[0] if self.config and self.config.providers else None)
        return build_session_status(
            sid=sid,
            server_work_dir=self.work_dir,
            meta=meta,
            agent=agent,
            provider=provider,
            conversation=conv,
            configured_permission_mode=(
                self.config.permission_mode
                if self.config is not None
                else "default"
            ),
            command_mode=self._command_acceptance_mode(sid, agent),
            active_task_id=self._active_task_ids.get(sid, ""),
            active_task_running=running,
        )

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
        hub = getattr(entry.agent, "memory_hub", None) if entry is not None else None
        if hub is not None:
            await hub.shutdown()
        self._session_meta.pop(sid, None)
        self._persisted_count.pop(sid, None)
        self._active_task_ids.pop(sid, None)
        self._pre_plan_modes.pop(sid, None)
        self.session_store.delete_session(sid)
        log.info("Session %s closed", sid)
