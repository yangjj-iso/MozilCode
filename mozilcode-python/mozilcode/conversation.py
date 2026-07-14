"""对话管理模块。

定义了对话历史的数据结构和 ConversationManager 管理器。

数据结构：
- ToolUseBlock: LLM 请求调用工具的描述
- ToolResultBlock: 工具执行结果
- ThinkingBlock: LLM 思考过程块
- Message: 统一表示 user/assistant 消息（多块结构）

ConversationManager 职责：
- 管理消息历史（增删改查）
- 环境上下文和长期记忆的一次性注入
- token 用量估算（API 锚点 + 字符估算的混合策略）
- 上下文压缩后替换历史
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolUseBlock:
    """LLM 请求调用工具的完整描述（工具名 + 参数）。"""
    tool_use_id: str          # 工具调用唯一 ID（用于关联结果）
    tool_name: str            # 工具名称
    arguments: dict[str, Any] # 工具参数


@dataclass
class ToolResultBlock:
    """工具执行结果（关联到对应的 ToolUseBlock）。"""
    tool_use_id: str    # 关联的工具调用 ID
    content: str        # 结果内容（文本）
    is_error: bool = False  # 是否为错误结果


@dataclass
class ThinkingBlock:
    """LLM 的思考过程块（extended thinking），包含思考和签名。"""
    thinking: str    # 思考内容
    signature: str   # 思考签名（用于 API 验证）


@dataclass
class Message:
    """对话历史中的一条消息，统一表示 user/assistant 消息。

    采用 Anthropic 风格的多块结构：一条消息可同时包含文本内容、
    工具调用请求（assistant）、工具执行结果（user）和思考块（assistant）。
    """
    role: str  # "user" | "assistant"
    content: str
    tool_uses: list[ToolUseBlock] = field(default_factory=list)        # 工具调用
    tool_results: list[ToolResultBlock] = field(default_factory=list)  # 工具结果
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list) # 思考块


# 估算最后一次 API 用量锚点之后追加的消息 token 开销时使用的字符/token 比率。
# 与 context.manager 中的恢复状态启发值保持一致，全代码库统一使用同一比率。
_CHARS_PER_TOKEN = 3.5


def _message_chars(m: Message) -> int:
    n = len(m.content)
    for tb in m.thinking_blocks:
        n += len(tb.thinking)
    for tu in m.tool_uses:
        n += len(tu.tool_name) + len(json.dumps(tu.arguments, ensure_ascii=False))
    for tr in m.tool_results:
        n += len(tr.content)
    return n


def estimate_tokens(messages: list[Message]) -> int:
    """基于字符数对一组消息做 token 估算。

    刻意做得粗略——它只覆盖那些尚未锚定到真实 API 用量数值的消息，这部分的
    精确度本就无关紧要。统计内容包括消息正文、thinking、工具调用参数以及
    工具结果内容。
    """
    total = sum(_message_chars(m) for m in messages)
    return int(total / _CHARS_PER_TOKEN)


@dataclass
class ConversationManager:
    """对话管理器：维护对话历史、环境注入状态和 token 用量锚点。

    职责：
    1. 管理消息历史（add_user_message / add_assistant_message / add_tool_results 等）
    2. 环境上下文和长期记忆的一次性注入（inject_environment / inject_long_term_memory）
    3. token 用量估算（基于 API 锚点 + 字符估算的混合策略）
    4. 上下文压缩后替换历史（replace_history）
    """
    history: list[Message] = field(default_factory=list)
    env_injected: bool = field(default=False, init=False)  # 环境上下文是否已注入
    ltm_injected: bool = field(default=False, init=False)   # 长期记忆是否已注入
    # API 报告的每轮真实 prompt 大小，保留用于向后兼容。
    # 现在与 baseline_tokens 一致（input + cache_read + cache_creation + output）。
    last_input_tokens: int = field(default=0, init=False)
    # 真实用量锚点。baseline_tokens 是上一轮 API 计费的完整 prompt+output 大小；
    # anchor_count 是记录该数值时的消息数量。两者配合让 current_tokens() 在
    # anchor_count 以内信任 API 数据，只对之后追加的消息做字符估算。
    # baseline_tokens == 0 表示"尚无锚点"（冷启动），此时退化为纯字符估算。
    baseline_tokens: int = field(default=0, init=False)
    anchor_count: int = field(default=0, init=False)

    def record_usage_anchor(
        self,
        input_tokens: int,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_creation: int = 0,
    ) -> None:
        """根据一次 API 响应钉下一个真实用量锚点。

        baseline = input + cache_read + cache_creation + output。各家服务商
        返回的 input_tokens 已经排除了命中缓存的 token，所以这三个 input 分量
        是相加关系，合起来才是真正的 prompt 大小；之所以再加上 output，是因为
        assistant 的回复此刻已成为历史的一部分。anchor_count 对齐到当前的消息
        数量，这样后续新追加的消息就成了唯一需要估算的部分。
        """
        self.baseline_tokens = (
            input_tokens + cache_read + cache_creation + output_tokens
        )
        self.anchor_count = len(self.history)
        # 保持旧字段同步，兼容仍在使用它的读取方。
        self.last_input_tokens = self.baseline_tokens

    def current_tokens(self) -> int:
        """对当前对话中的 token 数量做出最佳估算。

        有锚点时：baseline（真实用量）+ 仅对锚点之后追加的那些消息做字符估算。
        没有锚点时（冷启动，或刚经历一次压缩重置）：对整个历史做字符估算，
        这样在第一次 API 响应到来之前阈值检查依然能正常工作。
        """
        if self.baseline_tokens <= 0:
            return estimate_tokens(self.history)
        tail = self.history[self.anchor_count:]
        return self.baseline_tokens + estimate_tokens(tail)

    def add_user_message(self, content: str) -> None:
        """追加一条用户消息。"""
        self.history.append(Message(role="user", content=content))

    def add_assistant_message(
        self,
        content: str,
        tool_uses: list[ToolUseBlock] | None = None,
        thinking_blocks: list[ThinkingBlock] | None = None,
    ) -> None:
        """追加一条 assistant 消息，可携带工具调用和思考块。"""
        self.history.append(
            Message(
                role="assistant",
                content=content,
                tool_uses=tool_uses or [],
                thinking_blocks=thinking_blocks or [],
            )
        )

    def add_system_reminder(self, content: str) -> None:
        """以 system-reminder 标签包裹的方式追加一条用户消息。

        用于注入 Hook 通知、记忆提醒等系统级上下文，
        LLM 会将其视为系统提示而非用户直接输入。
        """
        self.history.append(
            Message(
                role="user",
                content=f"<system-reminder>\n{content}\n</system-reminder>",
            )
        )

    def add_tool_results_message(self, tool_results: list[ToolResultBlock]) -> None:
        """追加一条携带工具结果的用户消息（content 为空，结果在 tool_results 中）。"""
        self.history.append(
            Message(role="user", content="", tool_results=tool_results)
        )


    def inject_environment(self, context: str) -> None:
        """在历史最前面插入环境上下文（只注入一次）。

        包含工作目录、可用 Skill、Agent 类型清单等信息。
        """
        if not self.env_injected:
            self.history.insert(0, Message(role="user", content=context))
            self.env_injected = True

    def inject_long_term_memory(
        self, instructions: str, memories: str
    ) -> None:
        """在环境上下文之后插入长期记忆（只注入一次）。

        包含两部分：
        1. MOZILCODE.md 指令文件内容（项目级 + 用户级）
        2. 自动提取的记忆（来自 memories.md）
        以及当前日期。全部包裹在 system-reminder 标签中。
        """
        if self.ltm_injected:
            return
        sections: list[str] = []
        if instructions:
            sections.append(
                "# mozilcodeMd\n"
                "Codebase and user instructions are shown below. "
                "Be sure to adhere to these instructions. "
                "IMPORTANT: These instructions OVERRIDE any default behavior "
                "and you MUST follow them exactly as written.\n\n" + instructions
            )
        if memories:
            sections.append("# autoMemory\n" + memories)
        if not sections:
            return
        from datetime import date

        sections.append(f"# currentDate\nToday's date is {date.today().isoformat()}.")
        body = "\n\n".join(sections)
        wrapped = (
            "<system-reminder>\n"
            "As you answer the user's questions, you can use the following context:\n"
            + body
            + "\n\n      IMPORTANT: this context may or may not be relevant to your tasks."
            " You should not respond to this context unless it is highly relevant to your task.\n"
            "</system-reminder>"
        )
        pos = 1 if self.env_injected else 0
        self.history.insert(pos, Message(role="user", content=wrapped))
        self.ltm_injected = True

    def replace_history(self, new_messages: list[Message]) -> None:
        """用新消息列表替换整个历史（上下文压缩后调用）。

        重置 env_injected / ltm_injected 标记，使下一轮可以重新注入环境。
        清除用量锚点，使 current_tokens() 退化为字符估算。
        """
        self.history = new_messages
        self.env_injected = False
        self.ltm_injected = False
        # 旧的用量锚点描述的是压缩前的对话记录，这里清除它，
        # 使 current_tokens() 退化为字符估算，直到下次 API 响应
        # 基于摘要后的历史重新建立锚点。
        self.baseline_tokens = 0
        self.anchor_count = 0
        self.last_input_tokens = 0


    def get_messages(self) -> list[Message]:
        """返回历史消息的副本。"""
        return list(self.history)
