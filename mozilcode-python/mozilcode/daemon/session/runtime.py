"""DaemonSessionRuntime 创建与持有。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mozilcode.agent import Agent
from mozilcode.agent.factory import AgentDeps, create_agent_from_config
from mozilcode.config import AppConfig
from mozilcode.conversation import ConversationManager
from mozilcode.daemon.session import SessionManager
from mozilcode.hooks import HookEngine
from mozilcode.permissions import PermissionMode


@dataclass(frozen=True)
class DaemonSessionRuntime:
    agent: Agent
    deps: AgentDeps
    conversation: ConversationManager


AgentFactory = Callable[
    [AppConfig, str, PermissionMode, HookEngine | None],
    Awaitable[tuple[Agent, AgentDeps]],
]


async def create_daemon_session_runtime(
    *,
    sid: str,
    config: AppConfig,
    work_dir: str,
    permission_mode: PermissionMode,
    hook_engine: HookEngine | None,
    session_mgr: SessionManager,
    agent_factory: AgentFactory = create_agent_from_config,
    register_session: bool = True,
    conversation: ConversationManager | None = None,
) -> DaemonSessionRuntime:
    agent, deps = await agent_factory(
        config,
        work_dir,
        permission_mode,
        hook_engine,
    )
    agent.session_id = sid
    conversation = conversation or ConversationManager()
    runtime = DaemonSessionRuntime(agent, deps, conversation)
    if register_session:
        await session_mgr.create_session(sid, agent, conversation)
    return runtime
