from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from pydantic import ValidationError

from mozilcode.client import LLMClient
from mozilcode.context import (
    CompactBoundary,
    CompactCircuitBreaker,
    CompactEvent,
    ContentReplacementRecord,
    ContentReplacementState,
    RecoveryState,
    append_replacement_records,
    apply_tool_result_budget,
    auto_compact,
    compute_compact_threshold,
    create_replacement_state,
    ensure_session_dir,
    load_replacement_records,
    reconstruct_replacement_state,
    should_auto_compact,
)
from mozilcode.conversation import ConversationManager, ToolResultBlock, ToolUseBlock
from mozilcode.conversation import ThinkingBlock as ConvThinkingBlock
from mozilcode.memory.auto_memory import MemoryManager
from mozilcode.memory.providers import (
    MEMORY_EVENT_TURN_COMMITTED,
    MEMORY_EVENT_TURN_COMPLETED,
    MemoryEvent,
    MemoryHub,
    MemoryScope,
    MarkdownMemoryProvider,
)
from mozilcode.permissions import (
    Decision,
    PermissionChecker,
    PermissionMode,
)
from mozilcode.plan_paths import create_plan_path
from mozilcode.hooks import HookContext, HookEngine, ToolRejectedError
from mozilcode.hooks.engine import HookNotification
from mozilcode.prompts import build_environment_context, build_plan_mode_reminder, build_system_prompt
from mozilcode.tools import ToolRegistry
from mozilcode.tools.base import (
    MAX_OUTPUT_CHARS,
    StreamEnd,
    StreamEvent,
    TextDelta,
    ThinkingComplete,
    ThinkingDelta,
    ToolCallComplete,
    ToolCallDelta,
    ToolCallStart,
    ToolResult,
)
from mozilcode.tools.paths import resolve_tool_path

log = logging.getLogger(__name__)

MEMORY_EXTRACTION_INTERVAL = 5
MAX_TOKENS_CEILING = 64000
MAX_OUTPUT_TOKENS_RECOVERIES = 3


# ---------------------------------------------------------------------------
# AgentEvent 事件类型
# ---------------------------------------------------------------------------

@dataclass
class StreamText:
    text: str


@dataclass
class ThinkingText:
    text: str


@dataclass
class RetryEvent:
    reason: str
    wait: float = 0.0


@dataclass
class ToolUseEvent:
    tool_name: str
    tool_id: str
    arguments: dict[str, Any]


@dataclass
class ToolResultEvent:
    tool_id: str
    tool_name: str
    output: str
    is_error: bool
    elapsed: float


@dataclass
class TurnComplete:
    turn: int


@dataclass
class LoopComplete:
    total_turns: int


@dataclass
class UsageEvent:
    input_tokens: int
    output_tokens: int
    context_tokens: int = 0


@dataclass
class ErrorEvent:
    message: str


@dataclass
class CompactNotification:
    before_tokens: int
    message: str
    after_tokens: int = 0
    # 结构化 boundary（摘要 + 原文保留尾部），daemon/session 层用它持久化 compact_boundary 记录。
    # 失败路径下为 None。
    boundary: "CompactBoundary | None" = None


@dataclass
class CompactStarted:
    current_tokens: int
    threshold: int
    context_window: int
    message: str = "正在自动压缩上下文"


@dataclass
class HookEvent:
    hook_id: str
    event: str
    output: str
    success: bool


class PermissionResponse(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"


@dataclass
class PermissionRequest:
    tool_name: str
    description: str
    future: asyncio.Future[PermissionResponse]


@dataclass
class AskUserRequest:
    """Yielded when AskUserQuestion tool needs user input.

    The caller (daemon / embedding runtime) must resolve ``future`` with a dict of
    {question_name: answer} via ``future.set_result(answers)``.
    """
    questions: list[dict[str, Any]]
    future: asyncio.Future[dict[str, str]]


AgentEvent = (
    StreamText
    | ThinkingText
    | RetryEvent
    | ToolUseEvent
    | ToolResultEvent
    | TurnComplete
    | LoopComplete
    | UsageEvent
    | ErrorEvent
    | PermissionRequest
    | AskUserRequest
    | CompactNotification
    | CompactStarted
    | HookEvent
)


# ---------------------------------------------------------------------------
# LLM 响应收集器
# ---------------------------------------------------------------------------

@dataclass
class ThinkingBlock:
    thinking: str
    signature: str


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCallComplete] = field(default_factory=list)
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0


class StreamCollector:
    def __init__(self) -> None:
        self.response = LLMResponse()

    async def consume(
        self, stream: AsyncIterator[StreamEvent]
    ) -> AsyncIterator[AgentEvent]:
        async for event in stream:
            if isinstance(event, TextDelta):
                self.response.text += event.text
                yield StreamText(text=event.text)
            elif isinstance(event, ThinkingDelta):
                yield ThinkingText(text=event.text)
            elif isinstance(event, ThinkingComplete):
                self.response.thinking_blocks.append(
                    ThinkingBlock(thinking=event.thinking, signature=event.signature)
                )
            elif isinstance(event, ToolCallStart):
                pass
            elif isinstance(event, ToolCallDelta):
                pass
            elif isinstance(event, ToolCallComplete):
                self.response.tool_calls.append(event)
                yield ToolUseEvent(
                    tool_name=event.tool_name,
                    tool_id=event.tool_id,
                    arguments=event.arguments,
                )
            elif isinstance(event, StreamEnd):
                self.response.stop_reason = event.stop_reason
                self.response.input_tokens = event.input_tokens
                self.response.output_tokens = event.output_tokens
                self.response.cache_read = event.cache_read
                self.response.cache_creation = event.cache_creation


# ---------------------------------------------------------------------------
# tool 批量执行
# ---------------------------------------------------------------------------

@dataclass
class ToolBatch:
    concurrent: bool
    calls: list[ToolCallComplete]


def partition_tool_calls(
    tool_calls: list[ToolCallComplete],
    registry: ToolRegistry,
) -> list[ToolBatch]:
    batches: list[ToolBatch] = []
    for tc in tool_calls:
        tool = registry.get(tc.tool_name)
        safe = tool is not None and tool.is_concurrency_safe and registry.is_enabled(tc.tool_name)

        if safe and batches and batches[-1].concurrent:
            batches[-1].calls.append(tc)
        else:
            batches.append(ToolBatch(concurrent=safe, calls=[tc]))
    return batches


# ---------------------------------------------------------------------------
# streaming 执行器 — 在 LLM streaming 期间启动 tool 执行
# ---------------------------------------------------------------------------

@dataclass
class _ToolExecResult:
    tool_id: str
    tool_name: str
    result: ToolResult
    elapsed: float
    is_unknown: bool


@dataclass
class _AuthResult:
    """Tool authorization result. If approved is False, error holds the result."""
    approved: bool
    error: ToolResult | None = None
    is_unknown: bool = False


class StreamingExecutor:
    def __init__(self) -> None:
        self._tasks: list[tuple[int, asyncio.Task[_ToolExecResult]]] = []
        self._order = 0

    def submit(
        self,
        coro: Any,
    ) -> None:
        task = asyncio.create_task(coro)
        self._tasks.append((self._order, task))
        self._order += 1

    async def collect_results(self) -> list[_ToolExecResult]:
        if not self._tasks:
            return []
        tasks = [t for _, t in sorted(self._tasks, key=lambda x: x[0])]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[_ToolExecResult] = []
        for r in results:
            if isinstance(r, Exception):
                out.append(_ToolExecResult(
                    tool_id="",
                    tool_name="",
                    result=ToolResult(output=f"Tool execution error: {r}", is_error=True),
                    elapsed=0.0,
                    is_unknown=False,
                ))
            else:
                out.append(r)
        return out


# ---------------------------------------------------------------------------
# Agent 主循环
# ---------------------------------------------------------------------------

class Agent:
    def __init__(
        self,
        client: LLMClient,
        registry: ToolRegistry,
        protocol: str,
        work_dir: str = ".",
        max_iterations: int = 50,
        permission_checker: PermissionChecker | None = None,
        context_window: int = 200_000,
        instructions_content: str = "",
        memory_manager: MemoryManager | None = None,
        memory_hub: MemoryHub | None = None,
        hook_engine: HookEngine | None = None,
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
        self.session_dir = ensure_session_dir(work_dir)
        self.compact_breaker = CompactCircuitBreaker()
        self.replacement_state: ContentReplacementState = create_replacement_state()
        # 保存重建工作上下文所需的快照，在 Layer 2 压缩对话后使用：
        # 最近的文件读取和 skill 调用。每次 ReadFile / skill 调用时记录，
        # auto_compact 触发阈值时消费。
        self.recovery_state: RecoveryState = RecoveryState()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.instructions_content = instructions_content
        self.memory_manager = memory_manager
        self.memory_hub = memory_hub
        if self.memory_hub is None and self.memory_manager is not None:
            self.memory_hub = MemoryHub(
                providers=[MarkdownMemoryProvider(work_dir, manager=self.memory_manager)]
            )
        self.hook_engine = hook_engine
        self._loop_count = 0
        self._extracting = False
        self.session_id: str = ""
        self.active_skills: dict[str, str] = {}
        self._skill_catalog: str = ""
        self._agent_catalog: str = ""
        self._agent_catalog_list: list[tuple[str, str]] = []
        self.agent_id: str = uuid.uuid4().hex[:12]
        self.parent_id: str | None = None
        self.trace_id: str | None = None
        self.coordinator_mode: bool = False
        self.team_name: str = ""
        self._team_manager: Any = None
        self.notification_fn: Callable[[], list[str]] | None = None
        self.file_history: Any = None

    @property
    def _transcript_path(self) -> str:
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
        return HookContext(
            event_name=event,
            tool_name=str(kwargs.get("tool_name", "")),
            tool_args=kwargs.get("tool_args", {}),
            file_path=str(kwargs.get("file_path", "")),
            message=str(kwargs.get("message", "")),
            error=str(kwargs.get("error", "")),
        )

    def _infer_file_path(self, args: dict) -> str:
        return str(args.get("file_path", args.get("path", "")))

    def _drain_hook_events(self) -> list[HookEvent]:
        if not self.hook_engine:
            return []
        return [
            HookEvent(
                hook_id=n.hook_id,
                event=n.event,
                output=n.output,
                success=n.success,
            )
            for n in self.hook_engine.drain_notifications()
        ]

    async def _load_memory_context(self, query: str = "") -> str:
        if not self.memory_hub:
            return ""
        scope = MemoryScope(
            query=query,
            session_id=self.session_id,
            project_root=self.work_dir,
            source="agent",
        )
        return await self.memory_hub.load_context(query, scope)

    @staticmethod
    def _latest_user_query(conversation: ConversationManager) -> str:
        for message in reversed(conversation.history):
            if message.role != "user" or message.tool_results:
                continue
            content = message.content.strip()
            if not content:
                continue
            if content.startswith("<system-reminder>"):
                continue
            if content.startswith("Current working directory:"):
                continue
            return content
        return ""

    async def run(self, conversation: ConversationManager) -> AsyncIterator[AgentEvent]:
        self._current_conversation = conversation
        env_context = build_environment_context(
            self.work_dir, self.active_skills, self._skill_catalog, self._agent_catalog
        )
        conversation.inject_environment(env_context)

        memory_content = await self._load_memory_context(self._latest_user_query(conversation))
        conversation.inject_long_term_memory(self.instructions_content, memory_content)

        if self.hook_engine:
            ctx = self._build_hook_context("session_start")
            await self.hook_engine.run_hooks("session_start", ctx)
            for he in self._drain_hook_events():
                yield he

        iteration = 0
        consecutive_unknown = 0
        max_tokens_escalated = False
        output_recoveries = 0

        while True:
            iteration += 1

            if iteration > self.max_iterations:
                yield ErrorEvent(
                    message=f"Agent reached maximum iterations ({self.max_iterations})"
                )
                break

            if self.hook_engine:
                ctx = self._build_hook_context("turn_start")
                await self.hook_engine.run_hooks("turn_start", ctx)
                for he in self._drain_hook_events():
                    yield he

            self._consume_mailbox(conversation)
            if self.notification_fn:
                for note in self.notification_fn():
                    conversation.add_system_reminder(note)

            # Layer 2: 接近 context window 上限时自动 compact（操作原始对话）
            current_tokens = conversation.current_tokens()
            compact_threshold = compute_compact_threshold(self.context_window)
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
                conversation.inject_environment(env_context)
                mem = await self._load_memory_context()
                conversation.inject_long_term_memory(
                    self.instructions_content, mem
                )
                after_tokens = conversation.current_tokens()
                yield CompactNotification(
                    before_tokens=compact_result.before_tokens,
                    message=(
                        f"上下文已压缩（{compact_result.before_tokens:,} → "
                        f"{after_tokens:,} tokens）"
                    ),
                    after_tokens=after_tokens,
                    boundary=compact_result.boundary,
                )
                yield UsageEvent(
                    input_tokens=self.total_input_tokens,
                    output_tokens=self.total_output_tokens,
                    context_tokens=after_tokens,
                )
            elif compact_result is None and compact_started:
                after_tokens = conversation.current_tokens()
                yield CompactNotification(
                    before_tokens=current_tokens,
                    message="上下文暂未压缩（近期内容不足以生成有效摘要）",
                    after_tokens=after_tokens,
                )
            elif isinstance(compact_result, str):
                yield ErrorEvent(message=compact_result)

            if self.hook_engine:
                ctx = self._build_hook_context("pre_send")
                await self.hook_engine.run_hooks("pre_send", ctx)
                for he in self._drain_hook_events():
                    yield he

            hook_prompts = (
                self.hook_engine.get_prompt_messages() if self.hook_engine else None
            )
            system = build_system_prompt(
                hook_prompts=hook_prompts,
                coordinator_mode=self.coordinator_mode,
                agent_catalog=self._agent_catalog_list or None,
            )

            if self.plan_mode:
                plan_path = str(self._get_plan_path())
                if self.permission_checker:
                    self.permission_checker.plan_file_path = plan_path
                plan_exists = self._get_plan_path().exists()
                plan_reminder = build_plan_mode_reminder(
                    plan_path, plan_exists, iteration
                )
                conversation.add_system_reminder(plan_reminder)

            if self.hook_engine:
                for note in self.hook_engine.drain_notifications():
                    conversation.add_system_reminder(
                        f"Hook [{note.hook_id}] {note.event}: {note.output}"
                    )

            deferred_names = self.registry.get_deferred_tool_names()
            if deferred_names:
                conversation.add_system_reminder(
                    "The following deferred tools are available via ToolSearch. "
                    "Their schemas are NOT loaded - use ToolSearch with "
                    'query "select:<name>[,<name>...]" to load tool schemas before calling them:\n'
                    + "\n".join(deferred_names)
                )

            tools = self.registry.get_all_schemas(self.protocol)

            # Layer 1: 在 LLM 调用前应用 tool-result budget，确保 api_conv 反映
            # 本轮迭代中所有已发生的写入（system reminders、hook 通知等）。
            # 原始 conversation 不会被修改；替换决策保存在 self.replacement_state 中。
            api_conv, _new_records = apply_tool_result_budget(
                conversation, self.session_dir, self.replacement_state
            )
            if _new_records:
                append_replacement_records(self.session_dir, _new_records)

            collector = StreamCollector()
            llm_stream = self.client.stream(api_conv, system=system, tools=tools)
            async for event in collector.consume(llm_stream):
                yield event

            response = collector.response

            if self.hook_engine:
                ctx = self._build_hook_context("post_receive", message=response.text)
                await self.hook_engine.run_hooks("post_receive", ctx)
                for he in self._drain_hook_events():
                    yield he

            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens
            context_tokens = (
                response.input_tokens
                + response.output_tokens
                + response.cache_read
                + response.cache_creation
            )
            yield UsageEvent(
                input_tokens=self.total_input_tokens,
                output_tokens=self.total_output_tokens,
                context_tokens=context_tokens,
            )

            conv_thinking = [
                ConvThinkingBlock(thinking=tb.thinking, signature=tb.signature)
                for tb in response.thinking_blocks
            ]

            if response.stop_reason == "max_tokens":
                if not max_tokens_escalated:
                    self.client.set_max_output_tokens(MAX_TOKENS_CEILING)
                    max_tokens_escalated = True
                    if response.text:
                        conversation.add_assistant_message(
                            response.text, thinking_blocks=conv_thinking
                        )
                        conversation.add_user_message(
                            "Output token limit hit. Resume directly from where you stopped. "
                            "Do not apologize or repeat previous content. Pick up mid-thought if needed."
                        )
                    yield RetryEvent(reason="max_tokens escalation")
                    continue
                elif output_recoveries < MAX_OUTPUT_TOKENS_RECOVERIES:
                    output_recoveries += 1
                    conversation.add_assistant_message(
                        response.text, thinking_blocks=conv_thinking
                    )
                    conversation.add_user_message(
                        "Output token limit hit. Resume directly from where you stopped. "
                        "Break remaining work into smaller pieces."
                    )
                    yield RetryEvent(
                        reason=f"max_tokens recovery {output_recoveries}/{MAX_OUTPUT_TOKENS_RECOVERIES}"
                    )
                    continue
            else:
                output_recoveries = 0

            if not response.tool_calls:
                conversation.add_assistant_message(
                    response.text, thinking_blocks=conv_thinking
                )
                if self.memory_hub:
                    asyncio.ensure_future(
                        self._observe_memories(conversation, MEMORY_EVENT_TURN_COMPLETED)
                    )
                self._loop_count += 1
                if (
                    self._loop_count % MEMORY_EXTRACTION_INTERVAL == 0
                    and self.memory_hub
                ):
                    asyncio.ensure_future(self._extract_memories(conversation))
                if self.hook_engine:
                    ctx = self._build_hook_context("turn_end")
                    await self.hook_engine.run_hooks("turn_end", ctx)
                    ctx = self._build_hook_context("session_end")
                    await self.hook_engine.run_hooks("session_end", ctx)
                    for he in self._drain_hook_events():
                        yield he
                if self.file_history is not None:
                    summary = response.text[:60] + "..." if len(response.text) > 60 else response.text
                    self.file_history.make_snapshot(len(conversation.history), summary)
                yield LoopComplete(total_turns=iteration)
                break

            tool_uses = [
                ToolUseBlock(
                    tool_use_id=tc.tool_id,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                )
                for tc in response.tool_calls
            ]
            conversation.add_assistant_message(
                response.text, tool_uses, thinking_blocks=conv_thinking
            )
            # 在 assistant 回复加入历史后锚定实际用量：基线（input + cache + output）
            # 覆盖到当前位置，因此下一轮迭代顶部的 auto-compact 检查只需对
            # 接下来追加的 tool results 做字符估算。
            conversation.record_usage_anchor(
                response.input_tokens,
                response.output_tokens,
                response.cache_read,
                response.cache_creation,
            )

            tool_results: list[ToolResultBlock] = []
            batches = partition_tool_calls(response.tool_calls, self.registry)

            for batch in batches:
                if batch.concurrent and len(batch.calls) > 1:
                    # 并发执行前先逐个做授权预检：pre_tool_use hook + 权限检查。
                    # 只有通过的调用才进入并行执行，避免并发路径绕过 PathSandbox、
                    # 权限规则和 hooks（历史上 _execute_single_tool_direct 直接执行，
                    # 造成批量只读工具能逃逸沙箱、hooks 不触发）。
                    approved: list[ToolCallComplete] = []
                    pre_failed: dict[str, ToolResult] = {}
                    for tc in batch.calls:
                        if self.hook_engine:
                            file_path = self._infer_file_path(tc.arguments)
                            hook_ctx = self._build_hook_context(
                                "pre_tool_use",
                                tool_name=tc.tool_name,
                                tool_args=tc.arguments,
                                file_path=file_path,
                            )
                            rejection = await self.hook_engine.run_pre_tool_hooks(hook_ctx)
                            for he in self._drain_hook_events():
                                yield he
                            if rejection is not None:
                                pre_failed[tc.tool_id] = ToolResult(
                                    output=f"Hook rejected: {rejection.reason}",
                                    is_error=True,
                                )
                                continue

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

                    exec_results: dict[str, _ToolExecResult] = {}
                    if approved:
                        for br in await self._execute_batch_parallel(approved):
                            exec_results[br.tool_id] = br
                        if self.hook_engine:
                            for tc in approved:
                                file_path = self._infer_file_path(tc.arguments)
                                hook_ctx = self._build_hook_context(
                                    "post_tool_use",
                                    tool_name=tc.tool_name,
                                    tool_args=tc.arguments,
                                    file_path=file_path,
                                )
                                await self.hook_engine.run_hooks("post_tool_use", hook_ctx)
                                for he in self._drain_hook_events():
                                    yield he

                    # 并发批次内均为已知且已启用的工具，重置连续 unknown 计数
                    # （与串行路径中非 unknown 结果的处理保持一致）。
                    consecutive_unknown = 0
                    for tc in batch.calls:
                        if tc.tool_id in pre_failed:
                            result = pre_failed[tc.tool_id]
                            elapsed = 0.0
                        else:
                            br = exec_results[tc.tool_id]
                            result = br.result
                            elapsed = br.elapsed
                        content = self._maybe_persist_or_truncate(
                            tc.tool_id, result.output
                        )
                        tool_results.append(
                            ToolResultBlock(
                                tool_use_id=tc.tool_id,
                                content=content,
                                is_error=result.is_error,
                            )
                        )
                        yield ToolResultEvent(
                            tool_id=tc.tool_id,
                            tool_name=tc.tool_name,
                            output=result.output,
                            is_error=result.is_error,
                            elapsed=elapsed,
                        )
                else:
                    for tc in batch.calls:
                        result: ToolResult | None = None
                        elapsed = 0.0
                        is_unknown = False

                        if self.hook_engine:
                            file_path = self._infer_file_path(tc.arguments)
                            hook_ctx = self._build_hook_context(
                                "pre_tool_use",
                                tool_name=tc.tool_name,
                                tool_args=tc.arguments,
                                file_path=file_path,
                            )
                            rejection = await self.hook_engine.run_pre_tool_hooks(hook_ctx)
                            for he in self._drain_hook_events():
                                yield he
                            if rejection is not None:
                                result = ToolResult(
                                    output=f"Hook rejected: {rejection.reason}",
                                    is_error=True,
                                )
                                content = self._maybe_persist_or_truncate(
                                    tc.tool_id, result.output
                                )
                                tool_results.append(
                                    ToolResultBlock(
                                        tool_use_id=tc.tool_id,
                                        content=content,
                                        is_error=True,
                                    )
                                )
                                yield ToolResultEvent(
                                    tool_id=tc.tool_id,
                                    tool_name=tc.tool_name,
                                    output=result.output,
                                    is_error=True,
                                    elapsed=0.0,
                                )
                                continue

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

                        if self.hook_engine:
                            file_path = self._infer_file_path(tc.arguments)
                            hook_ctx = self._build_hook_context(
                                "post_tool_use",
                                tool_name=tc.tool_name,
                                tool_args=tc.arguments,
                                file_path=file_path,
                            )
                            await self.hook_engine.run_hooks("post_tool_use", hook_ctx)
                            for he in self._drain_hook_events():
                                yield he

                        content = self._maybe_persist_or_truncate(
                            tc.tool_id, result.output
                        )
                        tool_results.append(
                            ToolResultBlock(
                                tool_use_id=tc.tool_id,
                                content=content,
                                is_error=result.is_error,
                            )
                        )
                        yield ToolResultEvent(
                            tool_id=tc.tool_id,
                            tool_name=tc.tool_name,
                            output=result.output,
                            is_error=result.is_error,
                            elapsed=elapsed,
                        )

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

            if self.hook_engine:
                ctx = self._build_hook_context("turn_end")
                await self.hook_engine.run_hooks("turn_end", ctx)
                for he in self._drain_hook_events():
                    yield he
            yield TurnComplete(turn=iteration)


    def _consume_mailbox(self, conversation: ConversationManager) -> None:
        if not self.team_name or not self._team_manager:
            return
        try:
            mailbox = self._team_manager.get_mailbox(self.team_name)
            if mailbox is None:
                return
            messages = mailbox.consume(self.agent_id)
            for msg in messages:
                prefix = f"[Message from {msg.from_agent}]"
                if msg.message_type != "text":
                    prefix = f"[{msg.message_type} from {msg.from_agent}]"
                content = f"{prefix} {msg.content}"
                conversation.add_user_message(content)
        except Exception as e:
            log.debug("Mailbox consumption failed: %s", e)

    def _build_permission_description(self, tc: ToolCallComplete) -> str:
        if tc.tool_name == "Bash":
            return tc.arguments.get("command", tc.tool_name)
        if tc.tool_name in ("ReadFile", "WriteFile", "EditFile"):
            return tc.arguments.get("file_path", tc.tool_name)
        return str(tc.arguments)

    async def _execute_single_tool_direct(
        self, tc: ToolCallComplete
    ) -> _ToolExecResult:
        # 纯执行器：不做权限检查 / hooks。仅供并发批处理使用，授权预检由
        # 调用方（Agent.run 的并发分支通过 _authorize_tool）在执行前完成。
        tool = self.registry.get(tc.tool_name)
        start = time.monotonic()

        if tool is None:
            return _ToolExecResult(
                tool_id=tc.tool_id,
                tool_name=tc.tool_name,
                result=ToolResult(output=f"Error: unknown tool '{tc.tool_name}'", is_error=True),
                elapsed=time.monotonic() - start,
                is_unknown=True,
            )

        if not self.registry.is_enabled(tc.tool_name):
            return _ToolExecResult(
                tool_id=tc.tool_id,
                tool_name=tc.tool_name,
                result=ToolResult(output=f"Error: tool '{tc.tool_name}' is disabled", is_error=True),
                elapsed=time.monotonic() - start,
                is_unknown=False,
            )

        try:
            params = tool.params_model.model_validate(tc.arguments)
            result = await tool.execute(params)
        except ValidationError as e:
            result = ToolResult(output=f"Parameter validation error: {e}", is_error=True)
        except Exception as e:
            result = ToolResult(output=f"Tool execution error: {e}", is_error=True)

        self._snapshot_for_recovery(tc, result)

        return _ToolExecResult(
            tool_id=tc.tool_id,
            tool_name=tc.tool_name,
            result=result,
            elapsed=time.monotonic() - start,
            is_unknown=False,
        )


    async def _execute_batch_parallel(
        self, calls: list[ToolCallComplete]
    ) -> list[_ToolExecResult]:
        tasks = [self._execute_single_tool_direct(tc) for tc in calls]
        return list(await asyncio.gather(*tasks))

    async def _authorize_tool(
        self, tc: ToolCallComplete
    ) -> AsyncIterator["PermissionRequest | AskUserRequest | _AuthResult"]:
        """并发执行前的授权预检。

        复用与 _execute_tool 完全相同的权限决策逻辑（deny / ask / allow_always），
        但不执行工具本身。ask 决策通过 yield PermissionRequest 交回调用方处理，
        最终 yield 一个 _AuthResult 表示是否放行。
        """
        tool = self.registry.get(tc.tool_name)
        if tool is None:
            yield _AuthResult(
                False,
                ToolResult(output=f"Error: unknown tool '{tc.tool_name}'", is_error=True),
                is_unknown=True,
            )
            return

        if not self.registry.is_enabled(tc.tool_name):
            yield _AuthResult(
                False,
                ToolResult(
                    output=f"Error: tool '{tc.tool_name}' is disabled in current mode",
                    is_error=True,
                ),
            )
            return

        if self.permission_checker:
            decision = self.permission_checker.check(tool, tc.arguments)

            if decision.effect == "deny":
                yield _AuthResult(
                    False,
                    ToolResult(output=f"Permission denied: {decision.reason}", is_error=True),
                )
                return

            if decision.effect == "ask":
                loop = asyncio.get_running_loop()
                future: asyncio.Future[PermissionResponse] = loop.create_future()
                desc = self._build_permission_description(tc)
                yield PermissionRequest(
                    tool_name=tc.tool_name,
                    description=desc,
                    future=future,
                )
                response = await future

                if response == PermissionResponse.DENY:
                    yield _AuthResult(
                        False,
                        ToolResult(output="Permission denied: 用户拒绝了此操作", is_error=True),
                    )
                    return

                if response == PermissionResponse.ALLOW_ALWAYS:
                    from mozilcode.permissions.rules import Rule, extract_content
                    content = extract_content(tc.tool_name, tc.arguments)
                    pattern = f"{content[:60]}*" if len(content) > 60 else f"{content}*"
                    rule = Rule(tool_name=tc.tool_name, pattern=pattern, effect="allow")
                    self.permission_checker.rule_engine.append_local_rule(rule)

        yield _AuthResult(True, None)

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

            # AskUserQuestion: yield an AskUserRequest event so the caller
            # (daemon / embedding runtime) can handle it via the event stream,
            # instead of the old _pending_event side-channel.
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
        """捕获 ReadFile 刚交给模型的内容，以便 Layer 2 压缩对话后
        auto_compact 能重新附加这些数据。每次 ReadFile 多一次磁盘读取，
        比从 tool 输出中反向解析行号要划算。
        """
        if result.is_error or tc.tool_name != "ReadFile":
            return
        path = tc.arguments.get("file_path") if isinstance(tc.arguments, dict) else None
        if not path:
            return
        resolved = resolve_tool_path(path, self.work_dir)
        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return
        self.recovery_state.record_file_read(str(resolved), content)

    async def _extract_memories(
        self, conversation: ConversationManager
    ) -> None:
        if self._extracting or not self.memory_hub:
            return
        self._extracting = True
        try:
            await self._observe_memories(conversation, MEMORY_EVENT_TURN_COMMITTED)
        except Exception as e:
            log.debug("Memory extraction failed: %s", e)
        finally:
            self._extracting = False

    async def _observe_memories(
        self,
        conversation: ConversationManager,
        event_type: str,
    ) -> None:
        if not self.memory_hub:
            return
        try:
            await self.memory_hub.observe(
                MemoryEvent(
                    type=event_type,
                    source="agent",
                    session_id=self.session_id,
                    query=self._latest_user_query(conversation),
                    conversation=conversation,
                    client=self.client,
                    protocol=self.protocol,
                    metadata={"agent_id": self.agent_id},
                )
            )
        except Exception as e:
            log.debug("Memory observe failed for %s: %s", event_type, e)

    async def manual_compact(
        self, conversation: ConversationManager
    ) -> CompactNotification | ErrorEvent:
        # auto_compact 会用摘要替换 conversation.history，所有 tool-result 内容
        # （原始或已替换的）都将被丢弃。这里跳过 apply_tool_result_budget —
        # 它在主循环中的唯一目的是为 LLM 调用生成 api_conv，而本路径不需要
        # 发起看到替换结果的 LLM 调用（auto_compact 内部的摘要调用操作的是原始对话）。
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
            conversation.inject_environment(env_context)
            memory_content = await self._load_memory_context()
            conversation.inject_long_term_memory(
                self.instructions_content, memory_content
            )
            after_tokens = conversation.current_tokens()
            return CompactNotification(
                before_tokens=result.before_tokens,
                message=(
                    f"上下文已压缩（{result.before_tokens:,} → "
                    f"{after_tokens:,} tokens）"
                ),
                after_tokens=after_tokens,
                boundary=result.boundary,
            )
        current_tokens = conversation.current_tokens()
        return CompactNotification(
            before_tokens=current_tokens,
            message=result or "上下文暂未压缩（对话历史为空或未达到压缩条件）",
            after_tokens=current_tokens,
        )

    async def run_to_completion(
        self, task: str, conversation: ConversationManager | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        if conversation is None:
            conversation = ConversationManager()

            env_context = build_environment_context(
                self.work_dir, self.active_skills, self._skill_catalog, self._agent_catalog
            )
            conversation.inject_environment(env_context)

            memory_content = await self._load_memory_context(task)
            conversation.inject_long_term_memory(
                self.instructions_content, memory_content
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

            self._consume_mailbox(conversation)
            if self.notification_fn:
                for note in self.notification_fn():
                    conversation.add_system_reminder(note)

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
                conversation.inject_environment(env_context)

            deferred_names = self.registry.get_deferred_tool_names()
            if deferred_names:
                conversation.add_system_reminder(
                    "The following deferred tools are available via ToolSearch. "
                    "Their schemas are NOT loaded - use ToolSearch with "
                    'query "select:<name>[,<name>...]" to load tool schemas before calling them:\n'
                    + "\n".join(deferred_names)
                )

            api_conv, _new_records = apply_tool_result_budget(
                conversation, self.session_dir, self.replacement_state
            )
            if _new_records:
                append_replacement_records(self.session_dir, _new_records)

            collector = StreamCollector()
            llm_stream = self.client.stream(api_conv, system=system, tools=tools)
            async for _event in collector.consume(llm_stream):
                pass

            response = collector.response
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            if event_callback:
                event_callback({
                    "type": "usage",
                    "usage": {
                        "inputTokens": self.total_input_tokens,
                        "outputTokens": self.total_output_tokens,
                    },
                })

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
                conversation.add_assistant_message(response.text)
                await self._observe_memories(conversation, MEMORY_EVENT_TURN_COMPLETED)
                if self.file_history is not None:
                    summary = response.text[:60] + "..." if len(response.text) > 60 else response.text
                    self.file_history.make_snapshot(len(conversation.history), summary)
                break

            tool_uses = [
                ToolUseBlock(
                    tool_use_id=tc.tool_id,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                )
                for tc in response.tool_calls
            ]
            conversation.add_assistant_message(response.text, tool_uses)
            # assistant 回复已在历史中，锚定实际用量；下一轮迭代只需对
            # 下方追加的 tool results 做字符估算。
            conversation.record_usage_anchor(
                response.input_tokens,
                response.output_tokens,
                response.cache_read,
                response.cache_creation,
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
                content = self._maybe_persist_or_truncate(tc.tool_id, result.output)
                tool_results.append(
                    ToolResultBlock(
                        tool_use_id=tc.tool_id,
                        content=content,
                        is_error=result.is_error,
                    )
                )

            conversation.add_tool_results_message(tool_results)

            if self.hook_engine:
                ctx = self._build_hook_context("turn_end")
                await self.hook_engine.run_hooks("turn_end", ctx)

        return last_text

    async def _execute_tool_noninteractive(
        self, tc: ToolCallComplete
    ) -> ToolResult:
        tool = self.registry.get(tc.tool_name)

        if tool is None:
            return ToolResult(
                output=f"Error: unknown tool '{tc.tool_name}'", is_error=True
            )

        if not self.registry.is_enabled(tc.tool_name):
            return ToolResult(
                output=f"Error: tool '{tc.tool_name}' is disabled",
                is_error=True,
            )

        if self.hook_engine:
            file_path = self._infer_file_path(tc.arguments)
            hook_ctx = self._build_hook_context(
                "pre_tool_use",
                tool_name=tc.tool_name,
                tool_args=tc.arguments,
                file_path=file_path,
            )
            rejection = await self.hook_engine.run_pre_tool_hooks(hook_ctx)
            if rejection is not None:
                return ToolResult(
                    output=f"Hook rejected: {rejection.reason}",
                    is_error=True,
                )

        if self.permission_checker:
            decision = self.permission_checker.check(tool, tc.arguments)
            if decision.effect == "deny":
                return ToolResult(
                    output=f"Permission denied: {decision.reason}",
                    is_error=True,
                )
            if decision.effect == "ask":
                if self.permission_mode == PermissionMode.DONT_ASK:
                    pass  # 自动批准
                else:
                    return ToolResult(
                        output="Permission denied: non-interactive agent cannot prompt user",
                        is_error=True,
                    )

        try:
            params = tool.params_model.model_validate(tc.arguments)
            result = await tool.execute(params)
        except ValidationError as e:
            result = ToolResult(
                output=f"Parameter validation error: {e}", is_error=True
            )
        except Exception as e:
            result = ToolResult(
                output=f"Tool execution error: {e}", is_error=True
            )

        if self.hook_engine:
            file_path = self._infer_file_path(tc.arguments)
            hook_ctx = self._build_hook_context(
                "post_tool_use",
                tool_name=tc.tool_name,
                tool_args=tc.arguments,
                file_path=file_path,
            )
            await self.hook_engine.run_hooks("post_tool_use", hook_ctx)

        return result

    def _maybe_persist_or_truncate(self, tool_use_id: str, text: str) -> str:
        from mozilcode.context.manager import (
            SINGLE_RESULT_CHAR_LIMIT,
            make_persisted_preview,
            persist_tool_result,
        )

        if len(text) > SINGLE_RESULT_CHAR_LIMIT:
            fp = persist_tool_result(tool_use_id, text, self.session_dir)
            return make_persisted_preview(text, fp)
        if len(text) > MAX_OUTPUT_CHARS:
            return text[:MAX_OUTPUT_CHARS] + "\n… (output truncated)"
        return text
