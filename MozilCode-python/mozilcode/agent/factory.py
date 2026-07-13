from __future__ import annotations

"""Shared construction for headless MozilCode Agent runtimes."""

from dataclasses import dataclass
from pathlib import Path

from mozilcode.agent import Agent
from mozilcode.agents.loader import AgentLoader
from mozilcode.agents.task_manager import TaskManager
from mozilcode.agents.trace import TraceManager
from mozilcode.client import create_client, resolve_context_window
from mozilcode.config import AppConfig, ProviderConfig, WorktreeConfig
from mozilcode.hooks import HookEngine
from mozilcode.memory.instructions import load_instructions
from mozilcode.memory.providers import build_memory_hub
from mozilcode.mcp import MCPManager
from mozilcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from mozilcode.teams.manager import TeamManager
from mozilcode.tools import ToolRegistry, create_default_registry
from mozilcode.tools.agent.tool import AgentTool
from mozilcode.tools.ask_user import AskUserTool
from mozilcode.tools.exit_plan_mode import ExitPlanModeTool
from mozilcode.tools.impl.tool_search import ToolSearchTool
from mozilcode.tools.team_create import TeamCreateTool
from mozilcode.tools.team_delete import TeamDeleteTool
from mozilcode.worktree import WorktreeManager


@dataclass
class AgentDeps:
    """Container for subsystem references created alongside an Agent."""

    task_manager: TaskManager
    team_manager: TeamManager
    trace_manager: TraceManager
    agent_loader: AgentLoader
    worktree_manager: WorktreeManager
    provider: ProviderConfig
    mcp_manager: MCPManager | None = None


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

    instructions = load_instructions(work_dir)
    memory_hub = build_memory_hub(config.memory, work_dir)
    registry = _create_base_registry(provider.protocol, work_dir)
    mcp_manager = MCPManager()
    mcp_manager.load_configs(config.mcp_servers)
    mcp_errors = await mcp_manager.register_all_tools(registry)
    for error in mcp_errors:
        # MCP is optional: a failed external server must not prevent local tools.
        import logging
        logging.getLogger(__name__).warning(error)

    agent = Agent(
        client=client,
        registry=registry,
        protocol=provider.protocol,
        work_dir=work_dir,
        permission_checker=_create_permission_checker(work_dir, permission_mode),
        context_window=provider.get_context_window(),
        instructions_content=instructions,
        memory_hub=memory_hub,
        hook_engine=hook_engine,
    )

    deps = _create_agent_deps(config, work_dir, provider, agent, registry, mcp_manager)
    return agent, deps


def _create_permission_checker(
    work_dir: str,
    permission_mode: PermissionMode,
) -> PermissionChecker:
    home = Path.home()
    work_path = Path(work_dir)
    return PermissionChecker(
        detector=DangerousCommandDetector(),
        sandbox=PathSandbox(work_dir),
        rule_engine=RuleEngine(
            user_rules_path=home / ".mozilcode" / "permissions.yaml",
            project_rules_path=work_path / ".mozilcode" / "permissions.yaml",
            local_rules_path=work_path / ".mozilcode" / "permissions.local.yaml",
        ),
        mode=permission_mode,
    )


def _create_base_registry(protocol: str, work_dir: str) -> ToolRegistry:
    registry = create_default_registry(base_dir=work_dir)
    registry.register(ToolSearchTool(registry, protocol=protocol))
    registry.register(AskUserTool())
    registry.register(ExitPlanModeTool())
    return registry


def _create_agent_deps(
    config: AppConfig,
    work_dir: str,
    provider: ProviderConfig,
    agent: Agent,
    registry: ToolRegistry,
    mcp_manager: MCPManager | None = None,
) -> AgentDeps:
    wt_cfg = config.worktree or WorktreeConfig()
    wt_manager = WorktreeManager(
        repo_root=work_dir,
        symlink_directories=wt_cfg.symlink_directories,
    )
    trace_manager = TraceManager()
    task_manager = TaskManager()
    agent_loader = AgentLoader(
        work_dir,
        enable_verification=config.enable_verification_agent,
    )
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
    registry.register(
        TeamCreateTool(
            team_manager=team_manager,
            parent_agent=agent,
            teammate_mode=config.teammate_mode,
            is_interactive=False,
            enable_coordinator_mode=config.enable_coordinator_mode,
        )
    )
    registry.register(TeamDeleteTool(team_manager=team_manager, parent_agent=agent))

    def drain_mailbox() -> list[str]:
        return team_manager.drain_lead_mailbox()

    agent.notification_fn = drain_mailbox

    return AgentDeps(
        task_manager=task_manager,
        team_manager=team_manager,
        trace_manager=trace_manager,
        agent_loader=agent_loader,
        worktree_manager=wt_manager,
        provider=provider,
        mcp_manager=mcp_manager,
    )
