from __future__ import annotations

from enum import StrEnum


class LifecycleEvent(StrEnum):
    """Agent 生命周期的全部 Hook 触发点。

    每个事件在 Agent 循环的固定位置触发，用户可在 config.yaml 中为这些事件
    配置自定义 Hook（执行命令 / 注入提示 / 发 HTTP / 派子 Agent）。
    """

    # === 会话（Session）级别 ===
    # 会话开始时触发（Agent.run() 入口，注入环境上下文和记忆后）
    SESSION_START = "session_start"
    # 会话结束时触发（LLM 不再请求工具调用，任务完成时）
    SESSION_END = "session_end"

    # === 轮次（Turn）级别 ===
    # 每轮迭代开始时触发
    TURN_START = "turn_start"
    # 每轮迭代结束时触发
    TURN_END = "turn_end"

    # === 工具（Tool）级别 ===
    # 工具执行前触发（可以 reject 拦截工具执行）
    PRE_TOOL_USE = "pre_tool_use"
    # 工具执行后触发（可以执行 lint / 格式化等后置操作）
    POST_TOOL_USE = "post_tool_use"

    # === 消息（Message）级别 ===
    # 发送给 LLM 之前触发（可以改写 prompt）
    PRE_SEND = "pre_send"
    # 收到 LLM 响应之后触发（可以处理响应）
    POST_RECEIVE = "post_receive"

    # === 系统（System）级别 ===
    # 程序启动时触发
    STARTUP = "startup"
    # 程序关闭时触发
    SHUTDOWN = "shutdown"
    # 发生错误时触发
    ERROR = "error"
    # 上下文压缩时触发
    COMPACT = "compact"
    # 权限请求时触发
    PERMISSION_REQUEST = "permission_request"
    # 文件变更时触发
    FILE_CHANGE = "file_change"
    # 命令执行时触发
    COMMAND_EXECUTE = "command_execute"
