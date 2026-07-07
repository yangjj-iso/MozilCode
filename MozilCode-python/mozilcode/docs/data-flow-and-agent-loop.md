# MozilCode 数据传输与流程框架总结

本文总结当前项目里一次用户请求从 daemon/headless CLI 进入、经过多轮模型交互、触发工具调用、写回对话历史、最终收敛为答案的完整路径。重点覆盖三个功能面：

- 多轮对话功能
- 工具调用功能
- 单次任务循环处理功能

## 一、整体分层

当前代码可以按 6 层理解：

1. **入口层**
   - `mozilcode/__main__.py`：headless CLI 入口，负责读取配置、初始化 hooks，并执行 `-p` 非交互任务。
   - `mozilcode/daemon/server.py`：本地 daemon 入口，提供 HTTP/WebSocket API、会话管理和 A2A 桥接。

2. **对话状态层**
   - `mozilcode/conversation.py`：定义内部消息结构 `Message`、工具调用块 `ToolUseBlock`、工具结果块 `ToolResultBlock`，以及 `ConversationManager`。
   - 所有多轮上下文都落在 `ConversationManager.history` 里。

3. **模型适配层**
   - `mozilcode/serialization.py`：把内部 `Message` 序列化成 Anthropic、OpenAI Responses、OpenAI Chat Completions 三种协议需要的请求格式。
   - `mozilcode/client.py`：封装不同 provider，把各家 streaming 响应统一转成项目内部的 `StreamEvent`。

4. **Agent 编排层**
   - `mozilcode/agent.py`：核心循环。负责组装上下文、调用模型、收集模型输出、执行工具、把工具结果写回历史，并决定是否继续下一轮。

5. **工具层**
   - `mozilcode/tools/base.py`：工具基类、工具结果、streaming 事件类型。
   - `mozilcode/tools/registry.py`：`ToolRegistry`，负责工具注册、启停、schema 输出、延迟工具发现。
   - `mozilcode/tools/*.py`：内置工具，如 `ReadFile`、`WriteFile`、`EditFile`、`Bash`、`Glob`、`Grep`、`Agent`、`ToolSearch`、`AskUserQuestion`。
   - `mozilcode/mcp/*`：把 MCP server 暴露的工具包装成统一 `Tool`。

6. **上下文与持久化层**
   - `mozilcode/context/manager.py`：工具结果预算、大输出持久化、自动 compact、压缩恢复附件。
   - `mozilcode/memory/session.py`：会话 JSONL 持久化、恢复、compact boundary 记录。
   - `mozilcode/memory/*`：长期记忆加载、召回、抽取。
   - `mozilcode/memory/providers/*`：`MemoryHub` 和可插拔记忆 provider。

可以把主流程想成：

```text
用户输入
  -> daemon 客户端 / headless CLI
  -> ConversationManager.history
  -> Agent.run 或 Agent.run_to_completion
  -> serialization.py
  -> LLMClient.stream
  -> StreamCollector
  -> 如果无工具调用：写 assistant 消息并结束
  -> 如果有工具调用：执行 Tool
  -> 工具结果作为 user/tool_result 消息写回 history
  -> 下一轮模型调用
```

## 二、内部消息数据结构

项目内部不直接使用某一家模型 API 的消息格式，而是先抽象成自己的结构：

```python
@dataclass
class Message:
    role: str
    content: str
    tool_uses: list[ToolUseBlock]
    tool_results: list[ToolResultBlock]
    thinking_blocks: list[ThinkingBlock]
```

几个关键点：

- 普通用户输入：`Message(role="user", content="...")`
- 普通助手回复：`Message(role="assistant", content="...")`
- 模型发起工具调用：assistant 消息里带 `tool_uses`
- 工具执行结果：用一条 `role="user"` 且 `content=""`、`tool_results=[...]` 的消息表示
- 系统提醒不是单独 system role，而是包装成 user 消息：

```text
<system-reminder>
...
</system-reminder>
```

这种设计的好处是：Agent 主循环只处理统一的 `ConversationManager`，不同 provider 的 API 差异放到 `serialization.py` 里解决。

## 三、模型请求与响应的数据传输

### 1. 请求前序列化

`client.stream(...)` 之前，Agent 会调用：

```python
api_conv, new_records = apply_tool_result_budget(...)
llm_stream = self.client.stream(api_conv, system=system, tools=tools)
```

其中 `api_conv` 是发送给模型前经过预算处理的对话副本，原始 `conversation.history` 不会被直接裁剪。

`serialization.py` 会根据协议转换：

- Anthropic：
  - assistant 的 `tool_uses` 转为 `content` 里的 `tool_use` block
  - user 的 `tool_results` 转为 `tool_result` block
  - thinking block 会保留

- OpenAI Responses：
  - 工具调用转为 `function_call`
  - 工具结果转为 `function_call_output`

- OpenAI Chat Completions 兼容协议：
  - assistant 消息里放 `tool_calls`
  - 工具结果转为 `role="tool"` 消息
  - thinking block 跳过

### 2. 响应后统一成 StreamEvent

`client.py` 的每个 client 都把外部 streaming 事件转成内部事件：

- `TextDelta`：文本增量
- `ThinkingDelta` / `ThinkingComplete`：思考内容
- `ToolCallStart` / `ToolCallDelta` / `ToolCallComplete`：工具调用增量和完成事件
- `StreamEnd`：本次模型响应结束，携带 token 用量和停止原因

`agent.py` 里的 `StreamCollector` 一边把这些 `StreamEvent` 汇总成 `LLMResponse`，一边再转换成 daemon / headless CLI 可消费的 `AgentEvent`：

- 文本流：`StreamText`
- 思考流：`ThinkingText`
- 工具开始：`ToolUseEvent`
- 工具结果：`ToolResultEvent`
- 用量：`UsageEvent`
- 单轮结束：`TurnComplete`
- 整个任务结束：`LoopComplete`
- 权限请求：`PermissionRequest`
- compact 通知：`CompactNotification`

## 四、多轮对话功能

daemon 会话和 headless CLI 都通过同一个 `ConversationManager` 实例维持多轮上下文。

### 1. 用户输入进入系统

daemon 任务请求进入：

```text
POST /api/task
  -> DaemonServer.start_task
  -> Agent.run(conversation)
```

headless CLI 入口进入：

```text
mozilcode -p PROMPT
  -> _run_prompt
  -> Agent.run_to_completion
```

发送一条用户消息时会做几件事：

1. 异步预取相关长期记忆。
2. 把用户消息追加到 `conversation.history`。
3. 把用户消息追加到当前 session JSONL（daemon 会话）。
4. 注入 MCP instructions 和记忆召回结果。
5. 调用：

```python
async for event in self.agent.run(self.conversation):
    ...
```

### 2. Agent.run 的一轮处理

`Agent.run` 是交互式主循环。一次用户请求可能包含多次模型调用，因为模型可能先调用工具，再根据工具结果继续思考。

每一轮大致如下：

```text
turn_start hooks
  -> 读取团队 mailbox / 后台通知
  -> auto_compact 检查
  -> pre_send hooks
  -> 构建 system prompt
  -> plan mode reminder
  -> deferred tools reminder
  -> 获取当前可用 tool schemas
  -> apply_tool_result_budget
  -> client.stream(...)
  -> StreamCollector 汇总响应
  -> post_receive hooks
  -> 更新 token 用量
  -> 判断是否有工具调用
```

如果没有工具调用：

```text
assistant text 写入 conversation.history
  -> 可触发长期记忆抽取
  -> turn_end/session_end hooks
  -> file history snapshot
  -> LoopComplete
  -> 本次用户请求结束
```

如果有工具调用：

```text
assistant text + tool_uses 写入 conversation.history
  -> record_usage_anchor
  -> 执行工具
  -> tool_results 写入 conversation.history
  -> TurnComplete
  -> 下一轮模型调用
```

这里的“多轮”有两个层次：

- 用户层面的多轮：用户连续发多条消息，同一个 `ConversationManager.history` 持续增长。
- 单次任务内部的多轮：一次用户消息内部，模型可能经历 “模型 -> 工具 -> 模型 -> 工具 -> 模型最终答复”。

### 3. 会话保存和恢复

交互模式会创建 `SessionManager` 和当前 `Session`。消息会写入：

```text
.mozilcode/sessions/<session_id>.jsonl
.mozilcode/sessions/<session_id>.meta
```

写入格式不是直接 dump `Message`，而是转换成 `SessionRecord`：

- `user`
- `assistant`
- `tool_result`
- `compact_boundary`

恢复时，`SessionManager.resume` 会：

1. 读取 JSONL。
2. 如果存在 `compact_boundary`，只从最后一个 boundary 开始重放。
3. 校验工具调用链，避免孤立的 tool_use/tool_result。
4. 转回 `Message` 列表。
5. 用新的 `ConversationManager` 替换 daemon session 当前 conversation。

因此，长对话压缩后恢复不会把压缩前的完整前缀重新塞回上下文，而是恢复为“摘要 + 保留尾部 + 后续消息”。

## 五、工具调用功能

### 1. 工具注册和 schema 暴露

所有工具都继承 `Tool`：

```python
class Tool(ABC):
    name: str
    description: str
    params_model: type[BaseModel]
    category: Literal["read", "write", "command"]
    is_concurrency_safe: bool = False
    is_system_tool: bool = False
    should_defer: bool = False
```

`params_model` 是 Pydantic 模型，既用于生成 JSON schema，也用于执行前参数校验。

默认注册表由 `create_default_registry` 创建，默认工具包括：

- `ReadFile`
- `WriteFile`
- `EditFile`
- `Bash`
- `Glob`
- `Grep`

交互模式还会额外注册：

- `LoadSkill`
- `ToolSearch`
- `AskUserQuestion`
- `ExitPlanMode`
- `Agent`
- team/worktree 相关工具
- MCP 工具

工具 schema 在每轮模型调用前通过：

```python
tools = self.registry.get_all_schemas(self.protocol)
```

传给模型。

### 2. 延迟工具加载

部分工具设置了：

```python
should_defer = True
```

这些工具一开始不会把完整 schema 发给模型，而是在 system reminder 中提示：

```text
The following deferred tools are available via ToolSearch...
```

模型如果需要，先调用 `ToolSearch`：

- `query="select:AskUserQuestion"`：按名称加载指定工具
- 普通关键词：按名称和描述搜索

`ToolSearch` 找到后会 `mark_discovered`，之后 `get_all_schemas` 才会把这些工具 schema 暴露给模型。

### 3. 工具调用执行链

模型返回工具调用后，Agent 做这些步骤：

```text
ToolCallComplete
  -> ToolUseEvent 发给事件消费者
  -> assistant 消息写入 tool_uses
  -> partition_tool_calls 分批
  -> 执行权限检查 / hooks / 参数校验 / tool.execute
  -> ToolResultEvent 发给事件消费者
  -> ToolResultBlock 写回 history
  -> 下一轮模型读取工具结果
```

核心代码路径：

- `Agent.run`
- `partition_tool_calls`
- `Agent._execute_tool`
- `Tool.execute`

工具结果并不是直接返回给模型 API，而是先写成内部消息：

```python
conversation.add_tool_results_message(tool_results)
```

下一轮调用模型时，`serialization.py` 再把这些 tool result 转成对应 provider 的格式。

### 4. 并发工具执行

`partition_tool_calls` 会把相邻的、可并发的工具调用分到同一批：

```python
safe = tool is not None and tool.is_concurrency_safe and registry.is_enabled(tc.tool_name)
```

当前默认只读类工具里有并发安全标记，例如：

- `ReadFile`
- `Glob`
- `Grep`

并发批次走：

```python
Agent._execute_batch_parallel
```

非并发或写入/命令类工具按顺序执行。

### 5. 权限检查

交互式工具执行走 `PermissionChecker.check`，决策层级大致是：

1. Plan 模式例外：允许 `Agent`、`ToolSearch`、`AskUserQuestion`、`ExitPlanMode`，允许写计划文件。
2. 安全只读命令自动放行。
3. 危险命令检测，命中则拒绝。
4. 文件读写走路径沙箱，限制在项目目录和临时目录等允许范围。
5. 用户/项目/本地权限规则匹配。
6. 根据当前权限模式兜底：
   - `default`：读允许，写和命令询问
   - `acceptEdits`：读写允许，命令询问
   - `plan`：读允许，写和命令询问
   - `bypassPermissions`：读写命令都允许
   - `custom`：都询问
   - `dontAsk`：都允许
7. 如果结果是 `ask`，Agent 产生 `PermissionRequest`，由 daemon 客户端选择允许、拒绝或总是允许。

非交互式 `run_to_completion` 中，如果权限结果是 `ask` 且当前模式不是 `dontAsk`，会直接返回权限错误，因为它不能弹窗询问用户。

### 6. 大工具结果处理

工具输出可能很大，项目有两层保护：

1. 执行后立即处理：
   - `prepare_tool_result_content`
   - 超过 `SINGLE_RESULT_CHAR_LIMIT` 的结果写入 `.mozilcode/session/tool-results/<tool_use_id>.txt`
   - 对话里只保留预览和文件路径

2. 请求前统一预算：
   - `apply_tool_result_budget`
   - 单条超限持久化
   - 聚合超限时优先持久化最长结果
   - 陈旧工具结果裁剪
   - 替换决策写入 `replacement_records.jsonl`

这样可以避免工具输出把上下文窗口撑爆，同时让完整内容仍可通过文件读取找回。

## 六、单次任务循环处理功能

这里的“单次任务”不是指只调用一次模型，而是指给 Agent 一个任务字符串，让它自己循环到没有工具调用为止。

主要入口是：

```python
Agent.run_to_completion(task, conversation=None, event_callback=None)
```

使用场景：

- CLI 非交互模式：`mozilcode -p "..."`。
- 子 Agent 前台执行：`AgentTool` 中调用子 agent 的 `run_to_completion`。
- 后台任务：`TaskManager.launch` 创建 asyncio task，内部调用 `run_to_completion`。
- team teammate 的 in-process 执行。

### 1. 非交互 CLI 流程

`mozilcode/__main__.py` 里：

```text
main
  -> parse args
  -> load_config
  -> load_hooks
  -> 如果存在 -p
     -> _run_prompt(...)
```

`_run_prompt` 会初始化：

- provider client
- permission checker
- instructions
- default registry
- `ToolSearch`
- `Agent`
- `WorktreeManager`
- `TaskManager`
- `AgentTool`
- team 工具

然后执行：

```python
conv = ConversationManager()
last_result = await agent.run_to_completion(prompt, conv)
print(last_result)
```

### 2. run_to_completion 的循环

`run_to_completion` 和交互式 `run` 的核心逻辑相似，但它不向 daemon 事件流持续 yield `AgentEvent`。

每轮：

```text
如果有 task：写入 user message
  -> 构建 system prompt
  -> 获取 tool schemas
  -> for iteration in 1..max_iterations
      -> turn_start hooks
      -> mailbox / notifications
      -> auto_compact
      -> deferred tools reminder
      -> apply_tool_result_budget
      -> client.stream
      -> StreamCollector 消费完整响应
      -> 更新 token
      -> event_callback 可选通知 usage/text/tool_use
      -> 如果无工具调用：写 assistant，break
      -> 如果有工具调用：写 assistant tool_uses
      -> 顺序执行 _execute_tool_noninteractive
      -> 写 tool_results
      -> 下一轮
```

最后返回 `last_text`，也就是最近一次模型文本输出。

### 3. `run` 与 `run_to_completion` 的主要区别

| 对比点 | `Agent.run` | `Agent.run_to_completion` |
| --- | --- | --- |
| 返回方式 | async iterator，持续 yield `AgentEvent` | 返回最终文本 |
| 事件消费 | daemon/WebSocket 根据事件实时转发 | 只有可选 `event_callback` |
| 权限询问 | 可以 yield `PermissionRequest` 等待调用方响应 | 不能交互询问，ask 通常转为错误 |
| 工具执行 | 支持并发安全工具批量并发 | 当前实现中按工具顺序执行 |
| 会话保存 | daemon 在 `TurnComplete` / `LoopComplete` 增量保存 | 调用方自行决定是否保存 |
| 典型用途 | daemon 多轮任务 | CLI、子 Agent、后台任务 |

## 七、上下文压缩与长对话控制

长对话控制主要有两层。

### Layer 1：工具结果预算

每轮模型调用前都会执行：

```python
apply_tool_result_budget(conversation, session_dir, replacement_state)
```

它返回一个新的 `ConversationManager` 副本用于本次 API 请求，不直接改原始 conversation。

主要策略：

- 单条工具结果超过 `50_000` 字符，持久化到磁盘并替换为预览。
- 多条工具结果聚合超过 `200_000` 字符，优先持久化最长的结果。
- 旧 turn 中较长的工具结果会裁剪为短摘要。
- 已做过的替换决策保存在 `ContentReplacementState` 和 `replacement_records.jsonl`，保证后续请求稳定。

### Layer 2：自动 compact

每轮模型调用前，Agent 会调用：

```python
auto_compact(...)
```

触发条件是当前估算 token 接近 context window 阈值。压缩时：

1. 按尾部窗口策略保留最近消息原文。
2. 对较早前缀调用模型生成结构化摘要。
3. 附加恢复信息：
   - 最近读过的文件快照
   - 最近启用过的 skill 正文
   - 当前可用工具列表
4. 用“摘要消息 + 保留尾部原文”替换 `conversation.history`。
5. 清理工具结果临时目录。
6. 返回 `CompactEvent`，daemon 会把 `compact_boundary` 写入 session。

这保证了长对话可以继续推进，同时恢复时不会丢失压缩边界。

## 八、子 Agent 和后台任务

`Agent` 本身也是一个工具，工具名是 `Agent`。

模型调用 `Agent` 工具时，`AgentTool.execute` 会根据参数决定：

- 指定 `subagent_type`：加载预定义 agent definition。
- 不指定 `subagent_type`：如果开启 fork，则从父对话派生上下文。
- `run_in_background=True` 或 fork 模式：交给 `TaskManager.launch` 后台跑。
- 否则：前台同步调用子 agent 的 `run_to_completion`。
- 如果 agent definition 要求 worktree isolation，则创建独立 worktree 后执行。
- 如果提供 `team_name`，则作为 teammate 加入 team，可能在进程内、tmux 或 iTerm2 后端运行。

后台任务完成后，`TaskManager` 会把 task id 放进通知队列。daemon 轮询到完成任务后，把结果注入当前 conversation：

```text
<task-notification>
...
</task-notification>
```

随后 daemon 触发一次通知消息，让主 Agent 根据任务通知继续处理。

## 九、关键退出和保护条件

Agent 循环不会无限跑，主要保护包括：

- `max_iterations`：超过最大迭代次数产生 `ErrorEvent`。
- 连续 unknown tool 调用达到 3 次，终止。
- 模型返回 `max_tokens`：
  - 第一次把最大输出 token 升到 `MAX_TOKENS_CEILING` 并要求续写。
  - 后续最多做 `MAX_OUTPUT_TOKENS_RECOVERIES` 次恢复。
- Plan 模式下调用 `ExitPlanMode` 后，当前循环结束。
- compact 连续失败会打开 circuit breaker，停止自动 compact 并提示手动处理。

## 十、最核心的调用链速记

### daemon 多轮任务

```text
DaemonServer.start_task
  -> conversation.add_user_message
  -> session.append(user)
  -> Agent.run(conversation)
     -> auto_compact
     -> apply_tool_result_budget
     -> client.stream
     -> StreamCollector
     -> conversation.add_assistant_message
     -> execute tools if any
     -> conversation.add_tool_results_message
     -> repeat until no tool calls
  -> daemon stream routes consume AgentEvent
  -> session.append(new messages)
```

### 工具调用

```text
LLM emits tool call
  -> ToolCallComplete
  -> ToolUseEvent
  -> assistant message with ToolUseBlock
  -> PermissionChecker / hooks / Pydantic validation
  -> Tool.execute
  -> ToolResultEvent
  -> user message with ToolResultBlock
  -> next model turn sees tool result
```

### 非交互单次任务

```text
_run_prompt or AgentTool or TaskManager
  -> Agent.run_to_completion(task)
     -> add user task
     -> loop model/tool/model/tool...
     -> return final text when no tool calls
```

## 十一、读代码时建议优先追问的点

如果后续要深挖代码细节，建议按这个顺序追：

1. `mozilcode/agent.py::Agent.run`：最重要，决定一次请求如何循环。
2. `mozilcode/conversation.py`：理解内部消息结构。
3. `mozilcode/serialization.py`：理解内部消息怎样映射到各家模型 API。
4. `mozilcode/client.py`：理解 streaming 响应怎样归一化。
5. `mozilcode/tools/registry.py`、`mozilcode/tools/__init__.py` 和 `mozilcode/tools/base.py`：理解工具注册、默认工具装配和 schema。
6. `mozilcode/permissions/checker.py`：理解工具调用安全边界。
7. `mozilcode/context/manager.py`：理解长对话、工具大输出、compact。
8. `mozilcode/memory/session.py`：理解多轮会话如何持久化和恢复。
