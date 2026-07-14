"""Agent 核心运行循环。

Agent.run() 是异步生成器，产出事件流供 TUI/Daemon/GUI 消费。
主路径：注入上下文 → 循环(压缩/pre_send/LLM/post_receive/工具执行) → 收敛结束。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from pydantic import ValidationError

from mozilcode.agent.events import (
    AgentEvent,
    AskUserRequest,
    CompactNotification,
    CompactStarted,
    ErrorEvent,
    HookEvent,
    LoopComplete,
    PermissionRequest,
    PermissionResponse,
    RetryEvent,
    StreamText,
    ThinkingText,
    ToolResultEvent,
    ToolUseEvent,
    TurnComplete,
    UsageEvent,
)
from mozilcode.agent.compaction import (
    compact_noop_notification,
    compact_success_notification,
    inject_agent_context,
    reinject_after_compact,
)
from mozilcode.agent.stream import LLMResponse, StreamCollector, ThinkingBlock
from mozilcode.agent.helpers import (
    build_hook_context,
    build_permission_description,
    infer_tool_file_path,
    latest_user_query,
)
from mozilcode.agent.hook_events import (
    drain_hook_events as drain_hook_engine_events,
    run_lifecycle_hook,
)
from mozilcode.agent.llm_preparation import (
    inject_deferred_tool_reminder,
    prepare_api_conversation,
)
from mozilcode.agent.memory import AgentMemoryBridge
from mozilcode.agent.notifications import (
    consume_team_mailbox,
    inject_external_notifications,
)
from mozilcode.agent.noninteractive_tools import execute_noninteractive_tool_call
from mozilcode.agent.output_recovery import (
    OutputRecoveryState,
    handle_output_token_limit,
)
from mozilcode.agent.recovery import record_tool_recovery_snapshot
from mozilcode.agent.response_history import (
    add_final_response,
    add_tool_call_response,
    response_thinking_blocks,
    snapshot_file_history,
)
from mozilcode.agent.tool_execution import (
    StreamingExecutor,
    ToolBatch,
    _AuthResult,
    _ToolExecResult,
    execute_direct_tool_call,
    execute_validated_tool,
    partition_tool_calls,
)
from mozilcode.agent.tool_authorization import authorize_tool_call
from mozilcode.agent.tool_hooks import run_post_tool_hook, run_pre_tool_hook
from mozilcode.agent.tool_results import (
    hook_rejected_result,
    tool_result_block,
    tool_result_event,
)
from mozilcode.agent.usage import (
    UsageTotals,
    accumulate_response_usage,
    usage_callback_payload,
)
from mozilcode.client import LLMClient
from mozilcode.context import (
    CompactCircuitBreaker,
    CompactEvent,
    ContentReplacementState,
    RecoveryState,
    auto_compact,
    compute_compact_threshold,
    create_replacement_state,
    ensure_session_dir,
    load_replacement_records,
    reconstruct_replacement_state,
    should_auto_compact,
)
from mozilcode.conversation import ConversationManager, ToolResultBlock
from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.providers import (
    MEMORY_EVENT_TURN_COMPLETED,
    MemoryHub,
    MarkdownMemoryProvider,
)
from mozilcode.permissions import (
    Decision,
    PermissionChecker,
    PermissionMode,
)
from mozilcode.plan_paths import create_plan_path
from mozilcode.hooks import HookContext, HookEngine
from mozilcode.prompts import build_environment_context, build_plan_mode_reminder, build_system_prompt
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import (
    ToolCallComplete,
    ToolResult,
)

log = logging.getLogger(__name__)

# 每隔 N 轮触发一次记忆提取
MEMORY_EXTRACTION_INTERVAL = 5


class Agent:
    """AI 编码助手核心引擎：循环调用 LLM + 工具，直到收敛或达上限。"""


    def __init__(
        self,
        client: LLMClient,              # LLM 客户端（Anthropic / OpenAI 统一接口）
        registry: ToolRegistry,          # 工具注册表（23 个内置工具 + MCP/Skills 扩展）
        protocol: str,                   # LLM 协议（anthropic / openai / openai-compat）
        work_dir: str = ".",            # 工作目录（文件操作的基础路径）
        max_iterations: int = 50,       # 最大循环次数（防止无限循环）
        permission_checker: PermissionChecker | None = None,  # 权限检查器
        context_window: int = 200_000,  # LLM 上下文窗口大小（tokens）
        instructions_content: str = "",  # MOZILCODE.md 中的项目指令
        memory_manager: MemoryManager | None = None,   # 旧版记忆管理器
        memory_hub: MemoryHub | None = None,            # 新版可插拔记忆中心
        hook_engine: HookEngine | None = None,          # Hook 引擎（生命周期钩子）
    ) -> None:
        self.client = client
        self.registry = registry
        self.protocol = protocol
        self.work_dir = work_dir
        self.max_iterations = max_iterations
        self.permission_checker = permission_checker
        self.permission_mode: PermissionMode = (
            permission_checker.mode if permission_checker else PermissionMode.DEFAULT
        )
        self.context_window = context_window
        self.session_dir = ensure_session_dir(work_dir)           # 会话持久化目录
        self.compact_breaker = CompactCircuitBreaker()            # 上下文压缩熔断器（防频繁压缩）
        self.replacement_state: ContentReplacementState = create_replacement_state()  # Layer 1 替换状态
        # Layer2 压缩后用于恢复近期读文件/skill 快照
        self.recovery_state: RecoveryState = RecoveryState()
        self.total_input_tokens = 0                                # 累计输入 token
        self.total_output_tokens = 0                               # 累计输出 token
        self.instructions_content = instructions_content
        self.memory_manager = memory_manager
        self.memory_hub = memory_hub
        # 如果只传了旧版 memory_manager 而没传 memory_hub，自动包装为 Hub
        if self.memory_hub is None and self.memory_manager is not None:
            self.memory_hub = MemoryHub(
                providers=[MarkdownMemoryProvider(work_dir, manager=self.memory_manager)]
            )
        # 记忆桥接层：Agent 循环 ↔ MemoryHub 之间的适配器
        self.memory_bridge = AgentMemoryBridge(
            memory_hub=self.memory_hub,
            client=self.client,
            protocol=self.protocol,
            project_root=self.work_dir,
        )
        self.hook_engine = hook_engine
        self._loop_count = 0                                       # 已完成的循环数（用于记忆提取间隔控制）
        self.session_id: str = ""
        self.active_skills: dict[str, str] = {}                    # 当前激活的 Skill 提示体
        self._skill_catalog: str = ""                              # 可用 Skill 清单（注入 system prompt）
        self._agent_catalog: str = ""                              # 可用子 Agent 类型清单
        self._agent_catalog_list: list[tuple[str, str]] = []
        self.agent_id: str = uuid.uuid4().hex[:12]                # Agent 唯一 ID
        self.parent_id: str | None = None                          # 父 Agent ID（子 Agent 模式时设置）
        self.trace_id: str | None = None                           # 追踪 ID（用于 trace 树）
        self.coordinator_mode: bool = False                       # 协调者模式（只调度不执行）
        self.team_name: str = ""                                  # 所属 Team 名称
        self._team_manager: Any = None                             # Team 管理器
        self.notification_fn: Callable[[], list[str]] | None = None  # 外部通知回调
        self.file_history: Any = None                             # 文件历史快照管理器

    @property
    def _transcript_path(self) -> str:
        """会话 JSONL 转录文件路径，用于持久化对话历史和回溯。"""
        if self.session_id:
            return str(Path(self.work_dir) / ".mozilcode" / "sessions" / f"{self.session_id}.jsonl")
        return ""

    @property
    def plan_mode(self) -> bool:
        return self.permission_mode == PermissionMode.PLAN

    _plan_path_cache: Path | None = None

    def _get_plan_path(self) -> Path:
        if self._plan_path_cache is not None:
            return self._plan_path_cache
        self._plan_path_cache = create_plan_path(self.work_dir)
        return self._plan_path_cache

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_mode = mode
        if self.permission_checker:
            self.permission_checker.mode = mode

    def activate_skill(self, name: str, prompt_body: str) -> None:
        self.active_skills[name] = prompt_body

    def clear_active_skills(self) -> None:
        self.active_skills.clear()

    def set_skill_catalog(self, catalog: str) -> None:
        self._skill_catalog = catalog


    def set_agent_catalog(self, catalog: str, catalog_list: list[tuple[str, str]] | None = None) -> None:
        self._agent_catalog = catalog
        if catalog_list is not None:
            self._agent_catalog_list = catalog_list

    def _build_hook_context(self, event: str, **kwargs: str | dict) -> HookContext:
        # 把事件名 + 可选字段打成 HookContext（供 condition / 模板变量 $FILE_PATH 等展开）
        return build_hook_context(event, **kwargs)

    def _infer_file_path(self, args: dict) -> str:
        return infer_tool_file_path(args)

    def _drain_hook_events(self) -> list[HookEvent]:
        # HookEngine 执行中写入的通知出队 → 转成 Agent 事件流用的 HookEvent 列表
        return drain_hook_engine_events(self.hook_engine)

    async def _run_lifecycle_hook(
        self,
        event: str,
        **context_kwargs: Any,
    ) -> list[HookEvent]:
        # 生命周期 Hook 薄封装：构造 context → run_hooks → drain 成 HookEvent
        return await run_lifecycle_hook(
            hook_engine=self.hook_engine,
            build_hook_context=self._build_hook_context,
            drain_events=self._drain_hook_events,
            event=event,
            context_kwargs=context_kwargs or None,
        )

    async def _load_memory_context(self, query: str = "") -> str:
        self.memory_bridge.memory_hub = self.memory_hub
        return await self.memory_bridge.load_context(
            query=query,
            session_id=self.session_id,
        )

    @staticmethod
    def _latest_user_query(conversation: ConversationManager) -> str:
        return latest_user_query(conversation)

    async def run(self, conversation: ConversationManager) -> AsyncIterator[AgentEvent]:
        """主循环：注入上下文后反复 LLM↔工具，直到无 tool_call 或达上限。"""
        self._current_conversation = conversation
        # 构建环境上下文（工作目录、激活的 Skill、可用 Agent 类型清单）
        env_context = build_environment_context(
            self.work_dir,
            self.active_skills,
            self._skill_catalog,
            self._agent_catalog,
        )
        # 用最近真实 user 消息做记忆检索 query
        memory_content = await self._load_memory_context(self._latest_user_query(conversation))
        # 将环境上下文、项目指令、记忆内容注入对话开头
        inject_agent_context(
            conversation,
            environment_context=env_context,
            instructions_content=self.instructions_content,
            memory_content=memory_content,
        )

        # session_start：await 列表后再 yield 给前端
        for he in await self._run_lifecycle_hook("session_start"):
            yield he

        iteration = 0
        consecutive_unknown = 0          # 连续未知工具调用计数（超过 3 次终止）
        output_recovery_state = OutputRecoveryState()  # max_tokens 触顶恢复状态

        while True:
            iteration += 1

            # 迭代次数保护：超过最大限制则终止
            if iteration > self.max_iterations:
                yield ErrorEvent(
                    message=f"Agent reached maximum iterations ({self.max_iterations})"
                )
                break

            # ① 触发 turn_start 生命周期 Hook
            for he in await self._run_lifecycle_hook("turn_start"):
                yield he

            # 注入外部通知（Team mailbox / notification_fn），供本轮 LLM 可见
            self._inject_external_notifications(conversation)

            # ② Layer 2: 接近 context window 上限时自动 compact（摘要历史对话）
            current_tokens = conversation.current_tokens()
            compact_threshold = compute_compact_threshold(self.context_window) # 当前对话占用了多少 token 的估算值（整数）
            compact_started = should_auto_compact(current_tokens, self.context_window)
            if compact_started:
                yield CompactStarted(
                    current_tokens=current_tokens,
                    threshold=compact_threshold,
                    context_window=self.context_window,
                )
            compact_result = await auto_compact(
                conversation,
                self.client,
                self.context_window,
                self.session_dir,
                protocol=self.protocol,
                breaker=self.compact_breaker,
                recovery=self.recovery_state,
                tool_schemas=self.registry.get_all_schemas(self.protocol),
                transcript_path=self._transcript_path,
            )
            if isinstance(compact_result, CompactEvent):
                # 压缩成功后重新注入环境上下文和记忆，保证工作集不丢失
                mem = await self._load_memory_context()
                after_tokens = reinject_after_compact(
                    conversation,
                    environment_context=env_context,
                    instructions_content=self.instructions_content,
                    memory_content=mem,
                )
                yield compact_success_notification(compact_result, after_tokens)
                yield UsageEvent(
                    input_tokens=self.total_input_tokens,
                    output_tokens=self.total_output_tokens,
                    context_tokens=after_tokens,
                )
            elif compact_result is None and compact_started:
                # 近期内容不足以生成有效摘要，跳过本轮压缩
                after_tokens = conversation.current_tokens()
                yield CompactNotification(
                    before_tokens=current_tokens,
                    message="上下文暂未压缩（近期内容不足以生成有效摘要）",
                    after_tokens=after_tokens,
                )
            elif isinstance(compact_result, str):
                yield ErrorEvent(message=compact_result)

            # ③ 触发 pre_send 生命周期 Hook（即将发送给 LLM）
            for he in await self._run_lifecycle_hook("pre_send"):
                yield he

            # 收集 Hook 产生的 prompt 注入消息（prompt 类型 action 的输出）
            hook_prompts = (
                self.hook_engine.get_prompt_messages() if self.hook_engine else None
            )
            # 构建 system prompt（包含环境信息、Hook 提示、协调者模式等）
            system = build_system_prompt(
                hook_prompts=hook_prompts,
                coordinator_mode=self.coordinator_mode,
                agent_catalog=self._agent_catalog_list or None,
            )

            # Plan 模式：仅允许改计划文件，并注入计划提醒
            if self.plan_mode:
                plan_path = str(self._get_plan_path())
                if self.permission_checker:
                    self.permission_checker.plan_file_path = plan_path
                plan_exists = self._get_plan_path().exists()
                plan_reminder = build_plan_mode_reminder(
                    plan_path, plan_exists, iteration
                )
                conversation.add_system_reminder(plan_reminder)

            # 兜底残留 hook 通知 → system-reminder（pre_send 通常已 drain 过）
            if self.hook_engine:
                for note in self.hook_engine.drain_notifications():
                    conversation.add_system_reminder(
                        f"Hook [{note.hook_id}] {note.event}: {note.output}"
                    )

            # 提醒 LLM 还有可 ToolSearch 加载的 deferred 工具
            inject_deferred_tool_reminder(
                conversation,
                self.registry.get_deferred_tool_names(),
            )

            # 本轮 tools schema（跳过未发现 deferred / disabled）
            tools = self.registry.get_all_schemas(self.protocol)

            # ④ Layer1：按 tool-result 预算生成 api_conv（不改原始 conversation）
            api_conv, _ = prepare_api_conversation(
                conversation,
                self.session_dir,
                self.replacement_state,
            )

            # ⑤ 调用 LLM（流式），通过 StreamCollector 收集事件并 yield 给前端
            collector = StreamCollector()
            llm_stream = self.client.stream(api_conv, system=system, tools=tools)
            async for event in collector.consume(llm_stream):
                yield event

            response = collector.response

            # ⑥ 触发 post_receive 生命周期 Hook（LLM 响应已收到）
            for he in await self._run_lifecycle_hook(
                "post_receive",
                message=response.text,
            ):
                yield he

            # ⑦ 记录 token 用量并产出 UsageEvent
            usage_update = accumulate_response_usage(
                UsageTotals(self.total_input_tokens, self.total_output_tokens),
                response,
            )
            self.total_input_tokens = usage_update.totals.input_tokens
            self.total_output_tokens = usage_update.totals.output_tokens
            yield usage_update.event

            conv_thinking = response_thinking_blocks(response)

            # ⑧ max_tokens 触顶：提输出上限 + 续写提示，必要时 continue 再调 LLM
            output_recovery_decision = handle_output_token_limit(
                response=response,
                conversation=conversation,
                client=self.client,
                thinking_blocks=conv_thinking,
                state=output_recovery_state,
            )
            output_recovery_state = output_recovery_decision.state
            if output_recovery_decision.retry_event is not None:
                yield output_recovery_decision.retry_event
                continue

            # ⑨ 如果 LLM 没有返回工具调用 → 任务完成
            if not response.tool_calls:
                add_final_response(
                    conversation,
                    response,
                    thinking_blocks=conv_thinking,
                )
                # 后台异步观察对话（轻量级，不阻塞）
                if self.memory_hub:
                    asyncio.ensure_future(
                        self._observe_memories(conversation, MEMORY_EVENT_TURN_COMPLETED)
                    )
                self._loop_count += 1
                # 每 5 轮触发一次记忆提取（重量级，用 LLM 从对话中提取值得记忆的信息）
                if (
                    self._loop_count % MEMORY_EXTRACTION_INTERVAL == 0
                    and self.memory_hub
                ):
                    asyncio.ensure_future(self._extract_memories(conversation))
                # 触发 turn_end 和 session_end 生命周期 Hook
                for he in await self._run_lifecycle_hook("turn_end"):
                    yield he
                for he in await self._run_lifecycle_hook("session_end"):
                    yield he
                # 保存文件历史快照（用于回溯）
                snapshot_file_history(
                    self.file_history,
                    conversation,
                    response.text,
                )
                # 产出 LoopComplete 事件，循环结束
                yield LoopComplete(total_turns=iteration)
                break

            # ⑩ LLM 返回了工具调用 → 记录到对话历史
            add_tool_call_response(
                conversation,
                response,
                thinking_blocks=conv_thinking,
            )
            
            tool_results: list[ToolResultBlock] = []
            # 按并发安全对工具调用分区（只读安全工具可批量并行，写/执行类串行）
            batches = partition_tool_calls(response.tool_calls, self.registry)

            for batch in batches:
                if batch.concurrent and len(batch.calls) > 1:
                    # 并发路径：先逐个 pre_tool_use + 权限预检，通过后再并行执行
                    approved: list[ToolCallComplete] = []
                    pre_failed: dict[str, ToolResult] = {}
                    for tc in batch.calls:
                        hook_result = await run_pre_tool_hook(
                            hook_engine=self.hook_engine,
                            build_hook_context=self._build_hook_context,
                            infer_file_path=self._infer_file_path,
                            drain_hook_events=self._drain_hook_events,
                            tool_call=tc,
                        )
                        for he in hook_result.events:
                            yield he
                        if hook_result.rejection is not None:
                            pre_failed[tc.tool_id] = hook_rejected_result(
                                hook_result.rejection.reason
                            )
                            continue

                        # 权限预检（不执行工具）；ask 时先 yield 给前端
                        auth: _AuthResult | None = None
                        async for item in self._authorize_tool(tc):
                            if isinstance(item, (PermissionRequest, AskUserRequest)):
                                yield item
                            else:
                                auth = item
                        if auth is None or not auth.approved:
                            pre_failed[tc.tool_id] = (
                                auth.error
                                if auth is not None and auth.error is not None
                                else ToolResult(output="Permission denied", is_error=True)
                            )
                            continue
                        approved.append(tc)

                    # 并行执行通过预检的调用，再跑 post_tool_use
                    exec_results: dict[str, _ToolExecResult] = {}
                    if approved:
                        for br in await self._execute_batch_parallel(approved):
                            exec_results[br.tool_id] = br
                        for tc in approved:
                            for he in await run_post_tool_hook(
                                hook_engine=self.hook_engine,
                                build_hook_context=self._build_hook_context,
                                infer_file_path=self._infer_file_path,
                                drain_hook_events=self._drain_hook_events,
                                tool_call=tc,
                            ):
                                yield he

                    # 按原始调用顺序汇总结果
                    consecutive_unknown = 0
                    for tc in batch.calls:
                        if tc.tool_id in pre_failed:
                            result = pre_failed[tc.tool_id]
                            elapsed = 0.0
                        else:
                            br = exec_results[tc.tool_id]
                            result = br.result
                            elapsed = br.elapsed
                        tool_results.append(
                            tool_result_block(tc, result, self.session_dir)
                        )
                        yield tool_result_event(tc, result, elapsed)
                else:
                    # 串行路径
                    for tc in batch.calls:
                        result: ToolResult | None = None
                        elapsed = 0.0
                        is_unknown = False

                        # ⑩a pre_tool_use Hook（可以 reject 拦截）
                        hook_result = await run_pre_tool_hook(
                            hook_engine=self.hook_engine,
                            build_hook_context=self._build_hook_context,
                            infer_file_path=self._infer_file_path,
                            drain_hook_events=self._drain_hook_events,
                            tool_call=tc,
                        )
                        for he in hook_result.events:
                            yield he
                        if hook_result.rejection is not None:
                            result = hook_rejected_result(hook_result.rejection.reason)
                            tool_results.append(
                                tool_result_block(tc, result, self.session_dir)
                            )
                            yield tool_result_event(tc, result, 0.0)
                            continue

                        # ⑩b 执行工具（含权限检查，可能 yield PermissionRequest）
                        async for item in self._execute_tool(tc):
                            if isinstance(item, (PermissionRequest, AskUserRequest)):
                                yield item
                            else:
                                result, elapsed, is_unknown = item

                        if result is None:
                            result = ToolResult(output="Error: no result from tool", is_error=True)

                        if is_unknown:
                            consecutive_unknown += 1
                        else:
                            consecutive_unknown = 0

                        # ⑩c post_tool_use Hook
                        for he in await run_post_tool_hook(
                            hook_engine=self.hook_engine,
                            build_hook_context=self._build_hook_context,
                            infer_file_path=self._infer_file_path,
                            drain_hook_events=self._drain_hook_events,
                            tool_call=tc,
                        ):
                            yield he

                        tool_results.append(
                            tool_result_block(tc, result, self.session_dir)
                        )
                        yield tool_result_event(tc, result, elapsed)

            if consecutive_unknown >= 3:
                yield ErrorEvent(
                    message="Agent terminated: too many consecutive unknown tool calls"
                )
                break

            exit_plan_called = any(
                tc.tool_name == "ExitPlanMode" for tc in response.tool_calls
            )
            conversation.add_tool_results_message(tool_results)
            if exit_plan_called:
                yield TurnComplete(turn=iteration)
                yield LoopComplete(total_turns=iteration)
                break

            for he in await self._run_lifecycle_hook("turn_end"):
                yield he
            yield TurnComplete(turn=iteration)


    def _consume_mailbox(self, conversation: ConversationManager) -> None:
        consume_team_mailbox(
            conversation,
            team_name=self.team_name,
            team_manager=self._team_manager,
            agent_id=self.agent_id,
        )

    def _inject_external_notifications(self, conversation: ConversationManager) -> None:
        # mailbox / notification_fn → 注入对话
        inject_external_notifications(
            conversation,
            team_name=self.team_name,
            team_manager=self._team_manager,
            agent_id=self.agent_id,
            notification_fn=self.notification_fn,
        )

    def _build_permission_description(self, tc: ToolCallComplete) -> str:
        return build_permission_description(tc)

    async def _execute_single_tool_direct(
        self, tc: ToolCallComplete
    ) -> _ToolExecResult:
        # 仅执行工具（无权限/hooks）；调用方须先完成授权预检
        exec_result = await execute_direct_tool_call(self.registry, tc)
        self._snapshot_for_recovery(tc, exec_result.result)
        return exec_result

    async def _execute_batch_parallel(
        self, calls: list[ToolCallComplete]
    ) -> list[_ToolExecResult]:
        """并行执行多个安全工具调用（asyncio.gather）。"""
        tasks = [self._execute_single_tool_direct(tc) for tc in calls]
        return list(await asyncio.gather(*tasks))

    async def _authorize_tool(
        self, tc: ToolCallComplete
    ) -> AsyncIterator["PermissionRequest | AskUserRequest | _AuthResult"]:
        """并发前授权预检：deny/ask/allow，不执行工具。"""
        async for item in authorize_tool_call(
            registry=self.registry,
            permission_checker=self.permission_checker,
            tool_call=tc,
            permission_description=self._build_permission_description(tc),
        ):
            yield item

    async def _execute_tool(
        self, tc: ToolCallComplete
    ) -> AsyncIterator[tuple[ToolResult, float, bool]]:
        start = time.monotonic()
        auth: _AuthResult | None = None
        async for item in self._authorize_tool(tc):
            if isinstance(item, (PermissionRequest, AskUserRequest)):
                yield item
            else:
                auth = item
        if auth is None or not auth.approved:
            result = (
                auth.error
                if auth is not None and auth.error is not None
                else ToolResult(output="Permission denied", is_error=True)
            )
            elapsed = time.monotonic() - start
            yield result, elapsed, auth.is_unknown if auth is not None else False
            return

        tool = self.registry.get(tc.tool_name)
        if tool is None:
            result = ToolResult(
                output=f"Error: unknown tool '{tc.tool_name}'", is_error=True
            )
            elapsed = time.monotonic() - start
            yield result, elapsed, True
            return

        try:
            params = tool.params_model.model_validate(tc.arguments)

            # AskUserQuestion：经事件流向调用方提问，不再走旧 side-channel
            if tc.tool_name == "AskUserQuestion":
                from mozilcode.tools.ask_user import AskUserParams

                assert isinstance(params, AskUserParams)
                questions_data = [q.model_dump() for q in params.questions]

                loop = asyncio.get_running_loop()
                future: asyncio.Future[dict[str, str]] = loop.create_future()

                yield AskUserRequest(
                    questions=questions_data,
                    future=future,
                )

                try:
                    answers = await asyncio.wait_for(future, timeout=300)
                except asyncio.TimeoutError:
                    result = ToolResult(
                        output="User did not respond within 5 minutes",
                        is_error=True,
                    )
                    elapsed = time.monotonic() - start
                    yield result, elapsed, False
                    return

                lines = []
                for q in params.questions:
                    answer = answers.get(q.name, "(no answer)")
                    lines.append(f"{q.name}: {answer}")

                result = ToolResult(output="\n".join(lines))
            else:
                result = await tool.execute(params)
        except ValidationError as e:
            result = ToolResult(
                output=f"Parameter validation error: {e}", is_error=True
            )
        except Exception as e:
            result = ToolResult(
                output=f"Tool execution error: {e}", is_error=True
            )

        self._snapshot_for_recovery(tc, result)

        elapsed = time.monotonic() - start
        yield result, elapsed, False

    def _snapshot_for_recovery(
        self, tc: ToolCallComplete, result: ToolResult
    ) -> None:
        record_tool_recovery_snapshot(
            recovery_state=self.recovery_state,
            tool_call=tc,
            result=result,
            work_dir=self.work_dir,
        )

    async def _extract_memories(
        self, conversation: ConversationManager
    ) -> None:
        """后台提取记忆：用 LLM 从对话中提取值得长期记忆的信息，写入 memories.md。"""
        self.memory_bridge.memory_hub = self.memory_hub
        await self.memory_bridge.extract_memories(
            conversation,
            session_id=self.session_id,
            agent_id=self.agent_id,
            query=self._latest_user_query(conversation),
        )

    async def _observe_memories(
        self,
        conversation: ConversationManager,
        event_type: str,
    ) -> None:
        """后台观察对话：通知记忆系统发生了一轮对话（轻量级，不提取）。"""
        self.memory_bridge.memory_hub = self.memory_hub
        await self.memory_bridge.observe(
            conversation,
            event_type,
            session_id=self.session_id,
            agent_id=self.agent_id,
            query=self._latest_user_query(conversation),
        )

    async def manual_compact(
        self, conversation: ConversationManager
    ) -> CompactNotification | ErrorEvent:
        # 手动压缩：直接 auto_compact 原始对话，无需先做 Layer1 budget
        result = await auto_compact(
            conversation,
            self.client,
            self.context_window,
            self.session_dir,
            protocol=self.protocol,
            manual=True,
            breaker=self.compact_breaker,
            recovery=self.recovery_state,
            tool_schemas=self.registry.get_all_schemas(self.protocol),
            transcript_path=self._transcript_path,
        )
        if isinstance(result, CompactEvent):
            env_context = build_environment_context(
                self.work_dir,
                self.active_skills,
                self._skill_catalog,
                self._agent_catalog,
            )
            memory_content = await self._load_memory_context()
            after_tokens = reinject_after_compact(
                conversation,
                environment_context=env_context,
                instructions_content=self.instructions_content,
                memory_content=memory_content,
            )
            return compact_success_notification(result, after_tokens)
        current_tokens = conversation.current_tokens()
        return compact_noop_notification(
            before_tokens=current_tokens,
            message=result,
        )

    async def run_to_completion(
        self, task: str, conversation: ConversationManager | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        """子 Agent 非交互执行到完成；不 yield 事件，返回最终文本。"""
        env_context = build_environment_context(
            self.work_dir, self.active_skills, self._skill_catalog, self._agent_catalog
        )
        if conversation is None:
            conversation = ConversationManager()

            memory_content = await self._load_memory_context(task)
            inject_agent_context(
                conversation,
                environment_context=env_context,
                instructions_content=self.instructions_content,
                memory_content=memory_content,
            )

        if task:
            conversation.add_user_message(task)

        hook_prompts = (
            self.hook_engine.get_prompt_messages() if self.hook_engine else None
        )
        system = build_system_prompt(
            hook_prompts=hook_prompts,
            coordinator_mode=self.coordinator_mode,
        )

        tools = self.registry.get_all_schemas(self.protocol)

        log.info(
            "[run_to_completion] agent=%s tools=%d names=%s coordinator=%s",
            self.agent_id,
            len(tools),
            [t["name"] for t in tools][:10],
            self.coordinator_mode,
        )

        last_text = ""

        for iteration in range(1, self.max_iterations + 1):
            if self.hook_engine:
                ctx = self._build_hook_context("turn_start")
                await self.hook_engine.run_hooks("turn_start", ctx)

            self._inject_external_notifications(conversation)

            compact_result = await auto_compact(
                conversation,
                self.client,
                self.context_window,
                self.session_dir,
                protocol=self.protocol,
                breaker=self.compact_breaker,
                recovery=self.recovery_state,
                tool_schemas=self.registry.get_all_schemas(self.protocol),
                transcript_path=self._transcript_path,
            )
            if isinstance(compact_result, CompactEvent):
                memory_content = await self._load_memory_context(task)
                reinject_after_compact(
                    conversation,
                    environment_context=env_context,
                    instructions_content=self.instructions_content,
                    memory_content=memory_content,
                )

            inject_deferred_tool_reminder(
                conversation,
                self.registry.get_deferred_tool_names(),
            )

            api_conv, _ = prepare_api_conversation(
                conversation,
                self.session_dir,
                self.replacement_state,
            )

            collector = StreamCollector()
            llm_stream = self.client.stream(api_conv, system=system, tools=tools)
            async for _event in collector.consume(llm_stream):
                pass

            response = collector.response
            usage_update = accumulate_response_usage(
                UsageTotals(self.total_input_tokens, self.total_output_tokens),
                response,
            )
            self.total_input_tokens = usage_update.totals.input_tokens
            self.total_output_tokens = usage_update.totals.output_tokens

            if event_callback:
                event_callback(usage_callback_payload(usage_update.totals))

            if response.text:
                last_text = response.text
                if event_callback:
                    event_callback({
                        "type": "stream_text",
                        "text": response.text,
                    })

            log.info(
                "[run_to_completion] agent=%s iter=%d tool_calls=%d text_len=%d stop=%s",
                self.agent_id, iteration, len(response.tool_calls),
                len(response.text), response.stop_reason,
            )

            if not response.tool_calls:
                add_final_response(
                    conversation,
                    response,
                    thinking_blocks=[],
                )
                await self._observe_memories(conversation, MEMORY_EVENT_TURN_COMPLETED)
                snapshot_file_history(
                    self.file_history,
                    conversation,
                    response.text,
                )
                break

            add_tool_call_response(
                conversation,
                response,
                thinking_blocks=[],
            )

            tool_results: list[ToolResultBlock] = []
            for tc in response.tool_calls:
                if event_callback:
                    event_callback({
                        "type": "tool_use",
                        "toolName": tc.tool_name,
                        "args": tc.arguments,
                    })
                result = await self._execute_tool_noninteractive(tc)
                tool_results.append(
                    tool_result_block(tc, result, self.session_dir)
                )

            conversation.add_tool_results_message(tool_results)

            if self.hook_engine:
                ctx = self._build_hook_context("turn_end")
                await self.hook_engine.run_hooks("turn_end", ctx)

        return last_text

    async def _execute_tool_noninteractive(
        self, tc: ToolCallComplete
    ) -> ToolResult:
        return await execute_noninteractive_tool_call(
            registry=self.registry,
            permission_checker=self.permission_checker,
            permission_mode=self.permission_mode,
            hook_engine=self.hook_engine,
            build_hook_context=self._build_hook_context,
            infer_file_path=self._infer_file_path,
            tool_call=tc,
        )
