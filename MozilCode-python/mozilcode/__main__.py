
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from mozilcode.agents.notification import format_task_notification
from mozilcode.config import ConfigError, load_config
from mozilcode.conversation import ConversationManager
from mozilcode.hooks import HookConfigError, HookEngine, load_hooks
from mozilcode.permissions import PermissionMode


def main() -> None:
    # 先确保 .mozilcode/ 目录存在，否则下面写 debug.log 会因目录不存在而崩溃
    Path(".mozilcode").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        filename=".mozilcode/debug.log",
        filemode="w",
    )

    parser = argparse.ArgumentParser(prog="mozilcode", description="MozilCode AI coding assistant")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in PermissionMode],
        default=None,
        help="Permission mode (overrides config.yaml)",
    )
    parser.add_argument(
        "-p",
        metavar="PROMPT",
        default=None,
        help="Run non-interactively: execute the prompt and print the result to stdout",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    mode_str = args.mode if args.mode else config.permission_mode
    permission_mode = PermissionMode(mode_str)

    try:
        hooks = load_hooks(config.raw_hooks)
    except HookConfigError as e:
        print(f"Hook config error: {e}", file=sys.stderr)
        sys.exit(1)

    hook_engine = HookEngine(hooks) if hooks else None

    if args.p is not None:
        asyncio.run(_run_prompt(config, permission_mode, hook_engine, args.p))
        return

    from mozilcode.app import MozilCodeApp
    from mozilcode.driver import NoAltScreenDriver

    app = MozilCodeApp(
        providers=config.providers,
        permission_mode=permission_mode,
        mcp_servers=config.mcp_servers,
        hook_engine=hook_engine,
        enable_fork=config.enable_fork,
        enable_verification_agent=config.enable_verification_agent,
        worktree_config=config.worktree,
        teammate_mode=config.teammate_mode,
        enable_coordinator_mode=config.enable_coordinator_mode,
        driver_class=NoAltScreenDriver,
    )
    app.run()


async def _run_prompt(config, permission_mode, hook_engine, prompt: str) -> None:
    work_dir = os.getcwd()
    from mozilcode.agent.factory import create_agent_from_config

    agent, deps = await create_agent_from_config(
        config,
        work_dir,
        permission_mode,
        hook_engine,
    )
    task_manager = deps.task_manager
    team_manager = deps.team_manager
    try:
        await _run_prompt_loop(agent, task_manager, team_manager, prompt)
    finally:
        if agent.memory_hub:
            await agent.memory_hub.shutdown()


async def _run_prompt_loop(agent, task_manager, team_manager, prompt: str) -> None:
    conv = ConversationManager()
    last_result = await agent.run_to_completion(prompt, conv)
    print(last_result, flush=True)

    if not team_manager.has_teams():
        return

    for i in range(90):
        await asyncio.sleep(2)
        running = task_manager.running_task_states()
        completed_ids = task_manager.completed_task_ids()
        queue_size = task_manager.notification_queue_size()
        print(
            f"[poll {i}] running={running} completed={completed_ids} "
            f"teams={team_manager.team_names()} queue_size={queue_size}",
            file=sys.stderr,
            flush=True,
        )
        notes = _drain_cli_notifications(task_manager, team_manager)
        if not notes:
            if not task_manager.has_running_tasks():
                print(f"[poll {i}] no running tasks, breaking", file=sys.stderr, flush=True)
                break
            continue
        for note in notes:
            conv.add_system_reminder(note)
        last_result = await agent.run_to_completion(
            "Teammate notifications received. Process them and continue.", conv
        )
        print(last_result, flush=True)


def _drain_cli_notifications(task_manager, team_manager) -> list[str]:
    notes = [
        format_task_notification(task)
        for task in task_manager.poll_completed()
    ]
    notes.extend(team_manager.drain_lead_mailbox())
    return notes


if __name__ == "__main__":
    main()
