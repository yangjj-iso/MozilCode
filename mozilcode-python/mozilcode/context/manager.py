"""Layer2 自动压缩。

阈值判断、摘要、保留尾部、tool 配对对齐与 circuit breaker。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from mozilcode.conversation import (
    ConversationManager,
    Message,
    estimate_tokens,
)
from mozilcode.context.recovery import (
    RECOVERY_FILE_LIMIT,
    RECOVERY_SKILLS_BUDGET,
    RECOVERY_TOKENS_PER_FILE,
    RECOVERY_TOKENS_PER_SKILL,
    FileReadRecord,
    RecoveryState,
    SkillInvocationRecord,
    _RECOVERY_CHARS_PER_TOKEN,
    build_recovery_attachment,
)
from mozilcode.context.replacement import (
    REPLACEMENT_RECORDS_FILENAME,
    ContentReplacementRecord,
    ContentReplacementState,
    append_replacement_records,
    clone_replacement_state,
    create_replacement_state,
    load_replacement_records,
    reconstruct_replacement_state,
)
from mozilcode.context.tool_results import (
    AGGREGATE_CHAR_LIMIT,
    KEEP_RECENT_TURNS,
    OLD_RESULT_SNIP_CHARS,
    PERSISTED_TAG,
    PREVIEW_CHARS,
    SESSION_SUBDIR,
    SINGLE_RESULT_CHAR_LIMIT,
    SNIPPED_TAG,
    apply_tool_result_budget,
    cleanup_tool_results,
    ensure_session_dir,
    make_persisted_preview,
    persist_tool_result,
)
from mozilcode.serialization import build_messages

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SUMMARY_OUTPUT_RESERVE = 20_000
AUTO_COMPACT_SAFETY_MARGIN = 13_000
MANUAL_COMPACT_SAFETY_MARGIN = 3_000

# Layer 2 "保留近期原文"窗口（对应 Claude Code compact.ts 的
# buildPostCompactMessages messagesToKeep）。压缩时，尾部消息按 token 累计不超过
# KEEP_RECENT_TOKENS、或消息数不少于 MIN_KEEP_MESSAGES（取先满足的条件保底）保留原文，
# 不纳入摘要。累计超过 KEEP_MAX_TOKENS 时停止，防止单条超大消息吞掉整个窗口。
KEEP_RECENT_TOKENS = 10_000
MIN_KEEP_MESSAGES = 5
KEEP_MAX_TOKENS = 40_000

# 前缀 token 数低于此阈值时不值得做摘要——摘要往返的开销比回收的空间还大，
# 退化为不压缩、保留原始历史（避免「压了个寂寞」）。
MIN_SUMMARIZE_PREFIX_TOKENS = 2_000

# ---------------------------------------------------------------------------
# 事件
# ---------------------------------------------------------------------------


@dataclass
class CompactBoundary:
    """Layer 2 压缩的结构化结果，上交给 session 层处理。

    `summary` 是大模型对被摘要前缀生成的摘要；`keep` 是 auto_compact 原样保留、
    未做改动的近期尾部消息。session 层（持有 sessionId / 文件句柄）会把二者一起
    内联进一条 compact_boundary 记录，这样 resume 时就能重建压缩后的状态。
    用这种方式把写操作解耦出去，能让 auto_compact 保持纯粹、不依赖任何 session。
    """

    summary: str
    keep: list[Message]


@dataclass
class CompactEvent:
    before_tokens: int
    # 摘要成功时填充，调用方可据此持久化 compact_boundary 记录。
    # 未产出摘要时为 None。
    boundary: CompactBoundary | None = None


# ---------------------------------------------------------------------------
# Layer 2：全对话摘要（Auto-Compact）
# ---------------------------------------------------------------------------

def compute_compact_threshold(context_window: int, manual: bool = False) -> int:
    effective = context_window - SUMMARY_OUTPUT_RESERVE
    margin = MANUAL_COMPACT_SAFETY_MARGIN if manual else AUTO_COMPACT_SAFETY_MARGIN
    return effective - margin


def should_auto_compact(last_input_tokens: int, context_window: int) -> bool:
    return last_input_tokens >= compute_compact_threshold(context_window)


SUMMARY_PROMPT = """\
你是一个对话摘要助手。你只能输出纯文本，不能调用任何工具。

请对下面的对话生成一份结构化摘要。

先在 <analysis> 标签中梳理对话中发生了什么（这部分会被丢弃），然后在 <summary> 标签中输出正式摘要。

<summary> 必须包含以下 9 个部分：

1. **主要请求和意图**：用户到底想做什么
2. **关键技术概念**：讨论过的重要技术点
3. **文件和代码段**：涉及哪些文件，关键代码片段要保留
4. **错误和修复**：遇到了什么错，怎么解决的
5. **问题解决过程**：解决问题的思路和方法
6. **所有用户消息**：用户说过的所有非工具结果的话（原文保留，不可改写！）
7. **待办任务**：还没完成的事
8. **当前工作**：最近在做什么（要最详细）
9. **可能的下一步**：接下来打算做什么

提醒：不要调用任何工具。工具调用会被拒绝，你会失败。只输出纯文本。"""


def extract_summary(llm_output: str) -> str:
    start = llm_output.find("<summary>")
    end = llm_output.find("</summary>")
    if start == -1 or end == -1:
        return llm_output
    return llm_output[start + len("<summary>"):end].strip()


def build_compact_messages(
    summary: str,
    attachment: str = "",
    has_keep_tail: bool = False,
    transcript_path: str = "",
) -> list[Message]:
    content = "本次会话延续自之前的对话，因上下文空间不足进行了压缩。以下是早期对话的摘要：\n\n" + summary
    if has_keep_tail:
        content += "\n\n近期消息已原样保留。"
    if transcript_path:
        content += f"\n\n如果你需要压缩前的具体细节（代码片段、报错信息等），请用 ReadFile 读取完整会话记录：{transcript_path}"
    if attachment:
        content += "\n\n---\n\n" + attachment
    return [
        Message(role="user", content=content),
    ]


def _group_messages_by_turn(messages: list[Message]) -> list[list[Message]]:
    groups: list[list[Message]] = []
    current: list[Message] = []
    for msg in messages:
        current.append(msg)
        if msg.role == "assistant" and not msg.tool_uses:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _message_tokens(msg: Message) -> int:
    """估算单条消息的 token 数，复用共享的字符数启发式算法。"""
    return estimate_tokens([msg])


def _compute_keep_start_index(messages: list[Message]) -> int:
    """决定压缩时尾部要原样保留多少条消息。

    从尾部向头部遍历 `messages`，逐条累加 token 估算值。只要还有任一保底条件
    未满足——累计 token 尚未达到 KEEP_RECENT_TOKENS，或保留的消息数仍少于
    MIN_KEEP_MESSAGES——当前消息就会被纳入保留窗口；但一旦纳入下一条消息会使
    保留总量超过 KEEP_MAX_TOKENS，遍历立即停止（这样单条超大的尾部消息就不会把
    整个 history 都拖进窗口）。

    返回第一条被保留消息的下标（keepStartIndex）。原始遍历结束后，必要时会把这个
    下标往前挪，确保被保留的 tool_result 不会和它对应的 tool_use 被拆散——
    参见 `_align_keep_start_to_tool_pair`。
    """
    n = len(messages)
    if n == 0:
        return 0

    kept_tokens = 0
    kept_count = 0
    keep_start = n  # 尚未保留任何消息

    for i in range(n - 1, -1, -1):
        tok = _message_tokens(messages[i])

        # 在已经保留了至少一条消息的前提下，如果纳入当前消息会突破硬上限则停止
        # （但绝不拒绝保留最后一条消息，即使它单独就超限）。
        if kept_count > 0 and kept_tokens + tok > KEEP_MAX_TOKENS:
            break

        kept_tokens += tok
        kept_count += 1
        keep_start = i

        # 保底条件已满足（token 下限或消息条数下限达到其一）：
        # 近期原文保留足够了，停止回溯。
        if kept_tokens >= KEEP_RECENT_TOKENS or kept_count >= MIN_KEEP_MESSAGES:
            break

    return _align_keep_start_to_tool_pair(messages, keep_start)


def _align_keep_start_to_tool_pair(messages: list[Message], keep_start: int) -> int:
    """把 keep_start 往前挪，确保我们绝不会保留一个孤立的 tool_result。

    携带 tool_results 的 user 消息，会和它前面那条发起对应 tool_uses 的 assistant
    消息配成一对。如果 keep_start 正好落在这样一条 user 消息上，就把它往前回退到
    （至少）配对的那条 assistant 消息，让 tool_use 与 tool_result 的配对关系保持完整。
    宁可多保留一对，也不要只保留半对（一个模型无法归属到任何调用的悬空 tool_result）。
    """
    while 0 < keep_start < len(messages):
        msg = messages[keep_start]
        if msg.role == "user" and msg.tool_results:
            prev = messages[keep_start - 1]
            if prev.role == "assistant" and prev.tool_uses:
                keep_start -= 1
                continue
        break
    return keep_start


def _prefix_too_small_to_compact(prefix: list[Message]) -> bool:
    """当摘要 `prefix` 能回收的空间太少、不值得做时返回 True。"""
    if not prefix:
        return True
    return estimate_tokens(prefix) < MIN_SUMMARIZE_PREFIX_TOKENS


# ---------------------------------------------------------------------------
# 熔断器
# ---------------------------------------------------------------------------


@dataclass
class CompactCircuitBreaker:
    max_failures: int = 3
    consecutive_failures: int = field(default=0, init=False)

    def record_failure(self) -> None:
        self.consecutive_failures += 1

    def record_success(self) -> None:
        self.consecutive_failures = 0


    def is_open(self) -> bool:
        return self.consecutive_failures >= self.max_failures


# ---------------------------------------------------------------------------
# Auto-compact 编排器
# ---------------------------------------------------------------------------

async def auto_compact(
    conversation: ConversationManager,
    client: Any,
    context_window: int,
    session_dir: Path,
    protocol: str = "anthropic",
    manual: bool = False,
    breaker: CompactCircuitBreaker | None = None,
    recovery: RecoveryState | None = None,
    tool_schemas: list[Mapping[str, Any]] | None = None,
    transcript_path: str = "",
) -> CompactEvent | str | None:
    threshold = compute_compact_threshold(context_window, manual=manual)

    # 以真实 API 用量为锚点做阈值判断：current_tokens() 返回上次计费基准
    # （input + cache_read + cache_creation + output）加上锚点之后新增消息的
    # 字符估算。冷启动或刚压缩清空锚点时，退化为对整个 history 做字符估算。
    current = conversation.current_tokens()

    if not manual and current < threshold:
        return None

    if not manual and breaker is not None and breaker.is_open():
        return "自动压缩已熔断（连续失败 3 次），请手动处理或调用 daemon compact API"

    before_tokens = current

    # 决定保留多少尾部消息原文。只有前缀 messages[:keep_start] 会被摘要；
    # messages[keep_start:] 原样保留，让模型看到近期原文而非靠有损摘要复述。
    keep_start = _compute_keep_start_index(conversation.history)
    to_summarize = conversation.history[:keep_start]
    keep_tail = conversation.history[keep_start:]

    # 待摘要的前缀太小时退化为不压缩——要么全部消息都落在保留窗口内
    # （keep_start <= 0），要么摘要回收的 token 还不够摘要本身的开销。
    if keep_start <= 0 or _prefix_too_small_to_compact(to_summarize):
        return None

    messages_for_summary = build_messages(list(to_summarize), protocol)

    summary_messages: list[dict[str, Any]] = [
        {"role": "user", "content": SUMMARY_PROMPT},
    ]
    summary_messages.extend(messages_for_summary)
    summary_messages.append(
        {"role": "user", "content": "请根据以上对话生成结构化摘要。记住：不要调用任何工具。"}
    )

    summary_conv = ConversationManager()
    summary_conv.history = [
        Message(role="user", content=SUMMARY_PROMPT),
    ]
    # 只摘要前缀；保留的尾部在下面重建时原样拼回。
    for msg in to_summarize:
        summary_conv.history.append(msg)
    summary_conv.history.append(
        Message(role="user", content="请根据以上对话生成结构化摘要。记住：不要调用任何工具。")
    )

    max_retries = 3
    llm_output: str | None = None

    for attempt in range(max_retries):
        try:
            from mozilcode.tools.base import StreamEnd, StreamEvent, TextDelta

            collected_text = ""
            async for event in client.stream(summary_conv, system=SUMMARY_PROMPT):
                if isinstance(event, TextDelta):
                    collected_text += event.text
                elif isinstance(event, StreamEnd):
                    pass
            llm_output = collected_text
            break

        except Exception as e:
            err_msg = str(e).lower()
            if "prompt" in err_msg and "long" in err_msg or "too many" in err_msg:
                groups = _group_messages_by_turn(summary_conv.history[1:-1])
                drop_count = max(1, len(groups) // 5)
                remaining = groups[drop_count:]
                summary_conv.history = (
                    [summary_conv.history[0]]
                    + [m for g in remaining for m in g]
                    + [summary_conv.history[-1]]
                )
                continue
            if breaker is not None:
                breaker.record_failure()
            return f"摘要生成失败: {e}"

    if llm_output is None:
        if breaker is not None:
            breaker.record_failure()
        return "摘要生成失败：多次重试后仍超出上下文限制"

    summary = extract_summary(llm_output)
    attachment = build_recovery_attachment(recovery, tool_schemas)
    # 重建 = 摘要(user) + 尾部原文。
    new_messages = build_compact_messages(
        summary,
        attachment=attachment,
        has_keep_tail=bool(keep_tail),
        transcript_path=transcript_path,
    )
    new_messages = new_messages + list(keep_tail)

    # replace_history 替换为重建后的对话并将用量锚点清零
    # （baseline_tokens / anchor_count / last_input_tokens），这是必须的：
    # 旧的 anchor_count 对应压缩前的消息列表，现在已无意义，
    # 不清零会导致 current_tokens() 对增量的估算出错。
    # 下一次 API 响应会基于重建后的 history 重新锚定。
    conversation.replace_history(new_messages)
    cleanup_tool_results(session_dir)

    if breaker is not None:
        breaker.record_success()

    # 将结构化的 boundary（摘要 + 保留的尾部原文）交给 session 层，
    # 由它持久化为一条 compact_boundary 记录。keep tail 就是拼回重建 history 的那段。
    return CompactEvent(
        before_tokens=before_tokens,
        boundary=CompactBoundary(summary=summary, keep=list(keep_tail)),
    )
