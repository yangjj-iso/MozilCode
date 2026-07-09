from __future__ import annotations

import logging

from mozilcode.agent import Agent
from mozilcode.agent.events import PermissionResponse
from mozilcode.config import AppConfig
from mozilcode.conversation import ConversationManager
from mozilcode.agent.factory import AgentDeps, create_agent_from_config
from mozilcode.daemon.active_tasks import ActiveTaskRegistry
from mozilcode.daemon.agent_task_runner import AgentTaskRunner
from mozilcode.daemon.background_task_actions import (
    cancel_session_background_task,
    list_session_background_tasks,
)
from mozilcode.daemon.compact_actions import run_manual_compact
from mozilcode.daemon.foreground_task_actions import start_session_task
from mozilcode.daemon.session import SessionManager
from mozilcode.daemon.session.records import SessionRecords
from mozilcode.daemon.session.store import SessionStore
from mozilcode.daemon.responses import (
    DaemonActionResult,
)
from mozilcode.daemon.pending_prompts import PendingPromptRegistry
from mozilcode.daemon.pending_prompt_actions import resolve_session_pending_prompt
from mozilcode.daemon.permission_mode_actions import set_session_permission_mode
from mozilcode.daemon.session.close_actions import close_daemon_session
from mozilcode.daemon.session.lifecycle_actions import (
    ensure_session_runtime,
    init_daemon_session,
)
from mozilcode.daemon.session.runtime import (
    DaemonSessionRuntime,
)
from mozilcode.daemon.session.runtime_requirements import SessionRuntimeRequirements
from mozilcode.daemon.session.status_actions import build_daemon_session_status
from mozilcode.daemon.worktree_session_actions import (
    create_session_worktree,
    enter_session_worktree,
    exit_session_worktree,
    list_session_worktrees,
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
        self._active_tasks = ActiveTaskRegistry()
        self._runtime_requirements = SessionRuntimeRequirements(
            ensure_agent=self.ensure_agent,
            runtimes=self._agents,
        )
        self._pre_plan_modes: dict[str, PermissionMode] = {}
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

    async def init_session(
        self, session_id: str | None = None, work_dir: str | None = None
    ) -> str:
        """Create a new Agent session in the given workspace. Returns session_id."""
        sid = await init_daemon_session(
            session_id=session_id,
            work_dir=work_dir,
            config=self.config,
            default_work_dir=self.work_dir,
            hook_engine=self.hook_engine,
            session_mgr=self.session_mgr,
            runtimes=self._agents,
            records=self._records,
            agent_factory=create_agent_from_config,
        )
        log.info("Session %s initialized (work_dir=%s)", sid, self.session_work_dir(sid))
        return sid

    async def ensure_agent(self, sid: str) -> bool:
        """Make sure an Agent exists for a session, creating one lazily."""
        existed = sid in self._agents
        ok = await ensure_session_runtime(
            sid=sid,
            config=self.config,
            default_work_dir=self.work_dir,
            hook_engine=self.hook_engine,
            session_mgr=self.session_mgr,
            runtimes=self._agents,
            session_meta=self._records.session_meta,
            records=self._records,
            agent_factory=create_agent_from_config,
        )
        if ok and not existed:
            log.info("Session %s reactivated (work_dir=%s)", sid, self.session_work_dir(sid))
        return ok

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

    def _set_agent_work_dir(self, sid: str, agent: Agent, work_dir: str) -> None:
        agent.work_dir = work_dir
        self.update_session_work_dir(sid, work_dir)

    async def start_task(self, sid: str, prompt: str) -> str:
        """Start agent.run() as a background task. Returns task_id."""
        return await start_session_task(
            sid=sid,
            prompt=prompt,
            active_tasks=self._active_tasks,
            runtime_requirements=self._runtime_requirements,
            get_event_log=self.get_event_log,
            task_runner=self._agent_task_runner,
        )

    async def set_permission_mode(self, sid: str, mode: str) -> dict:
        """Switch a session's permission mode and return fresh status."""
        return await set_session_permission_mode(
            sid,
            mode,
            ensure_agent=self.ensure_agent,
            get_agent=self.get_agent,
            pre_plan_modes=self._pre_plan_modes,
            status_provider=self.status,
            emit_event=self._emit,
        )

    async def manual_compact(self, sid: str) -> DaemonActionResult:
        agent, conv, error = (
            await self._runtime_requirements.require_agent_and_conversation(sid)
        )
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
        return await list_session_worktrees(
            sid,
            self._runtime_requirements.require_deps,
        )

    async def create_worktree(
        self,
        sid: str,
        name: str,
        base_branch: str = "HEAD",
    ) -> DaemonActionResult:
        return await create_session_worktree(
            sid,
            name,
            base_branch,
            require_agent_and_deps=self._runtime_requirements.require_agent_and_deps,
            set_agent_work_dir=self._set_agent_work_dir,
            status_provider=self.status,
        )

    async def enter_worktree(self, sid: str, name: str) -> DaemonActionResult:
        return await enter_session_worktree(
            sid,
            name,
            require_agent_and_deps=self._runtime_requirements.require_agent_and_deps,
            set_agent_work_dir=self._set_agent_work_dir,
            status_provider=self.status,
        )

    async def exit_worktree(
        self,
        sid: str,
        *,
        remove: bool = False,
        discard: bool = False,
    ) -> DaemonActionResult:
        return await exit_session_worktree(
            sid,
            remove=remove,
            discard=discard,
            require_agent_and_deps=self._runtime_requirements.require_agent_and_deps,
            set_agent_work_dir=self._set_agent_work_dir,
            status_provider=self.status,
        )

    async def list_background_tasks(self, sid: str) -> DaemonActionResult:
        return await list_session_background_tasks(
            sid,
            self._runtime_requirements.require_deps,
        )

    async def cancel_background_task(
        self,
        sid: str,
        task_id: str,
    ) -> DaemonActionResult:
        return await cancel_session_background_task(
            sid,
            task_id,
            self._runtime_requirements.require_deps,
        )

    def status(self, sid: str) -> dict:
        return build_daemon_session_status(
            sid=sid,
            config=self.config,
            server_work_dir=self.work_dir,
            runtime=self._agents.get(sid),
            records=self._records,
            active_tasks=self._active_tasks,
            pre_plan_modes=self._pre_plan_modes,
        )

    def cancel_active_task(self, sid: str) -> bool:
        return self._active_tasks.cancel(sid)

    async def resolve_permission(
        self, sid: str, request_id: str, response: str
    ) -> bool:
        """Resolve a pending permission request. response: allow|deny|allow_always."""
        return await resolve_session_pending_prompt(
            sid,
            request_id,
            PermissionResponse(response),
            "PermissionResolved",
            session_mgr=self.session_mgr,
            pending_prompts=self._pending_prompts,
            emit_event=self._emit,
        )

    async def resolve_askuser(
        self, sid: str, request_id: str, answers: dict[str, str]
    ) -> bool:
        """Resolve a pending ask_user request."""
        return await resolve_session_pending_prompt(
            sid,
            request_id,
            answers,
            "AskUserResolved",
            session_mgr=self.session_mgr,
            pending_prompts=self._pending_prompts,
            emit_event=self._emit,
        )

    async def close_session(self, sid: str) -> None:
        """Clean up a session."""
        await close_daemon_session(
            sid,
            active_tasks=self._active_tasks,
            session_mgr=self.session_mgr,
            runtimes=self._agents,
            records=self._records,
            pre_plan_modes=self._pre_plan_modes,
            pending_prompts=self._pending_prompts,
        )
        log.info("Session %s closed", sid)
