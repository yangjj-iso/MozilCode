# 02 - Agent 核心运行循环（超详细版）

> 本文档逐行拆解 `Agent.run()` 方法，把每一行代码做什么、何时触发什么、数据怎么流转全部讲清楚。

## 1. 全局视角：一次完整任务的生命周期

假设用户说"帮我读取 main.py 并解释代码"，以下是完整时间线：

```
时刻 0   用户发消息 → Daemon 收到 POST /api/task
时刻 1   Daemon 调用 agent.run(conversation)
时刻 2   Agent 初始化：加载环境上下文 + 记忆 → 触发 session_start Hook
时刻 3   ┌─ 第 1 轮迭代 ──────────────────────────────────────┐
         │ ① turn_start Hook                                   │
         │ ② 检查是否需要上下文压缩（不需要，刚开始）              │
         │ ③ pre_send Hook                                     │
         │ ④ 构建 system prompt + tools schema                 │
         │ ⑤ Layer 1: 对旧工具结果做预算截断                     │
         │ ⑥ 调用 LLM（流式）→ yield StreamText("我来读取…")    │
         │ ⑦ post_receive Hook                                 │
         │ ⑧ 记录 token 用量 → yield UsageEvent                │
         │ ⑨ LLM 返回 tool_call(ReadFile, {path:"main.py"})   │
         │ ⑩ pre_tool_use Hook                                 │
         │ ⑪ 权限检查 → allow（read 类别默认放行）               │
         │ ⑫ 执行 ReadFile → yield ToolResultEvent             │
         │ ⑬ post_tool_use Hook                                │
         │ ⑭ 工具结果写入 conversation.history                  │
         │ ⑮ turn_end Hook → yield TurnComplete(turn=1)        │
         └──────────────────────────────────────────────────────┘
时刻 4   ┌─ 第 2 轮迭代 ──────────────────────────────────────┐
         │ ①~⑥ 同上                                            │
         │ ⑦ LLM 看到文件内容，生成解释文本 → yield StreamText   │
         │ ⑧ LLM 没有返回 tool_call（任务完成）                   │
         │ ⑨ 记录最终回复到 conversation                         │
         │ ⑩ 后台触发记忆观察（asyncio.ensure_future）            │
         │ ⑪ 每 5 轮触发记忆提取                                 │
         │ ⑫ turn_end Hook + session_end Hook                  │
         │ ⑬ yield LoopComplete(total_turns=2) → 循环结束       │
         └──────────────────────────────────────────────────────┘
时刻 5   Daemon 收到 LoopComplete → 标记任务完成 → WebSocket 通知 GUI
```

## 2. run() 方法初始化阶段（循环之前）

```python
async def run(self, conversation: ConversationManager) -> AsyncIterator[AgentEvent]:
    self._current_conversation = conversation

    # 【步骤 1】构建环境上下文字符串
    env_context = build_environment_context(
        self.work_dir,           # 工作目录路径
        self.active_skills,      # 当前激活的技能 {name: prompt_body}
        self._skill_catalog,     # 可用技能目录文本
        self._agent_catalog,     # 可用子 Agent 目录文本
    )
    # env_context 是一段文本，包含：工作目录、操作系统、可用技能列表等
    # 它会被注入到对话开头，让 LLM 知道"我在什么环境下工作"

    # 【步骤 2】加载长期记忆
    memory_content = await self._load_memory_context(
        self._latest_user_query(conversation)  # 取最近一条用户消息作为查询
    )
    # memory_content 是一段文本，包含从记忆存储中检索到的相关信息
    # 例如："用户偏好用 Python 3.12"、"项目用 pytest 做测试"

    # 【步骤 3】把环境上下文和记忆注入到对话历史
    inject_agent_context(
        conversation,
        environment_context=env_context,
        instructions_content=self.instructions_content,  # 系统指令
        memory_content=memory_content,
    )
    # 这里调用 conversation.inject_environment() 和 inject_long_term_memory()
    # 它们会在对话开头插入 system 消息，但只插一次（用 env_injected / ltm_injected 标记）

    # 【步骤 4】触发 session_start 生命周期 Hook
    for he in await self._run_lifecycle_hook("session_start"):
        yield he
    # 如果用户配置了 event=session_start 的 Hook，此时会执行
    # Hook 的输出会被包装成 HookEvent yield 出去
```

### inject_agent_context 做了什么？

```python
def inject_agent_context(conversation, *, environment_context, instructions_content, memory_content):
    conversation.inject_environment(environment_context)
    # → 在 conversation.history 开头插入一条 user 消息：
    #   "## Environment\n工作目录: /project\n操作系统: Linux\n..."

    conversation.inject_long_term_memory(instructions_content, memory_content)
    # → 在 history 开头插入另一条 user 消息：
    #   "## Instructions\n{instructions_content}\n\n## Memory\n{memory_content}"
    # 这两条消息只在会话首次调用时注入，用 env_injected / ltm_injected 标记防止重复
```

## 3. 主循环结构

```python
    iteration = 0
    consecutive_unknown = 0          # 连续"未知工具"计数器
    output_recovery_state = OutputRecoveryState()  # 输出 token 超限恢复状态

    while True:
        iteration += 1
```

### 3.1 迭代上限检查

```python
        if iteration > self.max_iterations:  # 默认 50
            yield ErrorEvent(
                message=f"Agent reached maximum iterations ({self.max_iterations})"
            )
            break
```

**何时触发**：当迭代次数超过 `max_iterations`（默认 50）。防止 LLM 陷入无限循环（反复调用工具但不收敛）。

**数据流转**：yield `ErrorEvent` → 消费者收到 → 显示错误 → break 退出循环。

### 3.2 turn_start Hook

```python
        for he in await self._run_lifecycle_hook("turn_start"):
            yield he
```

**何时触发**：每轮迭代刚开始，在所有其他操作之前。

**调用链**：
```
_run_lifecycle_hook("turn_start")
  → run_lifecycle_hook(hook_engine, build_hook_context, drain_events, "turn_start")
    → hook_ctx = build_hook_context("turn_start")  # 构建 Hook 上下文
    → await hook_engine.run_hooks("turn_start", hook_ctx)
      → find_matching_hooks("turn_start", ctx)  # 找出 event="turn_start" 的 Hook
      → for hook in matched:
          → execute_action(hook.action, ctx)  # 执行 Hook 动作
          → _record_result(...)               # 结果存入 _notifications 队列
    → drain_events()  # 取出 _notifications 队列中的所有通知
      → hook_engine.drain_notifications()
      → 返回 list[HookNotification] → 转换为 list[HookEvent]
```

**典型用途**：在每轮开始时记录日志、准备数据。

### 3.3 注入外部通知

```python
        self._inject_external_notifications(conversation)
```

**何时触发**：每轮迭代，turn_start Hook 之后。

**做什么**：检查是否有来自 Teammate Agent 的消息或其他外部通知，如果有，注入为 `system_reminder`。

```python
def _inject_external_notifications(self, conversation):
    inject_external_notifications(
        conversation,
        team_name=self.team_name,
        team_manager=self._team_manager,
        agent_id=self.agent_id,
        notification_fn=self.notification_fn,  # 通常是 team_manager.drain_lead_mailbox
    )
    # 如果 notification_fn 返回 ["Teammate A 完成了代码审查", ...]
    # 则每条消息都会被 conversation.add_system_reminder() 注入
```

### 3.4 上下文压缩检查（Layer 2）

这是最复杂的部分之一，我单独用一整节讲。

```python
        # === 上下文压缩检查 ===
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
            conversation, self.client, self.context_window, self.session_dir,
            protocol=self.protocol,
            breaker=self.compact_breaker,
            recovery=self.recovery_state,
            tool_schemas=self.registry.get_all_schemas(self.protocol),
            transcript_path=self._transcript_path,
        )
```

**何时触发压缩**：每轮迭代都会检查。具体触发条件：

```python
def compute_compact_threshold(context_window, manual=False):
    effective = context_window - SUMMARY_OUTPUT_RESERVE  # 200000 - 20000 = 180000
    margin = AUTO_COMPACT_SAFETY_MARGIN  # 13000（自动）/ 3000（手动）
    return effective - margin  # 180000 - 13000 = 167000

def should_auto_compact(last_input_tokens, context_window):
    return last_input_tokens >= compute_compact_threshold(context_window)
    # 当 current_tokens >= 167000 时触发自动压缩
```

**current_tokens 怎么算的**：

```python
# ConversationManager.current_tokens()
def current_tokens(self):
    if self.baseline_tokens == 0:
        # 冷启动：纯字符估算
        return estimate_tokens(self.history)  # 总字符数 / 3.5
    # 有锚点：锚点内信任 API 数据 + 锚点后字符估算
    return self.baseline_tokens + estimate_tokens(self.history[self.anchor_count:])
```

**auto_compact 的返回值有三种可能**：

| 返回值类型 | 含义 | Agent 的反应 |
|-----------|------|-------------|
| `CompactEvent` | 压缩成功 | 重新注入环境+记忆，yield 成功通知 |
| `None`（且 compact_started=True） | 需要压缩但内容太少不值得摘要 | yield "暂未压缩"通知 |
| `str` | 压缩失败（错误信息） | yield ErrorEvent |

```python
        if isinstance(compact_result, CompactEvent):
            # 压缩成功了！重新注入环境上下文和记忆
            mem = await self._load_memory_context()
            after_tokens = reinject_after_compact(
                conversation,
                environment_context=env_context,
                instructions_content=self.instructions_content,
                memory_content=mem,
            )
            # reinject_after_compact 做了什么：
            # 1. 调用 inject_agent_context 重新注入环境+记忆
            #    （因为压缩替换了 history，之前的注入被丢了）
            # 2. 返回压缩后的 token 数

            yield compact_success_notification(compact_result, after_tokens)
            # → CompactNotification(before_tokens=180000, message="上下文已压缩（180,000 → 45,000 tokens）", after_tokens=45000)

            yield UsageEvent(
                input_tokens=self.total_input_tokens,
                output_tokens=self.total_output_tokens,
                context_tokens=after_tokens,
            )

        elif compact_result is None and compact_started:
            # 需要压缩，但前缀太小不值得摘要
            after_tokens = conversation.current_tokens()
            yield CompactNotification(
                before_tokens=current_tokens,
                message="上下文暂未压缩（近期内容不足以生成有效摘要）",
                after_tokens=after_tokens,
            )

        elif isinstance(compact_result, str):
            # 压缩出错了
            yield ErrorEvent(message=compact_result)
```

**auto_compact 内部流程详解**：

```python
async def auto_compact(conversation, client, context_window, session_dir, ...):
    threshold = compute_compact_threshold(context_window, manual=manual)
    current = conversation.current_tokens()

    # 条件 1：非手动模式且未达阈值 → 不压缩
    if not manual and current < threshold:
        return None

    # 条件 2：熔断器已打开 → 返回错误
    if not manual and breaker is not None and breaker.is_open():
        return "自动压缩已熔断（连续失败 3 次）"

    # 步骤 A：决定保留多少尾部消息原文
    keep_start = _compute_keep_start_index(conversation.history)
    # 从尾部向前遍历，保留近期的消息原文：
    # - 累计 token >= KEEP_RECENT_TOKENS(10000) 或消息数 >= MIN_KEEP_MESSAGES(5) 时停止
    # - 但累计不超过 KEEP_MAX_TOKENS(40000)
    # 然后调整 keep_start 确保 tool_use 和 tool_result 不被拆散

    to_summarize = conversation.history[:keep_start]  # 要摘要的旧消息
    keep_tail = conversation.history[keep_start:]      # 原样保留的近期消息

    # 条件 3：待摘要的前缀为空或太小（< 2000 tokens）→ 不压缩
    if keep_start <= 0 or _prefix_too_small_to_compact(to_summarize):
        return None

    # 步骤 B：构建摘要请求
    summary_conv = ConversationManager()
    summary_conv.history = [
        Message(role="user", content=SUMMARY_PROMPT),  # 摘要提示词
        *to_summarize,  # 要摘要的旧对话
        Message(role="user", content="请根据以上对话生成结构化摘要。记住：不要调用任何工具。"),
    ]

    # 步骤 C：调用 LLM 生成摘要（最多重试 3 次）
    for attempt in range(3):
        try:
            collected_text = ""
            async for event in client.stream(summary_conv, system=SUMMARY_PROMPT):
                if isinstance(event, TextDelta):
                    collected_text += event.text
            llm_output = collected_text
            break
        except Exception as e:
            if "prompt" in str(e) and "long" in str(e):
                # 摘要请求本身太长了！丢弃最早的 1/5 对话轮次，重试
                groups = _group_messages_by_turn(summary_conv.history[1:-1])
                drop_count = max(1, len(groups) // 5)
                summary_conv.history = [first] + groups[drop_count:] + [last]
                continue
            breaker.record_failure()
            return f"摘要生成失败: {e}"

    # 步骤 D：提取摘要（从 <summary> 标签中）
    summary = extract_summary(llm_output)

    # 步骤 E：构建恢复附件（最近读取的文件、技能调用快照）
    attachment = build_recovery_attachment(recovery, tool_schemas)

    # 步骤 F：重建对话历史 = 摘要消息 + 保留的尾部原文
    new_messages = build_compact_messages(summary, attachment=attachment, ...)
    new_messages = new_messages + list(keep_tail)

    # 步骤 G：替换历史 + 清理持久化的工具结果文件
    conversation.replace_history(new_messages)  # 同时清零 token 锚点
    cleanup_tool_results(session_dir)           # 删除旧的工具结果持久化文件

    breaker.record_success()
    return CompactEvent(before_tokens=before_tokens, boundary=CompactBoundary(summary, keep_tail))
```

### 3.5 pre_send Hook

```python
        for he in await self._run_lifecycle_hook("pre_send"):
            yield he
```

**何时触发**：每轮迭代，在上下文压缩之后、调用 LLM 之前。

**用途**：在发送给 LLM 之前做最后的准备，比如注入额外的上下文信息。

### 3.6 构建 system prompt 和注入 reminders

```python
        # 获取 Hook 产生的 prompt 消息（action.type == "prompt" 的 Hook 输出）
        hook_prompts = (
            self.hook_engine.get_prompt_messages() if self.hook_engine else None
        )
        # get_prompt_messages() 会取出并清空 _prompt_messages 队列
        # 这些消息会被拼接到 system prompt 中

        # 构建 system prompt
        system = build_system_prompt(
            hook_prompts=hook_prompts,
            coordinator_mode=self.coordinator_mode,
            agent_catalog=self._agent_catalog_list or None,
        )

        # 如果是 Plan 模式，注入计划相关的 reminder
        if self.plan_mode:
            plan_path = str(self._get_plan_path())
            if self.permission_checker:
                self.permission_checker.plan_file_path = plan_path
            plan_exists = self._get_plan_path().exists()
            plan_reminder = build_plan_mode_reminder(plan_path, plan_exists, iteration)
            conversation.add_system_reminder(plan_reminder)
            # 注入一条 system_reminder 告诉 LLM：
            # "你处于 Plan 模式，只能读取文件和写计划文件，不能修改其他文件"

        # 注入 Hook 的通知消息
        if self.hook_engine:
            for note in self.hook_engine.drain_notifications():
                conversation.add_system_reminder(
                    f"Hook [{note.hook_id}] {note.event}: {note.output}"
                )
        # drain_notifications() 取出并清空 _notifications 队列
        # 每个 Hook 执行的输出都会以 system_reminder 形式告诉 LLM

        # 注入延迟工具提醒
        inject_deferred_tool_reminder(
            conversation,
            self.registry.get_deferred_tool_names(),
        )
        # 如果有 should_defer=True 的工具（如 MCP 工具），注入提醒：
        # "The following deferred tools are available via ToolSearch..."
```

### 3.7 Layer 1: 工具结果预算

```python
        # 获取所有已启用工具的 JSON Schema
        tools = self.registry.get_all_schemas(self.protocol)

        # Layer 1: 对旧工具结果做预算截断
        api_conv, _ = prepare_api_conversation(
            conversation,
            self.session_dir,
            self.replacement_state,
        )
```

**何时触发**：每轮迭代，在调用 LLM 之前。

**做什么**：创建一个 `conversation` 的**副本**（`api_conv`），在副本上对旧的工具结果做截断处理。原始 `conversation` 不受影响。

```python
def prepare_api_conversation(conversation, session_dir, replacement_state):
    api_conversation, new_records = apply_tool_result_budget(
        conversation, session_dir, replacement_state,
    )
    # apply_tool_result_budget 做了什么：
    # 遍历 conversation.history 中的所有 tool_result：
    #   Pass 1（单条超限）：如果某个 tool_result.content > 50000 字符
    #     → 持久化到文件，替换为预览（前 2000 字符 + 文件路径）
    #   Pass 2（聚合超限）：如果所有 tool_result 总计 > 200000 字符
    #     → 对最旧的 KEEP_RECENT_TURNS(10) 轮之外的做截断
    #   Pass 3（陈旧裁剪）：对已经处理过的做 idempotent 检查
    # 返回一个新的 ConversationManager（不修改原始的）

    if new_records:
        append_replacement_records(session_dir, new_records)
        # 记录哪些 tool_result 被替换了，以便后续恢复

    return api_conversation, new_records
```

**关键设计**：`api_conv` 是副本，原始 `conversation` 不变。这意味着：
- LLM 看到的是截断后的版本（省 token）
- 但完整的历史记录保留在 `conversation` 中（用于后续压缩、持久化等）

### 3.8 调用 LLM（流式）

```python
        collector = StreamCollector()
        llm_stream = self.client.stream(api_conv, system=system, tools=tools)
        async for event in collector.consume(llm_stream):
            yield event

        response = collector.response
```

**数据流**：

```
api_conv (截断后的对话)  ──→  client.stream()  ──→  LLM API
                                                       │
                                                    流式返回
                                                       │
                                                       ▼
TextDelta("我来")  ──→  StreamCollector.consume()  ──→  yield StreamText("我来")
TextDelta("读取")  ──→                              ──→  yield StreamText("读取")
ToolCallComplete(ReadFile, {path:"main.py"})  ──→   ──→  yield ToolUseEvent(...)
StreamEnd(input_tokens=5000, output_tokens=50)  ──→  (存入 response，不 yield)
```

`StreamCollector` 一边吃事件一边累积，最终 `collector.response` 包含完整的：
- `response.text`: LLM 输出的完整文本
- `response.tool_calls`: LLM 请求调用的工具列表
- `response.thinking_blocks`: 思考过程
- `response.stop_reason`: 停止原因（"end_turn" / "tool_use" / "max_tokens"）
- `response.input_tokens` / `output_tokens`: token 用量

### 3.9 post_receive Hook

```python
        for he in await self._run_lifecycle_hook(
            "post_receive",
            message=response.text,  # 把 LLM 的回复文本传给 Hook
        ):
            yield he
```

**何时触发**：LLM 响应完整接收之后。

**用途**：对 LLM 的回复做后处理，比如日志记录、内容审查。

### 3.10 Token 用量统计

```python
        usage_update = accumulate_response_usage(
            UsageTotals(self.total_input_tokens, self.total_output_tokens),
            response,
        )
        self.total_input_tokens = usage_update.totals.input_tokens
        self.total_output_tokens = usage_update.totals.output_tokens
        yield usage_update.event
        # → yield UsageEvent(input_tokens=总计, output_tokens=总计, context_tokens=本轮)

        # 同时更新 conversation 的 token 锚点
        # 这发生在 accumulate_response_usage 内部：
        # conversation.record_usage_anchor(response.input_tokens, len(conversation.history))
```

**关键**：每次 LLM 调用后，用 API 返回的真实 token 数更新锚点。之后 `current_tokens()` 的估算就基于这个锚点。

### 3.11 输出 token 超限恢复

```python
        conv_thinking = response_thinking_blocks(response)

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
            continue  # 跳过本轮后续步骤，直接进入下一轮迭代
```

**何时触发**：当 `response.stop_reason == "max_tokens"`（LLM 输出被截断了）。

**恢复策略**（两阶段）：

```
第 1 次超限（state.max_tokens_escalated == False）:
  → 提升 max_output_tokens 到 64000（MAX_TOKENS_CEILING）
  → 把已输出的部分文本存入 conversation
  → 注入提醒："从你停止的地方继续，不要重复之前的内容"
  → yield RetryEvent → continue（重新调 LLM）

第 2~4 次超限（state.output_recoveries < 3）:
  → 把已输出的部分文本存入 conversation
  → 注入提醒："输出超限，把剩余工作拆成更小的步骤"
  → yield RetryEvent → continue

第 5 次超限:
  → 放弃恢复，正常处理（可能是不完整输出）
```

### 3.12 判断是否完成

```python
        if not response.tool_calls:
            # LLM 没有请求工具调用 → 任务完成
            add_final_response(conversation, response, thinking_blocks=conv_thinking)
            # 把 LLM 的最终文本回复 + thinking 存入 conversation.history

            # 后台触发记忆观察（不等它完成）
            if self.memory_hub:
                asyncio.ensure_future(
                    self._observe_memories(conversation, MEMORY_EVENT_TURN_COMPLETED)
                )

            self._loop_count += 1

            # 每 5 轮触发记忆提取
            if self._loop_count % MEMORY_EXTRACTION_INTERVAL == 0 and self.memory_hub:
                asyncio.ensure_future(self._extract_memories(conversation))
                # 让 LLM 从对话中提取值得长期记住的信息

            # turn_end + session_end Hook
            for he in await self._run_lifecycle_hook("turn_end"):
                yield he
            for he in await self._run_lifecycle_hook("session_end"):
                yield he

            # 快照文件历史
            snapshot_file_history(self.file_history, conversation, response.text)

            yield LoopComplete(total_turns=iteration)
            break  # 退出主循环
```

**何时触发**：LLM 返回的 `response.tool_calls` 为空列表，意味着 LLM 认为任务已完成，不需要再调用工具。

**数据流**：
1. 最终回复存入 `conversation.history`（作为 assistant 消息）
2. 后台异步触发记忆观察和提取（不阻塞）
3. 触发 `turn_end` 和 `session_end` Hook
4. yield `LoopComplete` → 消费者收到 → 标记任务完成
5. `break` 退出循环

### 3.13 工具调用阶段

如果 LLM 返回了 `tool_calls`（不为空），则进入工具执行阶段：

```python
        # 把 LLM 的回复（文本 + thinking + tool_calls）存入 conversation
        add_tool_call_response(conversation, response, thinking_blocks=conv_thinking)

        tool_results: list[ToolResultBlock] = []

        # 将工具调用分批
        batches = partition_tool_calls(response.tool_calls, self.registry)
```

**partition_tool_calls 做了什么**：

```python
def partition_tool_calls(tool_calls, registry):
    batches = []
    for tc in tool_calls:
        tool = registry.get(tc.tool_name)
        safe = (tool is not None
                and tool.is_concurrency_safe  # is_concurrency_safe=True
                and registry.is_enabled(tc.tool_name))

        if safe and batches and batches[-1].concurrent:
            batches[-1].calls.append(tc)  # 加入当前并发批次
        else:
            batches.append(ToolBatch(concurrent=safe, calls=[tc]))
            # 不安全的工具单独一批（串行执行）
    return batches
```

**分批规则**：
- `is_concurrency_safe=True`（只读工具如 ReadFile, Glob, Grep）→ 可以并发
- `is_concurrency_safe=False`（写工具如 WriteFile, 命令工具如 Bash）→ 串行

例如 LLM 同时请求 `[ReadFile(a), ReadFile(b), WriteFile(c), ReadFile(d)]`：
```
批次 1: [ReadFile(a), ReadFile(b)]  ← 并发
批次 2: [WriteFile(c)]              ← 串行
批次 3: [ReadFile(d)]               ← 并发（但只有一个，效果同串行）
```

### 3.14 并发批次执行

```python
        for batch in batches:
            if batch.concurrent and len(batch.calls) > 1:
                # === 并发执行路径 ===
                approved = []
                pre_failed = {}

                # 步骤 1: 逐个做 pre_tool_use Hook + 权限预检
                for tc in batch.calls:
                    # --- pre_tool_use Hook ---
                    hook_result = await run_pre_tool_hook(
                        hook_engine=self.hook_engine,
                        build_hook_context=self._build_hook_context,
                        infer_file_path=self._infer_file_path,
                        drain_hook_events=self._drain_hook_events,
                        tool_call=tc,
                    )
                    for he in hook_result.events:
                        yield he  # Hook 执行产生的事件

                    if hook_result.rejection is not None:
                        # Hook 拒绝了此工具调用！
                        pre_failed[tc.tool_id] = hook_rejected_result(
                            hook_result.rejection.reason
                        )
                        continue  # 跳过此工具，不执行

                    # --- 权限预检 ---
                    auth = None
                    async for item in self._authorize_tool(tc):
                        if isinstance(item, PermissionRequest):
                            yield item  # 需要用户确认！
                            # 此时 Agent 暂停，等待消费者调用 future.set_result()
                        else:
                            auth = item  # _AuthResult

                    if auth is None or not auth.approved:
                        pre_failed[tc.tool_id] = (
                            auth.error or ToolResult(output="Permission denied", is_error=True)
                        )
                        continue

                    approved.append(tc)  # 通过了 Hook + 权限

                # 步骤 2: 并行执行所有已批准的工具
                exec_results = {}
                if approved:
                    for br in await self._execute_batch_parallel(approved):
                        exec_results[br.tool_id] = br
                    # asyncio.gather 同时执行所有工具

                    # 步骤 3: 对每个已执行的工具做 post_tool_use Hook
                    for tc in approved:
                        for he in await run_post_tool_hook(...):
                            yield he

                # 步骤 4: 收集所有结果（包括失败和成功的）
                consecutive_unknown = 0
                for tc in batch.calls:
                    if tc.tool_id in pre_failed:
                        result = pre_failed[tc.tool_id]
                        elapsed = 0.0
                    else:
                        br = exec_results[tc.tool_id]
                        result = br.result
                        elapsed = br.elapsed

                    tool_results.append(tool_result_block(tc, result, self.session_dir))
                    yield tool_result_event(tc, result, elapsed)
```

### 3.15 串行批次执行

```python
            else:
                # === 串行执行路径 ===
                for tc in batch.calls:
                    result = None
                    elapsed = 0.0
                    is_unknown = False

                    # --- pre_tool_use Hook ---
                    hook_result = await run_pre_tool_hook(...)
                    for he in hook_result.events:
                        yield he
                    if hook_result.rejection is not None:
                        result = hook_rejected_result(hook_result.rejection.reason)
                        tool_results.append(tool_result_block(tc, result, ...))
                        yield tool_result_event(tc, result, 0.0)
                        continue  # 跳过此工具

                    # --- 执行工具（内部包含权限检查）---
                    async for item in self._execute_tool(tc):
                        if isinstance(item, (PermissionRequest, AskUserRequest)):
                            yield item  # 需要用户确认或回答问题
                        else:
                            result, elapsed, is_unknown = item
                            # result: ToolResult(output=..., is_error=...)
                            # elapsed: 执行耗时（秒）
                            # is_unknown: 是否是未知工具

                    # --- post_tool_use Hook ---
                    for he in await run_post_tool_hook(...):
                        yield he

                    tool_results.append(tool_result_block(tc, result, ...))
                    yield tool_result_event(tc, result, elapsed)
```

### 3.16 _execute_tool 内部流程

```python
    async def _execute_tool(self, tc):
        start = time.monotonic()

        # === 权限检查 ===
        auth = None
        async for item in self._authorize_tool(tc):
            if isinstance(item, PermissionRequest):
                yield item  # ← 此处 Agent 暂停！
                # 消费者收到 PermissionRequest 后弹出确认框
                # 用户点击后调用 future.set_result(PermissionResponse.ALLOW)
                # 然后 await future 返回，授权流程继续
            else:
                auth = item  # _AuthResult(approved=True/False)

        # 权限未通过
        if auth is None or not auth.approved:
            result = auth.error or ToolResult(output="Permission denied", is_error=True)
            yield result, elapsed, auth.is_unknown
            return  # 不执行工具

        # === 获取工具实例 ===
        tool = self.registry.get(tc.tool_name)
        if tool is None:
            yield ToolResult(output="unknown tool", is_error=True), elapsed, True
            return

        # === 参数校验 ===
        try:
            params = tool.params_model.model_validate(tc.arguments)
            # 用 Pydantic 模型校验参数
            # 例如 ReadFileParams(path="main.py", offset=0, limit=0)

            # === 特殊工具：AskUserQuestion ===
            if tc.tool_name == "AskUserQuestion":
                # 创建一个 Future 等待用户回答
                future = loop.create_future()
                yield AskUserRequest(questions=questions_data, future=future)
                # Agent 暂停，等用户回答
                answers = await asyncio.wait_for(future, timeout=300)
                # 5 分钟超时
                result = ToolResult(output=answers)

            # === 普通工具：执行 ===
            else:
                result = await tool.execute(params)
                # 例如：ReadFile.execute(params) → 读取文件内容 → ToolResult(output=文件内容)

        except ValidationError as e:
            result = ToolResult(output=f"参数校验错误: {e}", is_error=True)
        except Exception as e:
            result = ToolResult(output=f"工具执行错误: {e}", is_error=True)

        # === 记录恢复快照 ===
        self._snapshot_for_recovery(tc, result)
        # 如果是 ReadFile，记录文件路径和内容摘要到 recovery_state
        # 压缩后这些信息会被重新注入，让 LLM "记住"读过什么文件

        yield result, elapsed, False
```

### 3.17 工具执行后

```python
            # 连续未知工具检查
            if consecutive_unknown >= 3:
                yield ErrorEvent(
                    message="Agent terminated: too many consecutive unknown tool calls"
                )
                break
            # 防止 LLM 反复调用不存在的工具

            # 检查是否调用了 ExitPlanMode
            exit_plan_called = any(
                tc.tool_name == "ExitPlanMode" for tc in response.tool_calls
            )

            # 把所有工具结果写入 conversation
            conversation.add_tool_results_message(tool_results)
            # → 在 history 中添加一条 user 消息，包含 tool_results

            if exit_plan_called:
                yield TurnComplete(turn=iteration)
                yield LoopComplete(total_turns=iteration)
                break  # 退出 Plan 模式

            # turn_end Hook
            for he in await self._run_lifecycle_hook("turn_end"):
                yield he

            yield TurnComplete(turn=iteration)
            # → 消费者收到，知道一轮迭代完成了
            # 但循环不结束，进入下一轮
```

## 4. 完整时序图

```
用户消息 "帮我读取 main.py"
    │
    ▼
┌─ run() 初始化 ─────────────────────────────────────────────────┐
│  build_environment_context() → env_context                      │
│  _load_memory_context() → memory_content                        │
│  inject_agent_context() → conversation.history 注入环境+记忆      │
│  _run_lifecycle_hook("session_start") → yield HookEvent         │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 迭代 1 ────────────────────────────────────────────────────────┐
│                                                                  │
│  ① _run_lifecycle_hook("turn_start") → yield HookEvent          │
│                                                                  │
│  ② _inject_external_notifications() → 注入 Teammate 消息         │
│                                                                  │
│  ③ current_tokens = conversation.current_tokens()                │
│     should_auto_compact(5000, 200000) → False（不需要压缩）       │
│     auto_compact() → None                                        │
│                                                                  │
│  ④ _run_lifecycle_hook("pre_send") → yield HookEvent             │
│                                                                  │
│  ⑤ hook_prompts = hook_engine.get_prompt_messages()              │
│     system = build_system_prompt(hook_prompts, ...)              │
│     inject_deferred_tool_reminder() → 注入延迟工具提醒             │
│                                                                  │
│  ⑥ api_conv = prepare_api_conversation(conversation, ...)        │
│     → 创建副本，对旧工具结果做截断                                  │
│                                                                  │
│  ⑦ collector.consume(client.stream(api_conv, system, tools))     │
│     → yield StreamText("我来读取")                                │
│     → yield StreamText("main.py")                                │
│     → yield ToolUseEvent(ReadFile, {path:"main.py"})             │
│     response = collector.response                                │
│                                                                  │
│  ⑧ _run_lifecycle_hook("post_receive") → yield HookEvent        │
│                                                                  │
│  ⑨ accumulate_response_usage() → yield UsageEvent                │
│                                                                  │
│  ⑩ handle_output_token_limit() → stop_reason != "max_tokens"     │
│     → 不触发恢复                                                  │
│                                                                  │
│  ⑪ response.tool_calls 不为空 → 进入工具执行                      │
│     add_tool_call_response() → 存入 conversation                  │
│                                                                  │
│  ⑫ partition_tool_calls([ReadFile]) → [Batch(concurrent=True)]   │
│                                                                  │
│  ⑬ 并发路径（但只有1个调用）：                                      │
│     run_pre_tool_hook(ReadFile) → 无拒绝                          │
│     _authorize_tool(ReadFile):                                   │
│       permission_checker.check(ReadFile, {path:"main.py"}):      │
│         Layer 0: 不是 Plan 模式 → 跳过                            │
│         Layer 1: 不是 command 类别 → 跳过                          │
│         Layer 2: PathSandbox.check("main.py") → 在沙箱内 → OK     │
│         Layer 3: RuleEngine 匹配 → 无匹配                          │
│         Layer 4: mode_decide(DEFAULT, read) → "allow"             │
│         → Decision(effect="allow")                               │
│       → _AuthResult(approved=True) → 不需要 yield PermissionRequest│
│     _execute_single_tool_direct(ReadFile):                       │
│       tool.execute(ReadFileParams(path="main.py"))               │
│       → ToolResult(output="文件内容...")                           │
│     _snapshot_for_recovery(ReadFile, result)                     │
│       → recovery_state.file_reads.append(FileReadRecord(...))     │
│     run_post_tool_hook(ReadFile) → 无 Hook                        │
│     yield ToolResultEvent(ReadFile, output="文件内容...")          │
│                                                                  │
│  ⑭ consecutive_unknown = 0（ReadFile 是已知工具）                  │
│     conversation.add_tool_results_message([result])               │
│     → history 追加一条 user 消息，包含 tool_result                  │
│                                                                  │
│  ⑮ _run_lifecycle_hook("turn_end") → yield HookEvent             │
│     yield TurnComplete(turn=1)                                    │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼ (回到 while True，iteration=2)
┌─ 迭代 2 ────────────────────────────────────────────────────────┐
│                                                                  │
│  ①~⑩ 同上                                                       │
│                                                                  │
│  ⑪ response.tool_calls 为空 → 任务完成！                          │
│     add_final_response() → 存入 conversation                      │
│     asyncio.ensure_future(_observe_memories()) → 后台记忆观察      │
│     _loop_count=1, 1%5 != 0 → 不触发记忆提取                      │
│     _run_lifecycle_hook("turn_end") → yield HookEvent             │
│     _run_lifecycle_hook("session_end") → yield HookEvent          │
│     yield LoopComplete(total_turns=2)                             │
│     break ← 退出循环                                              │
└──────────────────────────────────────────────────────────────────┘
```

## 5. 所有 Hook 触发时机汇总

| Hook 事件 | 触发时机 | 在 run() 中的位置 | 可能的用途 |
|-----------|---------|-------------------|-----------|
| `session_start` | 会话开始，循环之前 | 初始化阶段最后 | 初始化环境 |
| `turn_start` | 每轮迭代最开始 | while 循环第一行 | 准备数据 |
| `pre_send` | 压缩检查后、调用 LLM 前 | 压缩之后 | 注入额外信息 |
| `post_receive` | LLM 响应完整接收后 | stream 结束后 | 日志、审查 |
| `pre_tool_use` | 每个工具执行前 | 工具执行阶段 | 拦截/拒绝工具 |
| `post_tool_use` | 每个工具执行后 | 工具执行阶段 | 代码格式化 |
| `turn_end` | 每轮迭代结束 | 循环最后 | 统计 |
| `session_end` | 会话结束（仅任务完成时） | LoopComplete 之前 | 清理 |

## 6. 所有 yield 事件汇总

| 事件 | 何时 yield | 消费者怎么处理 |
|------|-----------|--------------|
| `HookEvent` | Hook 执行后 | 显示 Hook 输出 |
| `CompactStarted` | 即将开始压缩时 | 显示"正在压缩" |
| `CompactNotification` | 压缩完成/跳过时 | 显示压缩结果 |
| `UsageEvent` | LLM 用量更新时 | 更新 token 显示 |
| `StreamText` | LLM 流式输出文本时 | 实时显示文本 |
| `ThinkingText` | LLM 流式输出思考时 | 显示思考过程 |
| `ToolUseEvent` | LLM 请求调用工具时 | 显示工具调用卡片 |
| `ToolResultEvent` | 工具执行完成时 | 更新工具卡片状态 |
| `PermissionRequest` | 权限检查为 "ask" 时 | 弹出确认框 |
| `AskUserRequest` | AskUserQuestion 工具时 | 弹出问题输入框 |
| `RetryEvent` | 输出超限恢复时 | 显示"正在重试" |
| `TurnComplete` | 每轮迭代结束时 | 更新轮次显示 |
| `LoopComplete` | 任务完成、循环退出时 | 标记任务完成 |
| `ErrorEvent` | 发生错误时 | 显示错误 |
