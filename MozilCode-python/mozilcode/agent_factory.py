from __future__ import annotations

"""Shared construction for headless MozilCode Agent runtimes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mozilcode.agent import Agent
from mozilcode.agents.loader import AgentLoader
from mozilcode.agents.task_manager import TaskManager
from mozilcode.agents.trace import TraceManager
from mozilcode.client import create_client, resolve_context_window
from mozilcode.config import AppConfig, WorktreeConfig
from mozilcode.hooks import HookEngine
from mozilcode.memory.instructions import load_instructions
from mozilcode.memory.providers import build_memory_hub
from mozilcode.permissions import (
    DangerousCommandDetector,
    PathSandbox,
    PermissionChecker,
    PermissionMode,
    RuleEngine,
)
from mozilcode.teams.manager import TeamManager
from mozilcode.tools import create_default_registry
from mozilcode.tools.agent_tool import AgentTool
from mozilcode.tools.ask_user import AskUserTool
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
            teammate_mode="in-process",
            is_interactive=False,
            enable_coordinator_mode=config.enable_coordinator_mode,
        )
    )
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
