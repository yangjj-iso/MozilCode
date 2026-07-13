from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from urllib.request import Request, urlopen
from urllib.error import URLError

from mozilcode.hooks.models import Action, ActionResult, HookContext

log = logging.getLogger(__name__)

# agent 类型 action 的返回值类型：ActionResult 或纯字符串
AgentRunnerResult = ActionResult | str
# agent 类型 action 的执行器回调签名（接收 prompt 和上下文，返回结果）
AgentActionRunner = Callable[
    [str, HookContext],
    AgentRunnerResult | Awaitable[AgentRunnerResult],
]


async def execute_command(action: Action, ctx: HookContext) -> ActionResult:
    """执行 shell 命令（command 类型 action）。

    使用 asyncio.create_subprocess_shell 异步执行，支持超时。
    模板变量（如 $FILE_PATH）会被 ctx.expand() 替换为实际值。
    """
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
    """注入提示消息（prompt 类型 action）。

    不执行任何外部操作，只返回展开后的消息文本。
    HookEngine 会将其收集到 _prompt_messages，由 Agent 在 pre_send 后注入 system prompt。
    """
    message = ctx.expand(action.message)
    return ActionResult(output=message, success=True)


async def execute_http(action: Action, ctx: HookContext) -> ActionResult:
    """发送 HTTP 请求（http 类型 action）。

    使用 urllib（而非 aiohttp）保持零额外依赖，通过 run_in_executor 在线程池中执行。
    支持自定义 method / headers / body，模板变量会被展开。
    响应体只取前 500 字符以避免过长。
    """
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
    """派生子 Agent 处理（agent 类型 action）。

    通过 agent_runner 回调执行，该回调由 Agent 在初始化 HookEngine 时注入。
    支持同步和异步两种回调签名（inspect.isawaitable 检测）。
    典型用途：自动代码审查、生成 commit 消息等。
    """
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


# action type → 执行器 的映射表
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
    """统一入口：根据 action.type 分发到对应的执行器。

    由 HookEngine._run_single() 调用，是所有 Hook action 执行的入口点。
    agent 类型需要额外的 agent_runner 参数，其余类型只需 action 和 ctx。
    """
    executor = _EXECUTOR_MAP.get(action.type)
    if executor is None:
        return ActionResult(
            output=f"Unknown action type: {action.type}",
            success=False,
        )
    if action.type == "agent":
        return await execute_agent(action, ctx, agent_runner)
    return await executor(action, ctx)
