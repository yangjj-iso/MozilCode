from __future__ import annotations

from mozilcode.agents.parser import AgentDef


def _default_agent_def(
    *,
    agent_type: str,
    when_to_use: str,
    max_turns: int,
) -> AgentDef:
    return AgentDef(
        agent_type=agent_type,
        when_to_use=when_to_use,
        system_prompt="",
        disallowed_tools=[],
        model="inherit",
        max_turns=max_turns,
        permission_mode="dontAsk",
        source="builtin",
    )


def fork_agent_def(max_turns: int) -> AgentDef:
    return _default_agent_def(
        agent_type="fork",
        when_to_use="Forked from parent agent",
        max_turns=max_turns,
    )


def teammate_agent_def(max_turns: int) -> AgentDef:
    return _default_agent_def(
        agent_type="teammate",
        when_to_use="Team member",
        max_turns=max_turns,
    )


def worktree_agent_def(max_turns: int) -> AgentDef:
    return _default_agent_def(
        agent_type="worktree-agent",
        when_to_use="Isolated worktree agent",
        max_turns=max_turns,
    )
