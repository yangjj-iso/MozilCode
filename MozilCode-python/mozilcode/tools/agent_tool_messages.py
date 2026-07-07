from __future__ import annotations

from collections.abc import Iterable
from typing import Any


NO_SUBAGENT_OUTPUT = "(sub-agent returned no output)"


def available_agent_names(agent_listing: Iterable[tuple[str, Any]]) -> str:
    return ", ".join(name for name, _ in agent_listing)


def unknown_agent_type_message(
    agent_type: str,
    agent_listing: Iterable[tuple[str, Any]],
    *,
    available_label: str = "Available types",
) -> str:
    return (
        f"Unknown agent type: '{agent_type}'. "
        f"{available_label}: {available_agent_names(agent_listing)}"
    )


def fork_disabled_message() -> str:
    return (
        "Fork mode is not enabled. "
        "Set 'enable_fork: true' in config.yaml to use fork, "
        "or specify a subagent_type parameter."
    )


def background_launch_message(
    *,
    task_id: str,
    agent_name: str,
    agent_type: str,
) -> str:
    return (
        "Sub-agent launched in background.\n"
        f"Task ID: {task_id}\n"
        f"Agent: {agent_name}\n"
        f"Type: {agent_type}\n"
        "The system will notify automatically when it completes.\n"
        "Do NOT wait, sleep, or poll. Report the task ID to the user and move on."
    )


def empty_subagent_output(result_text: str) -> str:
    return result_text or NO_SUBAGENT_OUTPUT


def teammate_launch_message(
    *,
    teammate_name: str,
    team_name: str,
    agent_id: str,
    backend: str,
    worktree_path: str,
    task_id: str,
) -> str:
    return (
        f"Teammate '{teammate_name}' spawned in team '{team_name}'.\n"
        f"Agent ID: {agent_id}\n"
        f"Backend: {backend}\n"
        f"Worktree: {worktree_path}\n"
        f"Task ID: {task_id}\n"
        "The system will notify when it completes."
    )


def pane_spawn_failed_message(error: Exception) -> str:
    return (
        f"Pane spawn failed ({error}), teammate not started. "
        "Retry or set teammate_mode to in-process."
    )


def pane_teammate_launch_message(
    *,
    teammate_name: str,
    team_name: str,
    agent_id: str,
    backend: str,
    worktree_path: str,
) -> str:
    return (
        f"Teammate '{teammate_name}' spawned in team '{team_name}'.\n"
        f"Agent ID: {agent_id}\n"
        f"Backend: {backend} (pane)\n"
        f"Worktree: {worktree_path}\n"
        "The teammate is running in an independent process."
    )


def worktree_preserved_suffix(path: str, branch: str) -> str:
    return f"\n[Worktree preserved at {path}, branch {branch}]"
