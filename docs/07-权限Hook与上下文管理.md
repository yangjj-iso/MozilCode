# 07 - 权限、Hook 与上下文管理（超详细版）

> 本文档把三大子系统——权限检查、Hook 引擎、上下文管理——的每一步触发条件、数据流转、判断逻辑全部讲透。  
> 若要从「系统如何整体驾驭 Agent」视角学习（圈地/放行/人在回路/取消/熔断），先读 [11-驾驭工程](./11-驾驭工程.md)。

---

## 第一部分：权限系统

### 1. 权限检查何时触发？

权限检查发生在**每个工具执行之前**。无论是并发批次还是串行批次，每个工具都必须通过权限检查才能执行。

```
LLM 返回 tool_call(WriteFile, {path:"config.py", content:"..."})
    │
    ▼
Agent._execute_tool(tc) 或 Agent._authorize_tool(tc)
    │
    ▼
authorize_tool_call(registry, permission_checker, tool_call, ...)
    │
    ▼
permission_checker.check(tool, arguments) → Decision(effect, reason)
    │
    ├── effect="allow" → 直接执行工具
    ├── effect="deny"  → 返回错误，不执行
    └── effect="ask"   → yield PermissionRequest → 等待用户确认
```

### 2. authorize_tool_call 的完整流程

```python
async def authorize_tool_call(*, registry, permission_checker, tool_call, permission_description):
    # === 前置检查 1：工具是否存在 ===
    tool = registry.get(tool_call.tool_name)
    if tool is None:
        yield _AuthResult(
            approved=False,
            error=ToolResult(output=f"Error: unknown tool '{tool_call.tool_name}'", is_error=True),
            is_unknown=True,  # 标记为"未知工具"，影响 consecutive_unknown 计数
        )
        return

    # === 前置检查 2：工具是否已启用 ===
    if not registry.is_enabled(tool_call.tool_name):
        yield _AuthResult(
            approved=False,
            error=ToolResult(output=f"Error: tool '{tool_call.tool_name}' is disabled", is_error=True),
        )
        return

    # === 核心权限检查 ===
    if permission_checker:
        decision = permission_checker.check(tool, tool_call.arguments)
        # ↓↓↓ 这里进入五层检查链，见下文 ↓↓↓

        # --- 决策：deny ---
        if decision.effect == "deny":
            yield _AuthResult(
                approved=False,
                error=ToolResult(output=f"Permission denied: {decision.reason}", is_error=True),
            )
            return  # 不执行工具

        # --- 决策：ask ---
        if decision.effect == "ask":
            # 创建一个 Future，用于等待用户回复
            loop = asyncio.get_running_loop()
            future = loop.create_future()

            # yield PermissionRequest 给消费者
            yield PermissionRequest(
                tool_name=tool_call.tool_name,
                description=permission_description,
                future=future,
            )
            # ★★★ 此时 Agent 在这里暂停 ★★★
            # 消费者收到 PermissionRequest 后弹出确认框
            # 用户点击"允许"/"拒绝"/"始终允许"
            # 消费者调用 future.set_result(PermissionResponse.ALLOW)
            # 然后 await future 返回，继续执行

            response = await future  # 等待用户决策

            # 用户拒绝
            if response == PermissionResponse.DENY:
                yield _AuthResult(
                    approved=False,
                    error=ToolResult(output="Permission denied: 用户拒绝了此操作", is_error=True),
                )
                return

            # 用户选择"始终允许" → 添加持久化规则
            if response == PermissionResponse.ALLOW_ALWAYS:
                content = extract_content(tool_call.tool_name, tool_call.arguments)
                pattern = f"{content[:60]}*" if len(content) > 60 else f"{content}*"
                rule = Rule(tool_name=tool_call.tool_name, pattern=pattern, effect="allow")
                permission_checker.rule_engine.append_local_rule(rule)
                # 规则写入 .mozilcode/permissions.local.yaml
                # 下次相同工具+内容会命中 Layer 3 规则引擎，直接 allow，不再 ask

    # --- 决策：allow 或用户已确认 ---
    yield _AuthResult(approved=True, error=None)
    # → Agent 继续执行工具
```

### 3. 五层权限检查链（PermissionChecker.check）

```python
def check(self, tool: Tool, arguments: dict) -> Decision:
    content = extract_content(tool.name, arguments)
    # extract_content 从参数中提取"内容"用于规则匹配
    # 例如 WriteFile → arguments["content"]
    #      Bash      → arguments["command"]
    #      ReadFile  → arguments["path"]

    # === Layer 0: Plan 模式例外 ===
    decision = self._check_plan_mode(tool, content)
    if decision is not None:
        return decision

    # === Layer 1: 命令安全检查 ===
    decision = self._check_command_safety(tool, content)
    if decision is not None:
        return decision

    # === Layer 2: 路径沙箱 ===
    decision = self._check_path_sandbox(tool, arguments)
    if decision is not None:
        return decision

    # === Layer 3: 规则引擎 ===
    decision = self._check_rules(tool, content)
    if decision is not None:
        return decision

    # === Layer 4: 权限模式兜底 ===
    decision = self._check_mode_fallback(tool)
    if decision is not None:
        return decision

    # === Layer 5: 人工确认 ===
    return Decision(effect="ask", reason="需要用户确认")
```

#### Layer 0: Plan 模式

```python
def _check_plan_mode(self, tool, content) -> Decision | None:
    if self.mode != PermissionMode.PLAN:
        return None  # 不是 Plan 模式，跳过

    # Plan 模式下允许的工具
    if tool.name in _PLAN_MODE_ALLOWED_TOOLS:  # {"Agent", "ToolSearch", "AskUserQuestion", "ExitPlanMode"}
        return Decision(effect="allow", reason="Plan mode: allowed tool")

    # Plan 模式下只允许写计划文件
    if tool.name in ("WriteFile", "EditFile") and content:
        if self._is_plan_file(content):  # 检查路径是否是 .mozilcode/plans/ 目录下
            ok, reason = self.sandbox.check(content)
            if not ok:
                return Decision(effect="deny", reason=f"路径沙箱拦截: {reason}")
            return Decision(effect="allow", reason="Plan mode: plan file write")

    return None  # 其他情况继续下一层
```

**何时触发**：`permission_mode == PLAN` 时。

**效果**：Plan 模式下只能读取文件、写计划文件、调用 Agent/ToolSearch/AskUserQuestion/ExitPlanMode。

#### Layer 1: 命令安全检查

```python
def _check_command_safety(self, tool, content) -> Decision | None:
    if tool.category != "command":
        return None  # 不是命令工具，跳过

    # 1b: 安全的只读命令（自动放行）
    if is_safe_command(content or ""):
        return Decision(effect="allow", reason="Safe read-only command")
    # is_safe_command 检查命令是否在白名单中
    # 例如: "ls", "cat", "git status", "pwd" 等

    # 1c: 危险命令黑名单（仅 Bash）
    hit, reason = self.detector.detect(content)
    if hit:
        return Decision(effect="deny", reason=f"危险命令拦截: {reason}")
    # DangerousCommandDetector 检查命令是否匹配危险模式
    # 例如: "rm -rf /", "mkfs", "dd if=", "> /dev/sda" 等

    return None  # 不是安全命令也不是危险命令，继续下一层
```

**何时触发**：`tool.category == "command"`（即 Bash 工具）。

**判断顺序**：
1. 先检查是否是安全的只读命令 → allow
2. 再检查是否是危险命令 → deny
3. 都不是 → 继续下一层

#### Layer 2: 路径沙箱

```python
def _check_path_sandbox(self, tool, arguments) -> Decision | None:
    if tool.category not in ("read", "write"):
        return None  # 不是文件操作工具，跳过

    target_path = extract_sandbox_path(tool.name, arguments)
    # 从参数中提取文件路径
    # 例如 ReadFile → arguments["path"]
    #      WriteFile → arguments["path"]
    #      Glob → arguments["pattern"]
    if target_path is None:
        return None  # 没有路径参数，跳过

    if not target_path.strip():
        return Decision(effect="deny", reason="路径沙箱拦截: 缺少路径参数")

    ok, reason = self.sandbox.check(target_path)
    # PathSandbox.check 做了什么：
    #   resolved = Path(target_path).resolve()  # 解析绝对路径
    #   resolved.relative_to(self._root)  # 检查是否在 work_dir 下
    #   如果不在 → return False, "路径不在工作目录内"
    #   如果在 → return True, ""
    if not ok:
        return Decision(effect="deny", reason=f"路径沙箱拦截: {reason}")

    return None  # 路径在沙箱内，继续下一层
```

**何时触发**：`tool.category in ("read", "write")`（即文件操作工具）。

**效果**：确保所有文件操作都在工作目录内，防止 LLM 读取/修改工作目录外的文件（如 `~/.ssh/`、`/etc/passwd` 等）。

#### Layer 3: 规则引擎

```python
def _check_rules(self, tool, content) -> Decision | None:
    rule_result = self.rule_engine.evaluate(tool.name, content)
    # RuleEngine 按顺序检查所有规则：
    #   for rule in self._rules:
    #     if rule.tool_name == tool_name and fnmatch(content, rule.pattern):
    #       return rule.effect  # "allow" / "deny" / None
    #   return None  # 无匹配

    if rule_result == "allow":
        return Decision(effect="allow", reason="权限规则放行")
    if rule_result == "deny":
        return Decision(effect="deny", reason="权限规则拒绝")
    return None  # 无匹配规则，继续下一层
```

**何时触发**：所有工具（Layer 0-2 没有返回决策的）。

**规则来源**（按优先级）：

```yaml
# ~/.mozilcode/permissions.yaml（用户级）
rules:
  - tool: Bash
    pattern: "git *"
    decision: allow

# .mozilcode/permissions.yaml（项目级）
rules:
  - tool: WriteFile
    pattern: "*.py"
    decision: allow

# .mozilcode/permissions.local.yaml（本地级，用户"始终允许"后自动生成）
rules:
  - tool: Bash
    pattern: "npm *"
    decision: allow
```

**ALLOW_ALWAYS 的效果**：当用户点击"始终允许"时，系统自动在 `permissions.local.yaml` 中添加一条规则。下次相同工具+相似内容会命中 Layer 3 直接 allow，不再弹出确认框。

#### Layer 4: 权限模式兜底

```python
def _check_mode_fallback(self, tool) -> Decision | None:
    effect = mode_decide(self.mode, tool.category)
    # 查表：
    # _MODE_MATRIX = {
    #     DEFAULT:      {"read": "allow", "write": "ask",    "command": "ask"},
    #     ACCEPT_EDITS: {"read": "allow", "write": "allow",  "command": "ask"},
    #     PLAN:         {"read": "allow", "write": "ask",    "command": "ask"},
    #     BYPASS:       {"read": "allow", "write": "allow",  "command": "allow"},
    #     CUSTOM:       {"read": "ask",   "write": "ask",    "command": "ask"},
    #     DONT_ASK:     {"read": "allow", "write": "allow",  "command": "allow"},
    # }

    if effect == "allow":
        return Decision(effect="allow", reason=f"权限模式 {self.mode.value} 放行")
    if effect == "deny":
        return Decision(effect="deny", reason=f"权限模式 {self.mode.value} 拒绝")
    return None  # effect == "ask"，继续下一层
```

**何时触发**：Layer 0-3 都没有返回决策时。

**关键**：这是最常见的决策来源。在 DEFAULT 模式下：
- read 类工具（ReadFile, Glob, Grep）→ allow（自动放行）
- write 类工具（WriteFile, EditFile）→ ask（需要确认）
- command 类工具（Bash）→ ask（需要确认）

#### Layer 5: 人工确认

```python
    return Decision(effect="ask", reason="需要用户确认")
```

**何时触发**：Layer 4 返回 `None`（即 `effect == "ask"`）。

**效果**：`authorize_tool_call` 收到 `ask` 后 yield `PermissionRequest`，Agent 暂停等待用户决策。

### 4. 完整判断流程图

以 `Bash(command="npm install")` 在 `DEFAULT` 模式下为例：

```
extract_content("Bash", {"command": "npm install"}) → "npm install"

Layer 0: mode != PLAN → 跳过
Layer 1: tool.category == "command"
  ├─ is_safe_command("npm install")? → False（不在白名单）
  ├─ DangerousCommandDetector.detect("npm install")? → False（不是危险命令）
  └─ 返回 None → 继续
Layer 2: tool.category != ("read", "write") → 跳过
Layer 3: RuleEngine.evaluate("Bash", "npm install")
  ├─ 检查所有规则...
  ├─ 如果有规则 {tool: "Bash", pattern: "npm *", decision: "allow"} → allow！
  └─ 如果没有匹配规则 → 返回 None → 继续
Layer 4: mode_decide(DEFAULT, "command") → "ask" → 返回 None → 继续
Layer 5: 返回 Decision(effect="ask", reason="需要用户确认")

→ authorize_tool_call 收到 "ask"
→ yield PermissionRequest(tool_name="Bash", description="执行命令: npm install", future=...)
→ Agent 暂停，等待用户点击

用户点击"始终允许" → future.set_result(ALLOW_ALWAYS)
→ authorize_tool_call 继续
→ 添加规则 {tool: "Bash", pattern: "npm install*", effect: "allow"} 到 permissions.local.yaml
→ yield _AuthResult(approved=True)
→ Agent 继续执行 Bash 工具
```

### 5. 权限确认的异步交互

权限确认是一个**异步暂停-恢复**的过程：

```
Agent 主循环                    消费者 (Daemon)              用户 (GUI)
    │                               │                          │
    │ yield PermissionRequest       │                          │
    │──────────────────────────────→│                          │
    │   (包含 future)               │                          │
    │                               │ WebSocket 推送            │
    │ ★ Agent 暂停 ★                │─────────────────────────→│
    │   (await future)              │                          │
    │                               │                    弹出确认框
    │                               │                          │
    │                               │                 用户点击"允许"
    │                               │←─────────────────────────│
    │                               │ POST /api/permission/sid │
    │                               │   {request_id, response} │
    │                               │                          │
    │                               │ future.set_result(ALLOW) │
    │←──────────────────────────────│                          │
    │   future 返回                 │                          │
    │ ★ Agent 恢复 ★                │                          │
    │                               │                          │
    │ 继续执行工具                   │                          │
```

---

## 第二部分：Hook 引擎

### 1. Hook 何时触发？

Hook 在 Agent 运行周期的特定时刻触发。有两类 Hook：

| 类型 | 触发方式 | 特点 |
|------|---------|------|
| 生命周期 Hook | `_run_lifecycle_hook(event)` | 在循环的特定位置自动触发 |
| 工具 Hook | `run_pre_tool_hook` / `run_post_tool_hook` | 在工具执行前后触发 |

### 2. 生命周期 Hook 的完整时序

```
run() 开始
    │
    ├── session_start  ← 仅一次，循环之前
    │
    └── while True:
            ├── turn_start     ← 每轮迭代开始
            │
            ├── (上下文压缩检查)
            ├── pre_send       ← 压缩后、调 LLM 前
            │
            ├── (调用 LLM)
            ├── post_receive   ← LLM 响应后
            │
            ├── (工具执行)
            │   ├── pre_tool_use   ← 每个工具执行前
            │   └── post_tool_use  ← 每个工具执行后
            │
            ├── turn_end       ← 每轮迭代结束
            │
            └── 如果任务完成:
                    ├── turn_end    ← 再触发一次
                    └── session_end ← 仅一次，退出前
```

### 3. Hook 匹配机制

```python
def find_matching_hooks(self, event: str, ctx: HookContext) -> list[Hook]:
    matched = []
    for hook in self.hooks:
        # 条件 1：事件名匹配
        if hook.event != event:
            continue

        # 条件 2：Hook 是否应该运行（频率控制）
        if not hook.should_run():
            continue
        # should_run() 检查 Hook 的执行限制
        # 例如 once=True 的 Hook 只执行一次

        # 条件 3：条件表达式匹配
        if hook.condition is not None and not hook.condition.evaluate(ctx):
            continue
        # condition 是一个表达式，例如：
        #   tool_name == "WriteFile"
        #   file_path matches "*.py"
        # 如果条件不满足，跳过此 Hook

        matched.append(hook)
    return matched
```

### 4. Hook 执行机制

```python
async def run_hooks(self, event: str, ctx: HookContext) -> None:
    matched = self.find_matching_hooks(event, ctx)
    for hook in matched:
        hook.mark_executed()  # 标记为已执行（用于 once 控制）

        if hook.async_exec:
            self._schedule_background_hook(hook, ctx)
            # 异步执行：创建 asyncio.Task，不等待完成
            # Agent 主循环不阻塞，继续往下走
        else:
            await self._run_single(hook, ctx)
            # 同步执行：等待 Hook 完成后才继续
```

### 5. pre_tool_use Hook 的特殊能力——拒绝工具

```python
async def run_pre_tool_hooks(self, ctx: HookContext) -> ToolRejectedError | None:
    matched = self.find_matching_hooks("pre_tool_use", ctx)
    for hook in matched:
        hook.mark_executed()
        try:
            result = await execute_action(hook.action, ctx, self.agent_runner)
            self._record_result(hook, "pre_tool_use", result)

            # ★ 如果 Hook 配置了 reject=True，返回拒绝错误 ★
            if hook.reject:
                return ToolRejectedError(
                    tool=ctx.tool_name,
                    reason=result.output,  # Hook 的输出作为拒绝理由
                    hook_id=hook.id,
                )
        except Exception as e:
            self._record_error(hook, "pre_tool_use", e)
    return None  # 没有拒绝
```

**何时触发**：每个工具执行之前（在权限检查之前）。

**效果**：如果 Hook 返回 `ToolRejectedError`，工具不会被执行，Agent 直接生成一个 `ToolResult(output="Hook 拒绝: ...", is_error=True)` 作为工具结果。

```yaml
# Hook 拒绝工具的配置示例
hooks:
  - id: block-prod-write
    event: pre_tool_use
    condition:
      tool_name: WriteFile
      file_path: "*/prod/*"     # 阻止写 prod 目录
    reject: true                 # ★ 拒绝执行
    action:
      type: command
      command: "echo '禁止写入生产目录'"
```

### 6. Hook 的通知和 Prompt 注入机制

Hook 执行后有两种输出方式：

#### 6.1 通知（Notification）

```python
def _record_result(self, hook, event, result):
    self._notifications.append(HookNotification(
        hook_id=hook.id,
        event=event,
        output=result.output,
        success=result.success,
    ))
```

通知会在**下一轮迭代**中通过 `drain_notifications()` 取出，注入为 `system_reminder`：

```python
# Agent.run() 主循环中
if self.hook_engine:
    for note in self.hook_engine.drain_notifications():
        conversation.add_system_reminder(
            f"Hook [{note.hook_id}] {note.event}: {note.output}"
        )
# → LLM 在下一轮会看到："Hook [auto-format] post_tool_use: 格式化完成"
```

#### 6.2 Prompt 消息

```python
async def _run_single(self, hook, ctx):
    result = await execute_action(hook.action, ctx, self.agent_runner)

    # 如果 action.type == "prompt"，输出会被注入到 system prompt
    if hook.action.type == "prompt" and result.success:
        self._prompt_messages.append(result.output)

    self._record_result(hook, hook.event, result)
```

Prompt 消息在**同一轮迭代**中被取出，拼接到 system prompt：

```python
# Agent.run() 主循环中
hook_prompts = self.hook_engine.get_prompt_messages() if self.hook_engine else None
system = build_system_prompt(hook_prompts=hook_prompts, ...)
# get_prompt_messages() 取出并清空 _prompt_messages
# build_system_prompt 会把 hook_prompts 拼接到 system prompt 末尾
```

### 7. Hook 的数据流总结

```
Hook 配置 (YAML)
    │
    ▼
HookEngine.__init__(hooks=[Hook(...), ...])
    │
    ▼
Agent.run() 触发 _run_lifecycle_hook("turn_start")
    │
    ├── find_matching_hooks("turn_start", ctx)
    │     └── 检查 event + should_run + condition
    │
    ├── 执行匹配的 Hook
    │     └── execute_action(hook.action, ctx)
    │         ├── type="command" → 执行 shell 命令
    │         ├── type="prompt"  → 输出存入 _prompt_messages
    │         └── type="agent"   → 启动子 Agent
    │
    ├── 结果存入 _notifications
    │
    └── drain_events() → 返回 list[HookEvent]
        │
        ▼
Agent yield HookEvent → 消费者显示

下一轮迭代：
    ├── get_prompt_messages() → 拼入 system prompt
    └── drain_notifications() → 注入 system_reminder
```

---

## 第三部分：上下文管理

### 1. 为什么需要上下文管理？

LLM 有上下文窗口限制（如 200K tokens）。随着对话变长，会逼近上限。如果不处理：
1. LLM API 会报错（prompt too long）
2. 费用飙升（按 token 计费）
3. 响应变慢（处理更多 token）

上下文管理通过两个层面优化：

| 层 | 名称 | 何时触发 | 做什么 | 操作对象 |
|----|------|---------|--------|---------|
| Layer 1 | 工具结果预算 | **每轮** LLM 调用前 | 截断旧工具结果 | api_conv（副本） |
| Layer 2 | 自动压缩 | **每轮**检查，达阈值时执行 | LLM 摘要旧对话 | conversation（原始） |

### 2. Layer 1: 工具结果预算

#### 2.1 何时触发

```python
# Agent.run() 主循环中，每轮都会执行
api_conv, _ = prepare_api_conversation(
    conversation,
    self.session_dir,
    self.replacement_state,
)
```

**触发条件**：每轮 LLM 调用前都会执行。

#### 2.2 做了什么

```python
def apply_tool_result_budget(conversation, session_dir, state):
    new_history = []

    for msg in conversation.history:
        if not msg.tool_results:
            new_history.append(msg)  # 不是工具结果消息，原样保留
            continue

        decisions = {}
        for tr in msg.tool_results:
            # 如果已经替换过（state 中有记录），直接使用替换后的版本
            if tr.tool_use_id in state.replacements:
                decisions[tr.tool_use_id] = state.replacements[tr.tool_use_id]
                continue

            # Pass 1: 单条超限（> 50,000 字符）
            if len(tr.content) > SINGLE_RESULT_CHAR_LIMIT:
                file_path = persist_tool_result(tr.tool_use_id, tr.content, session_dir)
                # 把完整内容写入文件：.mozilcode/session/tool-results/{tool_use_id}.txt
                replacement = make_persisted_preview(tr.content, file_path)
                # 生成预览：<persisted-output> 前2000字符 + 文件路径 </persisted-output>
                decisions[tr.tool_use_id] = replacement
                state.replacements[tr.tool_use_id] = replacement
                state.seen_ids.add(tr.tool_use_id)

            # Pass 2: 已处理过的不再处理
            elif tr.tool_use_id not in state.seen_ids:
                decisions[tr.tool_use_id] = tr.content  # 原样保留
                state.seen_ids.add(tr.tool_use_id)

        # Pass 3: 聚合超限检查
        total_chars = sum(len(decisions.get(tr.tool_use_id, tr.content)) for ...)
        if total_chars > AGGREGATE_CHAR_LIMIT:  # 200,000
            # 对超过 KEEP_RECENT_TURNS(10) 轮之外的旧结果做截断
            for tr in msg.tool_results:
                if tr.tool_use_id in state.seen_ids and tr.tool_use_id not in recent_ids:
                    content = decisions.get(tr.tool_use_id, tr.content)
                    if len(content) > OLD_RESULT_SNIP_CHARS:  # 2,000
                        decisions[tr.tool_use_id] = content[:OLD_RESULT_SNIP_CHARS] + "\n... <snipped>"

        # 构建新消息（替换 tool_results 的 content）
        new_msg = Message(...)
        new_history.append(new_msg)

    return ConversationManager(history=new_history, ...), new_records
```

#### 2.3 关键设计：不修改原始 conversation

```
conversation (原始)               api_conv (副本)
┌────────────────────┐           ┌────────────────────┐
│ Message(user)      │           │ Message(user)      │
│  tool_results:     │           │  tool_results:     │
│    [content: 80KB] │  ──copy──→│    [content: 2KB   │ ← 截断后的版本
│                    │           │     + 文件路径]    │
└────────────────────┘           └────────────────────┘
     ↑                                   ↑
  保留完整内容                       发给 LLM
  （用于持久化、                      （省 token）
   压缩等）
```

### 3. Layer 2: 自动压缩

#### 3.1 何时触发

```python
# 每轮迭代都会检查
current_tokens = conversation.current_tokens()
compact_threshold = compute_compact_threshold(self.context_window)
# = 200000 - 20000(SUMMARY_OUTPUT_RESERVE) - 13000(AUTO_COMPACT_SAFETY_MARGIN)
# = 167000

should_auto_compact(current_tokens, self.context_window)
# = current_tokens >= 167000
```

**触发条件**：`current_tokens >= context_window - 33000`

为什么留 33000 的余量？
- `SUMMARY_OUTPUT_RESERVE (20000)`：为 LLM 生成摘要预留的输出空间
- `AUTO_COMPACT_SAFETY_MARGIN (13000)`：安全边际，防止在压缩过程中就已经超限

#### 3.2 current_tokens 怎么算

```python
# ConversationManager
def current_tokens(self):
    if self.baseline_tokens == 0:
        # 冷启动（还没调用过 LLM）
        return estimate_tokens(self.history)
        # = 总字符数 / 3.5

    # 有锚点（上次 LLM API 返回的真实 token 数）
    return self.baseline_tokens + estimate_tokens(self.history[self.anchor_count:])
    # = API 报告的真实值 + 锚点之后新增消息的字符估算

def record_usage_anchor(self, input_tokens, message_count):
    self.baseline_tokens = input_tokens  # API 返回的真实 prompt token 数
    self.anchor_count = message_count    # 记录锚点时的消息数量
```

**两阶段估算**：
1. 冷启动（第 1 轮）：纯字符估算（`总字符 / 3.5`）
2. 后续轮次：API 真实值 + 增量估算

#### 3.3 压缩执行流程

```
auto_compact() 被调用
    │
    ├── 检查 1: current < threshold → 返回 None（不需要压缩）
    │
    ├── 检查 2: breaker.is_open() → 返回错误（熔断）
    │   （连续失败 3 次后熔断，防止反复失败）
    │
    ├── 步骤 A: 确定保留窗口
    │   _compute_keep_start_index(history)
    │   从尾部向前遍历：
    │     累计 token >= 10000 或消息数 >= 5 时停止
    │     但不超过 40000 token
    │   → to_summarize = history[:keep_start]  （要摘要的旧消息）
    │   → keep_tail = history[keep_start:]     （原样保留的近期消息）
    │
    ├── 检查 3: to_summarize 太小（< 2000 tokens）→ 返回 None
    │   （不值得摘要，摘要本身的开销比回收的空间还大）
    │
    ├── 步骤 B: 构建 LLM 摘要请求
    │   summary_conv = [SUMMARY_PROMPT] + to_summarize + ["请生成摘要"]
    │
    ├── 步骤 C: 调用 LLM 生成摘要（最多重试 3 次）
    │   for attempt in range(3):
    │     try:
    │       LLM stream → 收集文本
    │       break
    │     except "prompt too long":
    │       丢弃最早的 1/5 对话，重试
    │     except 其他错误:
    │       breaker.record_failure()
    │       返回错误字符串
    │
    ├── 步骤 D: 提取摘要
    │   extract_summary(llm_output)
    │   从 <summary>...</summary> 标签中提取
    │
    ├── 步骤 E: 构建恢复附件
    │   build_recovery_attachment(recovery_state, tool_schemas)
    │   把最近读取的文件、调用的技能做成文本附件
    │
    ├── 步骤 F: 重建对话历史
    │   new_messages = [
    │     Message(user, "本次会话延续自之前的对话...摘要:\n{summary}\n附件:\n{attachment}"),
    │     *keep_tail  ← 近期消息原样保留
    │   ]
    │
    ├── 步骤 G: 替换历史 + 清理
    │   conversation.replace_history(new_messages)
    │   → 同时清零 baseline_tokens / anchor_count（因为历史变了，旧锚点失效）
    │   cleanup_tool_results(session_dir)
    │   → 删除持久化的工具结果文件
    │
    └── 返回 CompactEvent(before_tokens, boundary)
```

#### 3.4 压缩后的恢复

压缩后，Agent 做了以下恢复操作：

```python
# Agent.run() 主循环中
if isinstance(compact_result, CompactEvent):
    # 1. 重新加载记忆
    mem = await self._load_memory_context()

    # 2. 重新注入环境上下文 + 记忆
    after_tokens = reinject_after_compact(
        conversation,
        environment_context=env_context,
        instructions_content=self.instructions_content,
        memory_content=mem,
    )
    # reinject_after_compact 做了什么：
    #   inject_agent_context(conversation, ...)
    #     → conversation.inject_environment(env_context)
    #       在 history 开头插入环境信息
    #     → conversation.inject_long_term_memory(instructions, memory)
    #       在 history 开头插入系统指令和记忆
    #   return conversation.current_tokens()

    # 3. 通知消费者
    yield compact_success_notification(compact_result, after_tokens)
    # → CompactNotification(before=180000, message="已压缩（180,000 → 45,000 tokens）", after=45000)
```

#### 3.5 RecoveryState 的作用

```python
# 每次 ReadFile 执行后，调用 _snapshot_for_recovery
def _snapshot_for_recovery(self, tc, result):
    record_tool_recovery_snapshot(
        recovery_state=self.recovery_state,
        tool_call=tc,
        result=result,
        work_dir=self.work_dir,
    )
    # 如果 tc.tool_name == "ReadFile":
    #   recovery_state.file_reads.append(FileReadRecord(
    #     path="main.py",
    #     content_snippet=result.output[:N],  # 前 N 行
    #     timestamp=time.time(),
    #   ))
    # 限制最多保留 RECOVERY_FILE_LIMIT 个文件记录
```

压缩时，这些快照被构建为附件文本：

```python
def build_recovery_attachment(recovery, tool_schemas):
    if recovery is None:
        return ""
    parts = []
    if recovery.file_reads:
        parts.append("## 最近读取的文件")
        for record in recovery.file_reads:
            parts.append(f"### {record.path}")
            parts.append(record.content_snippet)
    return "\n".join(parts)
```

这个附件被拼接到摘要消息中，让 LLM 在压缩后仍然"记得"最近读了哪些文件。

#### 3.6 熔断器

```python
@dataclass
class CompactCircuitBreaker:
    max_failures: int = 3
    consecutive_failures: int = 0

    def record_failure(self):
        self.consecutive_failures += 1

    def record_success(self):
        self.consecutive_failures = 0  # 成功就重置

    def is_open(self):
        return self.consecutive_failures >= max_failures
```

**何时触发**：
- 压缩失败时 `record_failure()`
- 压缩成功时 `record_success()`（重置计数）
- 检查时 `is_open()` → 连续失败 3 次后熔断，不再尝试自动压缩

**效果**：熔断后返回错误字符串，Agent yield `ErrorEvent`。用户需要手动处理（如手动压缩或清理对话）。

### 4. 手动压缩

除了自动压缩，用户可以通过 GUI 按钮或 API 手动触发压缩：

```python
# Agent.manual_compact()
async def manual_compact(self, conversation):
    result = await auto_compact(
        conversation, self.client, self.context_window, self.session_dir,
        manual=True,  # ← 关键区别：manual=True
        ...
    )
    # manual=True 的区别：
    #   threshold = context_window - 20000 - 3000（而不是 13000）
    #   不检查 current < threshold（强制执行）
    #   不检查熔断器
```

### 5. 完整数据流总结

```
对话开始
    │
    │ conversation.history = [环境消息, 记忆消息, 用户消息]
    │
    ▼
┌─ 迭代 1 ─────────────────────────────────────────────────┐
│                                                          │
│  Layer 2 检查: current_tokens=3000 < 167000 → 不压缩     │
│                                                          │
│  Layer 1: apply_tool_result_budget                       │
│    → 无旧工具结果，api_conv = conversation（原样）         │
│                                                          │
│  调用 LLM → 返回 tool_call(ReadFile)                     │
│  执行 ReadFile → ToolResult(output="5000行文件内容")      │
│  _snapshot_for_recovery → 记录 FileReadRecord            │
│  conversation.add_tool_results_message([result])          │
│  → history 追加 user 消息，含 5000 行文件内容              │
│                                                          │
│  record_usage_anchor(input_tokens=8000, count=4)         │
│  → baseline_tokens=8000, anchor_count=4                  │
└──────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 迭代 2 ─────────────────────────────────────────────────┐
│                                                          │
│  Layer 2 检查: current_tokens=8000 < 167000 → 不压缩     │
│                                                          │
│  Layer 1: apply_tool_result_budget                       │
│    → 工具结果 5000 行 < 50000 字符 → 不截断               │
│    → api_conv = conversation（原样）                      │
│                                                          │
│  调用 LLM → 返回 tool_call(ReadFile)                     │
│  执行 ReadFile → ToolResult(output="另一个大文件")        │
│  _snapshot_for_recovery → 记录 FileReadRecord            │
│  conversation.add_tool_results_message([result])          │
│                                                          │
│  record_usage_anchor(input_tokens=20000, count=6)        │
└──────────────────────────────────────────────────────────┘
    │
    ... 迭代 N（对话越来越长，token 逐渐增长）...
    │
    ▼
┌─ 迭代 50 ────────────────────────────────────────────────┐
│                                                          │
│  Layer 2 检查: current_tokens=170000 >= 167000 → 触发！  │
│  yield CompactStarted(current=170000, threshold=167000)  │
│                                                          │
│  auto_compact:                                           │
│    keep_start = 45（保留最后 5 条消息）                    │
│    to_summarize = history[:45]（45 条旧消息）              │
│    keep_tail = history[45:]（5 条近期消息）                │
│    调用 LLM 生成摘要 → "用户要求读取main.py..."            │
│    build_recovery_attachment → "最近读取: main.py\n..."   │
│    new_messages = [摘要消息, *keep_tail]                  │
│    conversation.replace_history(new_messages)             │
│    → baseline_tokens = 0（清零锚点）                       │
│                                                          │
│  reinject_after_compact:                                 │
│    重新注入 env_context + memory                         │
│    after_tokens = 35000                                  │
│                                                          │
│  yield CompactNotification(before=170000, after=35000)   │
│  yield UsageEvent(context_tokens=35000)                  │
│                                                          │
│  Layer 1: apply_tool_result_budget                       │
│    → 压缩后工具结果少了，不太需要截断                       │
│                                                          │
│  调用 LLM → 正常继续...                                   │
└──────────────────────────────────────────────────────────┘
```

## 第四部分：概念对照与排障（补充）

> 若要把「环境/指令/记忆注入 + Layer1/Layer2 + 记忆读写时序」从头走通，优先读专章：[10-上下文与记忆系统](./10-上下文与记忆系统.md)。本节保留权限/Hook 视角下的对照表。

### A. 双层上下文一句话

| 层 | 改不改真 history | 触发 | 目的 |
|----|------------------|------|------|
| Layer1 tool-result budget | 默认不改真历史（发送副本裁剪） | 每轮发送前 | 控制单次请求体积 |
| Layer2 auto compact | **改** conversation.history（摘要+keep-tail） | 接近 context window | 保住长期可续聊 |

### B. 权限 Future 在三条入口中的落点

`	ext
TUI:
  yield PermissionRequest → Textual 弹窗 → future.set_result

Daemon+GUI:
  yield PermissionRequest
  → serialize 去掉 future，换 request_id
  → WS 推前端
  → POST /api/permission/{sid}
  → Session.resolve_future

子 Agent 非交互:
  可能自动 deny/allow 策略（见 noninteractive_tools）
`

### C. Hook 输出如何进模型视野

`	ext
Hook 执行
  → 引擎记录 notification / prompt_messages
  → Agent drain
       notification → system-reminder 或 HookEvent
       prompt_messages → 拼进 system prompt
`

### D. token 估算与压缩阈值

ConversationManager.current_tokens()：

- 有 API usage 锚点：baseline + 锚点后新消息字符估算
- 无锚点：全历史字符估算
- compact 后锚点清零，直到下一次 API 响应

阈值大致：context_window - SUMMARY_OUTPUT_RESERVE - AUTO_COMPACT_SAFETY_MARGIN

### E. 排障

| 现象 | 检查 |
|------|------|
| 总是弹权限 | mode；规则；沙箱外路径 |
| 从不弹权限 | bypass；规则 allow；Hook 拦截 |
| 压缩后丢细节 | 有损摘要；看 recovery 附件 |
| 模型侧 tool 结果变短 UI 仍长 | Layer1 只裁发送副本 |
| Hook 不跑 | event 名；condition；load_hooks 失败 |

### F. 相关文件速查

| 主题 | 路径 |
|------|------|
| 权限检查链 | permissions/ |
| 授权握手 | gent/tool_authorization.py |
| Hook 引擎 | hooks/engine.py |
| Layer1 | context/tool_results.py / gent/llm_preparation.py |
| Layer2 | context/manager.py / gent/compaction.py |
| 替换状态 | context/replacement.py |
| 恢复附件 | context/recovery.py / gent/recovery.py |
