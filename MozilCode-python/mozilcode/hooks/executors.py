from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from urllib.request import Request, urlopen
from urllib.error import URLError

from mozilcode.hooks.models import Action, ActionResult, HookContext

log = logging.getLogger(__name__)

AgentRunnerResult = ActionResult | str
AgentActionRunner = Callable[
    [str, HookContext],
    AgentRunnerResult | Awaitable[AgentRunnerResult],
]


async def execute_command(action: Action, ctx: HookContext) -> ActionResult:
    command = ctx.expand(action.command)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=action.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ActionResult(
                output=f"Command timed out after {action.timeout}s: {command}",
                success=False,
            )
        output = stdout.decode(errors="replace").strip() if stdout else ""
        return ActionResult(output=output, success=proc.returncode == 0)
    except Exception as e:
        return ActionResult(output=f"Command execution error: {e}", success=False)


async def execute_prompt(action: Action, ctx: HookContext) -> ActionResult:
    message = ctx.expand(action.message)
    return ActionResult(output=message, success=True)


async def execute_http(action: Action, ctx: HookContext) -> ActionResult:
    url = ctx.expand(action.url)
    body = ctx.expand(action.body) if action.body else None
    method = action.method or "POST"

    headers = dict(action.headers)
    for k, v in headers.items():
        headers[k] = ctx.expand(v)
    if body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"


    def _do_request() -> ActionResult:
        try:
            data = body.encode() if body else None
            req = Request(url, data=data, headers=headers, method=method)
            with urlopen(req, timeout=action.timeout) as resp:
                resp_body = resp.read().decode(errors="replace")[:500]
                return ActionResult(
                    output=f"HTTP {resp.status}: {resp_body}",
                    success=200 <= resp.status < 300,
                )
        except URLError as e:
            return ActionResult(output=f"HTTP error: {e}", success=False)
        except Exception as e:
            return ActionResult(output=f"HTTP error: {e}", success=False)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _do_request)


async def execute_agent(
    action: Action,
    ctx: HookContext,
    agent_runner: AgentActionRunner | None = None,
) -> ActionResult:
    prompt = ctx.expand(action.prompt)
    if agent_runner is None:
        return ActionResult(
            output="agent action requires a configured hook agent runner",
            success=False,
        )

    try:
        result = agent_runner(prompt, ctx)
        if inspect.isawaitable(result):
            result = await result
    except Exception as e:
        log.warning("Hook agent runner failed: %s", e)
        return ActionResult(output=f"Agent runner error: {e}", success=False)

    if isinstance(result, ActionResult):
        return result
    return ActionResult(output=str(result), success=True)


_EXECUTOR_MAP = {
    "command": execute_command,
    "prompt": execute_prompt,
    "http": execute_http,
    "agent": execute_agent,
}


async def execute_action(
    action: Action,
    ctx: HookContext,
    agent_runner: AgentActionRunner | None = None,
) -> ActionResult:
    executor = _EXECUTOR_MAP.get(action.type)
    if executor is None:
        return ActionResult(
            output=f"Unknown action type: {action.type}",
            success=False,
        )
    if action.type == "agent":
        return await execute_agent(action, ctx, agent_runner)
    return await executor(action, ctx)
