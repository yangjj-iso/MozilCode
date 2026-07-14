"""会话维度的 worktree 列表与切换动作。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mozilcode.daemon.responses import (
    DaemonActionResult,
    bad_request_result,
)
from mozilcode.daemon.workspace_payloads import worktree_to_dict
from mozilcode.daemon.actions.worktree import (
    create_and_enter_worktree,
    enter_worktree as enter_worktree_action,
    exit_worktree as exit_worktree_action,
    list_worktrees_payload,
    normalize_create_worktree_request,
)

RequireDeps = Callable[[str], Awaitable[tuple[Any | None, DaemonActionResult | None]]]
RequireAgentAndDeps = Callable[
    [str],
    Awaitable[tuple[Any | None, Any | None, DaemonActionResult | None]],
]
SetAgentWorkDir = Callable[[str, Any, str], None]
StatusProvider = Callable[[str], dict]


def _status_payload(
    sid: str,
    status_provider: StatusProvider,
    **payload: object,
) -> dict:
    return {**payload, "status": status_provider(sid)}


async def list_session_worktrees(
    sid: str,
    require_deps: RequireDeps,
) -> DaemonActionResult:
    deps, error = await require_deps(sid)
    if error is not None:
        return error
    assert deps is not None
    return DaemonActionResult(list_worktrees_payload(deps.worktree_manager))


async def create_session_worktree(
    sid: str,
    name: str,
    base_branch: str,
    *,
    require_agent_and_deps: RequireAgentAndDeps,
    set_agent_work_dir: SetAgentWorkDir,
    status_provider: StatusProvider,
) -> DaemonActionResult:
    try:
        name, base_branch = normalize_create_worktree_request(name, base_branch)
    except ValueError as e:
        return bad_request_result(str(e))

    agent, deps, error = await require_agent_and_deps(sid)
    if error is not None:
        return error
    assert agent is not None and deps is not None

    try:
        entry = await create_and_enter_worktree(
            deps.worktree_manager,
            name,
            base_branch,
        )
        set_agent_work_dir(sid, agent, entry.work_dir)
    except Exception as e:
        return bad_request_result(str(e))

    return DaemonActionResult(
        _status_payload(
            sid,
            status_provider,
            worktree=worktree_to_dict(entry.worktree, name),
        )
    )


async def enter_session_worktree(
    sid: str,
    name: str,
    *,
    require_agent_and_deps: RequireAgentAndDeps,
    set_agent_work_dir: SetAgentWorkDir,
    status_provider: StatusProvider,
) -> DaemonActionResult:
    agent, deps, error = await require_agent_and_deps(sid)
    if error is not None:
        return error
    assert agent is not None and deps is not None

    try:
        entry = await enter_worktree_action(deps.worktree_manager, name)
        set_agent_work_dir(sid, agent, entry.work_dir)
    except Exception as e:
        return bad_request_result(str(e))

    return DaemonActionResult(
        _status_payload(sid, status_provider, entered=True)
    )


async def exit_session_worktree(
    sid: str,
    *,
    remove: bool,
    discard: bool,
    require_agent_and_deps: RequireAgentAndDeps,
    set_agent_work_dir: SetAgentWorkDir,
    status_provider: StatusProvider,
) -> DaemonActionResult:
    agent, deps, error = await require_agent_and_deps(sid)
    if error is not None:
        return error
    assert agent is not None and deps is not None

    try:
        entry = await exit_worktree_action(
            deps.worktree_manager,
            remove=remove,
            discard=discard,
        )
        set_agent_work_dir(sid, agent, entry.work_dir)
    except Exception as e:
        return bad_request_result(str(e))

    return DaemonActionResult(
        _status_payload(sid, status_provider, exited=True)
    )
