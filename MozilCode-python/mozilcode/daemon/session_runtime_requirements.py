from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from mozilcode.agent import Agent
from mozilcode.agent_factory import AgentDeps
from mozilcode.conversation import ConversationManager
from mozilcode.daemon.responses import DaemonActionResult, session_not_found_result
from mozilcode.daemon.session_runtime import DaemonSessionRuntime

EnsureAgent = Callable[[str], Awaitable[bool]]


class SessionRuntimeRequirements:
    """Resolve daemon session runtime dependencies for action modules."""

    def __init__(
        self,
        *,
        ensure_agent: EnsureAgent,
        runtimes: Mapping[str, DaemonSessionRuntime],
    ) -> None:
        self._ensure_agent = ensure_agent
        self._runtimes = runtimes

    async def ensure_runtime(self, sid: str) -> DaemonSessionRuntime | None:
        if not await self._ensure_agent(sid):
            return None
        return self._runtimes.get(sid)

    async def require_runtime(
        self,
        sid: str,
    ) -> tuple[DaemonSessionRuntime | None, DaemonActionResult | None]:
        runtime = await self.ensure_runtime(sid)
        if runtime is None:
            return None, session_not_found_result()
        return runtime, None

    async def require_deps(
        self,
        sid: str,
    ) -> tuple[AgentDeps | None, DaemonActionResult | None]:
        runtime, error = await self.require_runtime(sid)
        if error is not None:
            return None, error
        assert runtime is not None
        return runtime.deps, None

    async def require_agent_and_deps(
        self,
        sid: str,
    ) -> tuple[Agent | None, AgentDeps | None, DaemonActionResult | None]:
        runtime, error = await self.require_runtime(sid)
        if error is not None:
            return None, None, error
        assert runtime is not None
        return runtime.agent, runtime.deps, None

    async def require_agent_and_conversation(
        self,
        sid: str,
    ) -> tuple[Agent | None, ConversationManager | None, DaemonActionResult | None]:
        runtime, error = await self.require_runtime(sid)
        if error is not None:
            return None, None, error
        assert runtime is not None
        return runtime.agent, runtime.conversation, None
