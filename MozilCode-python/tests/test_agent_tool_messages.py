from __future__ import annotations

from mozilcode.tools.agent.messages import (
    NO_SUBAGENT_OUTPUT,
    available_agent_names,
    background_launch_message,
    empty_subagent_output,
    fork_disabled_message,
    pane_spawn_failed_message,
    pane_teammate_launch_message,
    teammate_launch_message,
    unknown_agent_type_message,
    worktree_preserved_suffix,
)


def test_available_agent_names_formats_loader_listing() -> None:
    assert available_agent_names([("Explore", "desc"), ("Plan", "desc")]) == (
        "Explore, Plan"
    )


def test_unknown_agent_type_message_uses_configurable_label() -> None:
    message = unknown_agent_type_message(
        "Missing",
        [("Explore", "desc")],
        available_label="Available",
    )

    assert message == "Unknown agent type: 'Missing'. Available: Explore"


def test_fork_disabled_message_preserves_guidance() -> None:
    message = fork_disabled_message()

    assert "enable_fork: true" in message
    assert "subagent_type" in message


def test_background_launch_message_contains_task_identity() -> None:
    message = background_launch_message(
        task_id="task-1",
        agent_name="worker",
        agent_type="Explore",
    )

    assert "Sub-agent launched in background." in message
    assert "Task ID: task-1" in message
    assert "Agent: worker" in message
    assert "Type: Explore" in message
    assert "Do NOT wait" in message


def test_empty_subagent_output_falls_back_when_blank() -> None:
    assert empty_subagent_output("") == NO_SUBAGENT_OUTPUT
    assert empty_subagent_output("done") == "done"


def test_teammate_launch_message_contains_runtime_details() -> None:
    message = teammate_launch_message(
        teammate_name="alice",
        team_name="core",
        agent_id="agent-1",
        backend="in-process",
        worktree_path="/repo/wt",
        task_id="task-1",
    )

    assert "Teammate 'alice' spawned in team 'core'." in message
    assert "Agent ID: agent-1" in message
    assert "Backend: in-process" in message
    assert "Worktree: /repo/wt" in message
    assert "Task ID: task-1" in message


def test_pane_spawn_failed_message_includes_exception() -> None:
    assert pane_spawn_failed_message(RuntimeError("boom")) == (
        "Pane spawn failed (boom), teammate not started. "
        "Retry or set teammate_mode to in-process."
    )


def test_pane_teammate_launch_message_marks_pane_backend() -> None:
    message = pane_teammate_launch_message(
        teammate_name="alice",
        team_name="core",
        agent_id="agent-1",
        backend="tmux",
        worktree_path="/repo/wt",
    )

    assert "Backend: tmux (pane)" in message
    assert "independent process" in message


def test_worktree_preserved_suffix_formats_cleanup_notice() -> None:
    assert worktree_preserved_suffix("/repo/wt", "branch-1") == (
        "\n[Worktree preserved at /repo/wt, branch branch-1]"
    )
