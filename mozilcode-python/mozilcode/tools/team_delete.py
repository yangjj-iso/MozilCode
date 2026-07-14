"""TeamDelete 工具：删除 Agent 团队。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from mozilcode.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from mozilcode.agent import Agent
    from mozilcode.teams.manager import TeamManager


class TeamDeleteParams(BaseModel):
    team_name: str


class TeamDeleteTool(Tool):
    name = "TeamDelete"
    description = (
        "Delete an Agent Team. Terminates all pane processes, removes worktrees, "
        "cleans up mailbox and team directory. Requires all members to be idle."
    )
    params_model = TeamDeleteParams
    category = "command"
    is_concurrency_safe = False


    def __init__(self, team_manager: TeamManager, parent_agent: Agent | None = None) -> None:
        self._team_manager = team_manager
        self._parent_agent = parent_agent


    async def execute(self, params: BaseModel) -> ToolResult:
        p: TeamDeleteParams = params  # type: ignore[assignment]

        from mozilcode.teams.manager import TeamError

        try:
            self._team_manager.delete_team(p.team_name)
        except TeamError as e:
            return ToolResult(output=str(e), is_error=True)
        except Exception as e:
            return ToolResult(output=f"Failed to delete team: {e}", is_error=True)

        coordinator_note = ""
        if self._parent_agent and self._parent_agent.coordinator_mode:
            full_registry = getattr(self._parent_agent, '_full_registry', None)
            if full_registry is not None:
                self._parent_agent.registry = full_registry
                self._parent_agent._full_registry = None
            self._parent_agent.coordinator_mode = False
            coordinator_note = "\nCoordinator Mode deactivated: full tools restored."

        return ToolResult(output=f"Team '{p.team_name}' deleted successfully.{coordinator_note}")
