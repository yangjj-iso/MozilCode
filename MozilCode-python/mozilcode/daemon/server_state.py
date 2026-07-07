from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from mozilcode.agent import Agent
from mozilcode.agent_events import PermissionResponse
from mozilcode.config import AppConfig, ProviderConfig
from mozilcode.conversation import ConversationManager
from mozilcode.agent_factory import AgentDeps, create_agent_from_config
from mozilcode.daemon.active_tasks import (
    ACTIVE_TASK_RUNNING_ERROR,
    ActiveTaskRegistry,
)
from mozilcode.daemon.agent_task_runner import AgentTaskRunner
from mozilcode.daemon.compact_actions import run_manual_compact
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session_status import (
    build_session_status,
    command_acceptance_mode,
    resolve_mode_transition,
)
from mozilcode.daemon.session_records import SessionRecords
from mozilcode.daemon.session_store import SessionStore, validate_session_id
from mozilcode.daemon.responses import (
    DaemonActionResult,
    bad_request_result,
    session_not_found_result,
)
from mozilcode.daemon.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.session_runtime import (
    DaemonSessionRuntime,
    create_daemon_session_runtime,
)
from mozilcode.daemon.workspace_payloads import task_to_dict, worktree_to_dict
from mozilcode.daemon.worktree_actions import (
    create_and_enter_worktree,
    enter_worktree as enter_worktree_action,
    exit_worktree as exit_worktree_action,
    list_worktrees_payload,
    normalize_create_worktree_request,
)
from mozilcode.hooks import HookEngine
from mozilcode.permissions import PermissionMode

log = logging.getLogger(__name__)


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
        self._records = SessionRecords(self.session_store, self.work_dir)
        self._agents: dict[str, DaemonSessionRuntime] = {}
        self._event_logs = self._records.event_logs
        self._active_tasks = ActiveTaskRegistry()
        self._tasks = self._active_tasks.tasks
        self._active_task_ids = self._active_tasks.task_ids
        self._pre_plan_modes: dict[str, PermissionMode] = {}
        self._session_meta = self._records.session_meta
        self._persisted_count = self._records.persisted_count
        self._pending_prompts = PendingPromptRegistry()
        self._agent_task_runner = AgentTaskRunner(
            active_tasks=self._active_tasks,
            session_mgr=self.session_mgr,
            pending_prompts=self._pending_prompts,
            emit_event=self._emit,
            persist_events=self._persist_events,
            set_title_from_prompt=self._set_session_title_from_prompt,
        )
        self._records.load_persisted()

    def _persist_meta(self, sid: str) -> None:
        self._records.persist_meta(sid)

    def _persist_events(self, sid: str) -> None:
        """Append newly-produced events for a session to its events.jsonl."""
        self._records.persist_events(sid)

    def _set_session_title_from_prompt(self, sid: str, prompt: str) -> None:
        self._records.set_title_from_prompt(sid, prompt)

    async def _create_session_runtime(
        self,
        sid: str,
        work_dir: str,
    ) -> DaemonSessionRuntime:
        if self.config is None:
            raise ValueError("model provider is not configured")
        mode = PermissionMode(self.config.permission_mode)
        runtime = await create_daemon_session_runtime(
            sid=sid,
            config=self.config,
            work_dir=work_dir,
            permission_mode=mode,
            hook_engine=self.hook_engine,
            session_mgr=self.session_mgr,
            agent_factory=create_agent_from_config,
        )
        self._agents[sid] = runtime
        return runtime

    async def init_session(
        self, session_id: str | None = None, work_dir: str | None = None
    ) -> str:
        """Create a new Agent session in the given workspace. Returns session_id."""
        if self.config is None:
            raise ValueError("model provider is not configured")
        sid = validate_session_id(session_id or uuid.uuid4().hex[:12])
        if self.has_session(sid):
            raise ValueError(f"session already exists: {sid}")
        wd = work_dir or self.work_dir
        if not Path(wd).is_dir():
            raise ValueError(f"workspace not found: {wd}")
        await self._create_session_runtime(sid, wd)
        self._records.create(sid, wd)
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
        await self._create_session_runtime(sid, wd)
        self._records.ensure_event_log(sid)
        log.info("Session %s reactivated (work_dir=%s)", sid, wd)
        return True

    def session_info(self, sid: str) -> dict:
        return self._records.info(sid)

    def has_session(self, sid: str) -> bool:
        return self._records.has(sid)

    def list_session_infos(self) -> list[dict]:
        return self._records.list_infos()

    def session_work_dir(self, sid: str) -> str | None:
        return self._records.work_dir(sid)

    def update_session_work_dir(self, sid: str, work_dir: str) -> None:
        self._records.update_work_dir(sid, work_dir)

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
        return self._records.event_log(sid)

    def _emit(self, sid: str, event: dict | None) -> None:
        """Append a serialized event to the session log. WS streamers tail it."""
        self._records.emit(sid, event)

    def emit_event(self, sid: str, event: dict | None) -> None:
        self._emit(sid, event)

    def persist_events(self, sid: str) -> None:
        self._persist_events(sid)

    def pending_prompt_events(self, sid: str) -> list[dict]:
        return self._pending_prompts.events(sid)

    def _status_payload(self, sid: str, **payload: object) -> dict:
        return {**payload, "status": self.status(sid)}

    def _configured_provider(self) -> ProviderConfig | None:
        if self.config is None or not self.config.providers:
            return None
        return self.config.providers[0]

    def _set_agent_work_dir(self, sid: str, agent: Agent, work_dir: str) -> None:
        agent.work_dir = work_dir
        self.update_session_work_dir(sid, work_dir)

    async def _ensure_runtime(self, sid: str) -> DaemonSessionRuntime | None:
        if not await self.ensure_agent(sid):
            return None
        return self._agents.get(sid)

    async def _require_runtime(
        self,
        sid: str,
    ) -> tuple[DaemonSessionRuntime | None, DaemonActionResult | None]:
        runtime = await self._ensure_runtime(sid)
        if runtime is None:
            return None, session_not_found_result()
        return runtime, None

    async def _require_deps(
        self,
        sid: str,
    ) -> tuple[AgentDeps | None, DaemonActionResult | None]:
        runtime, error = await self._require_runtime(sid)
        if error is not None:
            return None, error
        assert runtime is not None
        return runtime.deps, None

    async def _require_agent_and_deps(
        self,
        sid: str,
    ) -> tuple[Agent | None, AgentDeps | None, DaemonActionResult | None]:
        runtime, error = await self._require_runtime(sid)
        if error is not None:
            return None, None, error
        assert runtime is not None
        return runtime.agent, runtime.deps, None

    async def _require_agent_and_conversation(
        self,
        sid: str,
    ) -> tuple[Agent | None, ConversationManager | None, DaemonActionResult | None]:
        runtime, error = await self._require_runtime(sid)
        if error is not None:
            return None, None, error
        assert runtime is not None
        return runtime.agent, runtime.conversation, None

    async def start_task(self, sid: str, prompt: str) -> str:
        """Start agent.run() as a background task. Returns task_id."""
        self._active_tasks.ensure_available(sid)
        runtime = await self._ensure_runtime(sid)
        log_list = self.get_event_log(sid)
        if runtime is None or log_list is None:
            raise ValueError(f"Session {sid} not found")

        return self._agent_task_runner.start(
            sid,
            prompt,
            runtime.agent,
            runtime.conversation,
        )

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
        agent, conv, error = await self._require_agent_and_conversation(sid)
        if error is not None:
            return error
        assert agent is not None and conv is not None

        return await run_manual_compact(
            sid=sid,
            agent=agent,
            conversation=conv,
            emit_event=self._emit,
            persist_events=self._persist_events,
            status_provider=self.status,
        )

    async def list_worktrees(self, sid: str) -> DaemonActionResult:
        deps, error = await self._require_deps(sid)
        if error is not None:
            return error
        assert deps is not None

        return DaemonActionResult(list_worktrees_payload(deps.worktree_manager))

    async def create_worktree(
        self,
        sid: str,
        name: str,
        base_branch: str = "HEAD",
    ) -> DaemonActionResult:
        try:
            name, base_branch = normalize_create_worktree_request(name, base_branch)
        except ValueError as e:
            return bad_request_result(str(e))

        agent, deps, error = await self._require_agent_and_deps(sid)
        if error is not None:
            return error
        assert agent is not None and deps is not None

        try:
            entry = await create_and_enter_worktree(
                deps.worktree_manager,
                name,
                base_branch,
            )
            self._set_agent_work_dir(sid, agent, entry.work_dir)
        except Exception as e:
            return bad_request_result(str(e))

        return DaemonActionResult(
            self._status_payload(
                sid,
                worktree=worktree_to_dict(entry.worktree, name),
            )
        )

    async def enter_worktree(self, sid: str, name: str) -> DaemonActionResult:
        agent, deps, error = await self._require_agent_and_deps(sid)
        if error is not None:
            return error
        assert agent is not None and deps is not None

        try:
            entry = await enter_worktree_action(deps.worktree_manager, name)
            self._set_agent_work_dir(sid, agent, entry.work_dir)
        except Exception as e:
            return bad_request_result(str(e))

        return DaemonActionResult(self._status_payload(sid, entered=True))

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
        try:
            entry = await exit_worktree_action(
                manager,
                remove=remove,
                discard=discard,
            )
            self._set_agent_work_dir(sid, agent, entry.work_dir)
        except Exception as e:
            return bad_request_result(str(e))

        return DaemonActionResult(self._status_payload(sid, exited=True))

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
        runtime = self._agents.get(sid)
        agent = runtime.agent if runtime is not None else None
        deps = runtime.deps if runtime is not None else None
        conv = runtime.conversation if runtime is not None else None
        meta = self._records.meta(sid)
        provider = deps.provider if deps is not None else self._configured_provider()
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
            active_task_id=self._active_tasks.task_id(sid),
            active_task_running=self._active_tasks.is_running(sid),
        )

    def cancel_active_task(self, sid: str) -> bool:
        return self._active_tasks.cancel(sid)

    async def resolve_permission(
        self, sid: str, request_id: str, response: str
    ) -> bool:
        """Resolve a pending permission request. response: allow|deny|allow_always."""
        return await self._resolve_pending_request(
            sid,
            request_id,
            PermissionResponse(response),
            "PermissionResolved",
        )

    async def resolve_askuser(
        self, sid: str, request_id: str, answers: dict[str, str]
    ) -> bool:
        """Resolve a pending ask_user request."""
        return await self._resolve_pending_request(
            sid,
            request_id,
            answers,
            "AskUserResolved",
        )

    async def _resolve_pending_request(
        self,
        sid: str,
        request_id: str,
        result: object,
        resolved_event_type: str,
    ) -> bool:
        session = await self.session_mgr.get_session(sid)
        if session is None:
            return False
        ok = session.resolve_future(request_id, result)
        if ok:
            self._pending_prompts.discard(sid, request_id)
            self._emit(
                sid,
                {
                    "type": resolved_event_type,
                    "data": {"request_id": request_id},
                },
            )
        return ok

    async def close_session(self, sid: str) -> None:
        """Clean up a session."""
        validate_session_id(sid)
        task = self._active_tasks.pop_task(sid)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self.session_mgr.close_session(sid)
        entry = self._agents.pop(sid, None)
        hub = getattr(entry.agent, "memory_hub", None) if entry is not None else None
        if hub is not None:
            await hub.shutdown()
        self._records.close(sid)
        self._pre_plan_modes.pop(sid, None)
        self._pending_prompts.discard_session(sid)
        log.info("Session %s closed", sid)
