from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from mozilcode.hooks.executors import AgentActionRunner, execute_action
from mozilcode.hooks.models import ActionResult, Hook, HookContext, ToolRejectedError

log = logging.getLogger(__name__)


@dataclass
class HookNotification:
    hook_id: str
    event: str
    output: str
    success: bool


class HookEngine:
    """Hook 引擎：管理所有 Hook 配置，在生命周期事件触发时匹配并执行。

    核心职责：
    1. find_matching_hooks(): 根据事件名 + 条件匹配 Hook
    2. run_hooks(): 同步执行匹配的 Hook（阻塞 Agent 循环）
    3. run_pre_tool_hooks(): 执行 pre_tool_use Hook，可以 reject 拦截工具
    4. _schedule_background_hook(): 异步执行 Hook（不阻塞 Agent 循环）
    """
    def __init__(
        self,
        hooks: list[Hook] | None = None,
        agent_runner: AgentActionRunner | None = None,
    ) -> None:
        self.hooks: list[Hook] = hooks or []
        self.agent_runner = agent_runner       # agent 类型 action 的执行器
        self._prompt_messages: list[str] = []   # prompt action 产生的注入消息
        self._notifications: list[HookNotification] = []  # Hook 执行结果通知
        self._background_tasks: set[asyncio.Task[None]] = set()  # 后台异步任务集


    def find_matching_hooks(self, event: str, ctx: HookContext) -> list[Hook]:
        """根据事件名和条件匹配 Hook。检查三个条件：
        1. 事件名匹配
        2. once 标记检查（已执行过的 once Hook 跳过）
        3. condition 条件评估（如果配置了条件）
        """
        matched: list[Hook] = []
        for hook in self.hooks:
            if hook.event != event:
                continue
            if not hook.should_run():
                continue
            if hook.condition is not None and not hook.condition.evaluate(ctx):
                continue
            matched.append(hook)
        return matched


    async def run_hooks(self, event: str, ctx: HookContext) -> None:
        """执行匹配的 Hook。支持同步和异步两种模式。

        - 同步模式（默认）：阻塞 Agent 循环，等 Hook 执行完毕
        - 异步模式（async_exec=True）：后台 asyncio.Task 执行，不阻塞
        """
        matched = self.find_matching_hooks(event, ctx)
        for hook in matched:
            hook.mark_executed()
            if hook.async_exec:
                self._schedule_background_hook(hook, ctx)
            else:
                await self._run_single(hook, ctx)

    def _schedule_background_hook(self, hook: Hook, ctx: HookContext) -> None:
        task = asyncio.create_task(
            self._run_single(hook, ctx),
            name=f"mozilcode-hook-{hook.id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_task_done)

    def _on_background_task_done(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            log.info("Async hook task was cancelled")
        except Exception as e:
            log.warning("Async hook task failed unexpectedly: %s", e)

    async def wait_for_async_hooks(self) -> None:
        while self._background_tasks:
            pending = tuple(self._background_tasks)
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run_single(self, hook: Hook, ctx: HookContext) -> None:
        try:
            result = await execute_action(
                hook.action,
                ctx,
                self.agent_runner,
            )
            if hook.action.type == "prompt" and result.success:
                self._prompt_messages.append(result.output)
            self._record_result(hook, hook.event, result)
            if not result.success:
                log.warning(
                    "Hook '%s' action failed: %s", hook.id, result.output
                )
        except Exception as e:
            log.warning("Hook '%s' execution error: %s", hook.id, e)
            self._record_error(hook, hook.event, e)


    async def run_pre_tool_hooks(
        self, ctx: HookContext
    ) -> ToolRejectedError | None:
        """执行 pre_tool_use Hook，可以拒绝工具执行。

        与普通 run_hooks 的区别：
        - 如果 Hook 配置了 reject: true，返回 ToolRejectedError
        - Agent 收到 rejection 后跳过工具执行，将拒绝原因返回给 LLM
        """
        matched = self.find_matching_hooks("pre_tool_use", ctx)
        for hook in matched:
            hook.mark_executed()
            try:
                result = await execute_action(
                    hook.action,
                    ctx,
                    self.agent_runner,
                )
                self._record_result(hook, "pre_tool_use", result)
                if hook.reject:                     # 配置了拒绝标记
                    return ToolRejectedError(
                        tool=ctx.tool_name,
                        reason=result.output,
                        hook_id=hook.id,
                    )
            except Exception as e:
                log.warning("Hook '%s' execution error: %s", hook.id, e)
                self._record_error(hook, "pre_tool_use", e)
        return None

    def _record_result(
        self,
        hook: Hook,
        event: str,
        result: ActionResult,
    ) -> None:
        self._notifications.append(
            HookNotification(
                hook_id=hook.id,
                event=event,
                output=result.output,
                success=result.success,
            )
        )

    def _record_error(self, hook: Hook, event: str, error: Exception) -> None:
        self._notifications.append(
            HookNotification(
                hook_id=hook.id,
                event=event,
                output=str(error),
                success=False,
            )
        )

    def get_prompt_messages(self) -> list[str]:
        """取出并清空 prompt action 产生的注入消息。
        Agent 在 pre_send Hook 后调用，将这些消息注入 system prompt。"""
        messages = list(self._prompt_messages)
        self._prompt_messages.clear()
        return messages


    def drain_notifications(self) -> list[HookNotification]:
        """取出并清空 Hook 执行结果通知。
        Agent 在每轮迭代中调用，将通知作为 system reminder 注入对话。"""
        notifications = list(self._notifications)
        self._notifications.clear()
        return notifications
