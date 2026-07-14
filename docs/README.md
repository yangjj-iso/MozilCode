# MozilCode 文档索引

本目录是 **MozilCode / mozilcode-python** 的源码级学习文档：面向“读代码、跟数据流、改模块”而不是营销说明。

对应代码主目录：

- 运行时：`mozilcode-python/mozilcode/`
- 测试：`mozilcode-python/tests/`
- GUI（若存在）：仓库内 GUI 工程 / Vite 前端

## 阅读顺序（推荐）

| 顺序 | 文档 | 你应该带走什么 |
|------|------|----------------|
| 0 | [本索引](./README.md) | 文档地图、概念边界、常见误解 |
| 1 | [01-架构总览与核心概念](./01-架构总览与核心概念.md) | 系统分层、入口、事件驱动、会话/项目/上下文三概念 |
| 2 | [02-Agent核心运行循环](./02-Agent核心运行循环.md) | `Agent.run()` 每一步、事件 yield、工具批处理 |
| 3 | [03-LLM客户端与Provider适配层](./03-LLM客户端与Provider适配层.md) | 多协议适配、流式事件、序列化、错误映射 |
| 4 | [04-配置系统](./04-配置系统.md) | 配置层级合并、schema、校验、removed capabilities |
| 5 | [05-Daemon服务](./05-Daemon服务.md) | **前后端协议、会话维护、work_dir、任务与上下文接续** |
| 6 | [06-工具系统](./06-工具系统.md) | Tool/Registry/延迟工具/执行路径 |
| 7 | [07-权限Hook与上下文管理](./07-权限Hook与上下文管理.md) | 权限 Future 握手、Hook、双层上下文摘要 |
| 8 | [08-记忆技能MCP-Teams-A2A](./08-记忆技能MCP-Teams-A2A.md) | 记忆入口、Skill、MCP、Teams、A2A、Worktree |
| 9 | [09-GUI前端](./09-GUI前端.md) | Vue 状态、WS 事件处理、与 Daemon 对接 |
| 10 | [10-上下文与记忆系统](./10-上下文与记忆系统.md) | **专章学习**：四本账、Layer1/2、注入/reinject、记忆读写时序 |
| 11 | [11-驾驭工程](./11-驾驭工程.md) | **专章学习**：权限/沙箱/Hook/HITL/取消/预算如何拴住 Agent |

## 三条“不要混”的边界

```text
1) ConversationManager.history
   = 真对话账本（喂给 LLM 的消息来源）

2) Daemon event_logs / events.jsonl
   = 前端展示/回放账本（WS 推送用）
   ≠ 默认不会在 Daemon 重启后还原成 history

3) api_conv（prepare_api_conversation 输出）
   = 当次发送给模型的临时副本
   ≠ 真历史；可裁剪 tool-result（Layer1）
```

## 三条入口路径

```text
TUI / CLI:
  python -m mozilcode  →  app.py / driver
  同进程直接 Agent.run(conversation)

Daemon + GUI:
  uvicorn Starlette(daemon)
  HTTP 控制 + WS 事件
  Agent 在 Daemon 进程内按 session 持有

A2A 外部客户端:
  /a2a/* 或 /.well-known/agent-card.json
  复用 Daemon 会话/任务能力
```

## 文档维护约定

- 以**当前代码行为**为准；注释/旧文档与运行时冲突时，先信运行时与测试。
- 引用路径尽量写到模块级：`mozilcode/daemon/session/runtime.py`。
- 大段伪代码若与源码细节有出入，以源码为准；文档优先讲职责与数据流。
- 更新某个子系统时，至少同步：
  - 本索引（若新增文档）
  - `01` 总览图
  - 对应专题文档

## 快速问答入口

| 问题 | 先看 |
|------|------|
| 一次用户消息如何变成工具调用？ | 02 + 06 |
| 前端如何收流式文本？ | 05 + 09 |
| 会话如何绑定项目目录？ | 05（work_dir） |
| 多轮上下文如何接上？ | 05 + 02 + conversation.py |
| 权限弹窗如何阻塞 Agent？ | 07 + 05 serialize |
| 上下文为什么突然变短？ | 10 + 07 Layer1/Layer2 |
| 记忆何时 load / extract？ | 10 + 08 |
| 模型一次调用到底吃什么？ | 10 + 02 |
| MCP 工具从哪来？ | 08 + 06 Registry |
| 配置改了为什么旧会话没变？ | 04 + 05（new sessions） |
| Agent 如何被权限/沙箱/取消驾驭？ | 11 + 07 |
| 点允许后如何继续执行工具？ | 11 + 05 serialize |