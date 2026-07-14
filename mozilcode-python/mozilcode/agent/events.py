"""Agent 事件流类型定义。

定义了 Agent.run() 异步生成器产出的全部事件类型（AgentEvent 联合类型）。
前端（TUI / Daemon / GUI）通过消费这些事件来展示 Agent 的运行状态。

事件按阶段分为：
- 流式输出：StreamText / ThinkingText
- 工具交互：ToolUseEvent / ToolResultEvent / PermissionRequest / AskUserRequest
- 轮次控制：TurnComplete / LoopComplete
- 系统状态：UsageEvent / ErrorEvent / RetryEvent
- 上下文压缩：CompactStarted / CompactNotification
- Hook 通知：HookEvent
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mozilcode.context import CompactBoundary


@dataclass
class StreamText:
    """LLM 生成的文本片段（流式增量）。"""
    text: str


@dataclass
class ThinkingText:
    """LLM 的思考过程文本片段（extended thinking 流式增量）。"""
    text: str


@dataclass
class RetryEvent:
    """LLM 请求失败后重试事件。"""
    reason: str           # 失败原因（如速率限制 / 网络错误）
    wait: float = 0.0     # 重试前等待时间（秒）


@dataclass
class ToolUseEvent:
    """LLM 请求调用工具事件（工具开始执行前产出）。"""
    tool_name: str           # 工具名称
    tool_id: str             # 工具调用唯一 ID
    arguments: dict[str, Any]  # 工具参数


@dataclass
class ToolResultEvent:
    """工具执行完成事件（工具执行后产出，携带结果）。"""
    tool_id: str        # 关联的工具调用 ID
    tool_name: str      # 工具名称
    output: str         # 执行结果文本
    is_error: bool      # 是否为错误结果
    elapsed: float      # 执行耗时（秒）


@dataclass
class TurnComplete:
    """单轮迭代完成事件（LLM 返回但不包含工具调用时产出）。"""
    turn: int           # 当前轮次序号


@dataclass
class LoopComplete:
    """Agent 主循环完成事件（任务结束，Agent.run() 即将返回）。"""
    total_turns: int    # 总轮次数


@dataclass
class UsageEvent:
    """LLM API 用量事件（每轮 API 响应后产出，报告 token 消耗）。"""
    input_tokens: int       # 输入 token 数
    output_tokens: int      # 输出 token 数
    context_tokens: int = 0 # 上下文 token 数（窗口占用）


@dataclass
class ErrorEvent:
    """错误事件（Agent 运行过程中发生异常时产出）。"""
    message: str        # 错误消息


@dataclass
class CompactNotification:
    """上下文压缩完成通知（Layer 2 摘要完成后产出）。"""
    before_tokens: int                          # 压缩前 token 数
    message: str                                # 压缩描述
    after_tokens: int = 0                       # 压缩后 token 数
    boundary: CompactBoundary | None = None    # 压缩边界信息


@dataclass
class CompactStarted:
    """上下文压缩开始事件（接近窗口阈值时触发，前端可显示进度提示）。"""
    current_tokens: int    # 当前 token 数
    threshold: int          # 触发阈值
    context_window: int     # 上下文窗口大小
    message: str = "正在自动压缩上下文"  # 展示消息


@dataclass
class HookEvent:
    """Hook 执行通知事件（Hook 引擎执行 Hook 后产出，前端可展示结果）。"""
    hook_id: str        # Hook ID
    event: str          # 触发的事件名（如 pre_tool_use / post_tool_use）
    output: str         # Hook 执行输出
    success: bool       # 是否执行成功


class PermissionResponse(Enum):
    """权限请求的响应类型。"""
    ALLOW = "allow"                    # 允许本次
    DENY = "deny"                      # 拒绝
    ALLOW_ALWAYS = "allow_always"      # 永久允许（后续不再询问）


@dataclass
class PermissionRequest:
    """权限请求事件（工具需要用户授权时产出，前端弹窗确认后唤醒 Agent）。

    Agent yield 此事件后会挂起等待，直到 future.set_result() 被调用。
    """
    tool_name: str                       # 需要授权的工具名
    description: str                     # 权限描述（展示给用户）
    future: asyncio.Future[PermissionResponse]  # 异步等待用户响应


@dataclass
class AskUserRequest:
    """用户输入请求事件（AskUserQuestion 工具需要用户回答时产出）。

    Agent yield 此事件后会挂起等待，直到 future.set_result() 被调用。
    """

    questions: list[dict[str, Any]]              # 问题列表
    future: asyncio.Future[dict[str, str]]       # 异步等待用户回答


# Agent 事件联合类型：Agent.run() 产出的所有可能事件
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


__all__ = [
    "AgentEvent",
    "AskUserRequest",
    "CompactNotification",
    "CompactStarted",
    "ErrorEvent",
    "HookEvent",
    "LoopComplete",
    "PermissionRequest",
    "PermissionResponse",
    "RetryEvent",
    "StreamText",
    "ThinkingText",
    "ToolResultEvent",
    "ToolUseEvent",
    "TurnComplete",
    "UsageEvent",
]
