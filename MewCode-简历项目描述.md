# MewCode 简历项目描述参考

> 把这个项目写进简历，核心思路是：**别堆名词，讲清楚你解决了什么技术问题、怎么解决的、效果如何**。
> 面试官真正想看的是"系统设计能力 + 工程落地能力",不是一串框架清单。

---

## 项目概况（一句话）

**MewCode** —— 基于 Python 从零实现的终端 AI 编码助手，支持 Anthropic / OpenAI 三协议，包含完整的 Agent 循环、工具系统、子 Agent、双层上下文压缩、权限控制、Skills/Hooks/MCP 扩展与多 Agent 协作。

- 技术栈：Python 3.12 · asyncio · Textual(TUI) · Pydantic · MCP
- 规模：主包约 1.8 万行 / 131 个模块，含约 7,700 行测试
- 角色：独立设计与实现

---

## 版本 A：一段式（适合简历空间紧张）

> **MewCode — 终端 AI 编码助手（Python / 个人项目）**
> 从零设计并实现了一套类 Claude Code 的 AI Agent 系统。核心包括：模型↔工具流式 Agent 循环（支持工具批量并行、流式期预执行、max_tokens 中断恢复）；统一 Anthropic / OpenAI Responses / Chat Completions 三协议的模型适配层；双层上下文压缩（超大 tool 结果按预算替换+落盘 / 接近窗口自动摘要并保留恢复快照，支持 200K 窗口下的无限长对话）；6 种权限模式 + 规则引擎 + 全生命周期 Hooks；Skills / MCP 扩展体系；基于 mailbox 的多 Agent 协作框架（进程内 / tmux / iTerm2 三后端）。主包约 1.8 万行。

---

## 版本 B：Bullet 式（推荐，信息密度高）

**MewCode — 终端 AI 编码助手** ｜ Python 3.12 · asyncio · Textual · Pydantic · MCP ｜ 个人项目

- **设计并实现 Agent 核心循环**：模型↔工具流式交互至收敛；按"并发安全"对工具调用分区，安全工具批量并行执行；在 LLM streaming 期间预启动工具执行，减少串行等待；实现 max_tokens 触顶后的分级恢复（提额 + 分段续写），避免长输出被截断。
- **自研双层上下文压缩**：Layer 1 对超大工具结果按 token 预算替换为"摘要 + 落盘文件"并记录替换快照；Layer 2 在接近 context window 时自动摘要历史对话，并通过 RecoveryState 重新附加最近的文件读取内容，保证压缩后工作上下文不丢失，支持 200K 窗口下无限长对话。
- **抽象多协议模型适配层**：将 Anthropic、OpenAI Responses、Chat Completions 三种协议的请求/响应统一为内部 StreamEvent 流与 Conversation 格式；新增模型供应商只需实现一个 stream 适配器，业务层无感知。
- **实现 6 种权限模式 + 规则引擎**：覆盖 default / acceptEdits / plan / bypassPermissions / custom / dontAsk；支持 allow_always 自动生成规则；pre/post hooks 可在工具执行前后拦截、改写或拒绝。
- **构建扩展体系**：23 个内置工具 + 17 个斜杠命令；Skills（含 commit/review/test 等）按 frontmatter 声明式加载；MCP server 工具自动包装为统一 Tool；延迟工具加载（ToolSearch）按需注入 schema，控制 system prompt 体积。
- **设计 Teams 多 Agent 协作框架**：通过 mailbox 实现 Agent 间异步消息通信，支持进程内 / tmux / iTerm2 三种后端，可派生子 Agent 后台执行并共享任务列表。
- **工程化**：基于 Textual 构建 TUI；会话以 JSONL 持久化、支持 rewind 回溯；git worktree 隔离实验性改动；约 7,700 行测试覆盖核心路径。

---

## 版本 C：总分式（总起 + 分条展开，推荐用于简历正文主体）

**MewCode — 终端 AI 编码助手** ｜ Python 3.12 · asyncio · Textual · Pydantic · MCP ｜ 个人项目

从零设计并实现了一套类 Claude Code 的 AI Agent 系统，主包约 1.8 万行 / 131 个模块。系统以"模型↔工具流式交互至收敛"为核心循环，向上抽象出统一三协议（Anthropic / OpenAI Responses / Chat Completions）的模型适配层，向下提供 23 个内置工具与可扩展的 Skills / MCP / Hooks 体系；通过双层上下文压缩在 200K 窗口下支持无限长对话，并以 6 种权限模式 + 规则引擎保障执行安全。具体技术工作如下：

- **Agent 核心循环**：模型↔工具流式交互至收敛；按"并发安全"对工具调用分区，安全工具批量并行执行；在 LLM streaming 期间预启动工具执行，减少串行等待；实现 max_tokens 触顶后的分级恢复（提额 + 分段续写），避免长输出被截断。
- **双层上下文压缩**：Layer 1 对超大工具结果按 token 预算替换为"摘要 + 落盘文件"并记录替换快照；Layer 2 在接近 context window 时自动摘要历史对话，并通过 RecoveryState 重新附加最近的文件读取内容，保证压缩后工作上下文不丢失。
- **多协议模型适配层**：将 Anthropic、OpenAI Responses、Chat Completions 三种协议的请求/响应统一为内部 StreamEvent 流与 Conversation 格式；新增模型供应商只需实现一个 stream 适配器，业务层无感知。
- **权限模式 + 规则引擎**：覆盖 default / acceptEdits / plan / bypassPermissions / custom / dontAsk 六种模式；支持 allow_always 自动生成规则；pre/post hooks 可在工具执行前后拦截、改写或拒绝。
- **扩展体系**：23 个内置工具 + 17 个斜杠命令；Skills（含 commit / review / test 等）按 frontmatter 声明式加载；MCP server 工具自动包装为统一 Tool；延迟工具加载（ToolSearch）按需注入 schema，控制 system prompt 体积。
- **Teams 多 Agent 协作**：通过 mailbox 实现 Agent 间异步消息通信，支持进程内 / tmux / iTerm2 三种后端，可派生子 Agent 后台执行并共享任务列表。
- **工程化**：基于 Textual 构建 TUI；会话以 JSONL 持久化、支持 rewind 回溯；git worktree 隔离实验性改动；约 7,700 行测试覆盖核心路径。

---

## 版本 D：精简版（3 条，适合简历空间紧张）

**MewCode — 终端 AI 编码助手** ｜ Python · asyncio · Textual · MCP ｜ 个人项目（~1.8 万行）

从零实现类 Claude Code 的 AI Agent 系统，核心是模型↔工具流式交互至收敛的 Agent 循环，支持 Anthropic / OpenAI 三协议统一适配。

- **Agent 循环 + 双层上下文压缩**：工具按并发安全分区批量并行、流式期预执行；超大 tool 结果按 token 预算落盘替换，接近窗口时自动摘要历史并通过 RecoveryState 恢复工作集，支持 200K 窗口无限长对话。
- **权限 + 扩展体系**：6 种权限模式 + 规则引擎 + 全生命周期 Hooks；23 个内置工具，Skills / MCP / 延迟工具加载（ToolSearch）按需注入 schema 控制提示词体积。
- **多 Agent 协作 + 工程化**：基于 mailbox 的 Teams 框架（进程内 / tmux / iTerm2 三后端）派生子 Agent 后台执行；会话 JSONL 持久化 + rewind 回溯 + git worktree 隔离，约 7,700 行测试。

---

## 版本 E：极简版（2 条，空间极紧时用）

**MewCode — 终端 AI 编码助手** ｜ Python · asyncio · Textual · MCP ｜ 个人项目（~1.8 万行）

从零实现类 Claude Code 的 AI Agent 系统，核心为模型↔工具流式交互至收敛的 Agent 循环，统一适配 Anthropic / OpenAI 三协议。

- **双层上下文压缩**：超大工具结果按 token 预算落盘替换 + 接近窗口自动摘要并恢复工作集，支持 200K 窗口无限长对话；Agent 循环支持工具分区并行、流式预执行、max_tokens 分级恢复。
- **完整扩展体系**：6 种权限模式 + 规则引擎 + Hooks；23 工具 + Skills / MCP / 延迟加载；基于 mailbox 的多 Agent 协作框架（三后端）；JSONL 持久化 + rewind + worktree 隔离，约 7,700 行测试。

---

## 版本 F：逐条压缩版（6 条，每条一行）

**MewCode — 终端 AI 编码助手** ｜ Python · asyncio · Textual · MCP ｜ 个人项目（~1.8 万行）

从零实现类 Claude Code 的 AI Agent 系统：模型↔工具流式交互循环为核心，向上统一 Anthropic / OpenAI 三协议，向下提供 23 工具 + Skills / MCP / Hooks 扩展；双层上下文压缩支持 200K 窗口无限长对话，6 种权限模式 + 规则引擎保障执行安全。

- **Agent 核心循环**：模型↔工具流式交互至收敛；工具按并发安全分区并行、流式期预执行；max_tokens 触顶后分级恢复（提额 + 续写）避免截断。
- **双层上下文压缩**：超大 tool 结果按 token 预算落盘替换；接近窗口时自动摘要历史并恢复工作集，支持 200K 窗口无限长对话。
- **多协议适配层**：统一 Anthropic / OpenAI Responses / Chat Completions 三协议为内部 StreamEvent 流；新供应商只需实现一个 stream 适配器。
- **权限 + 规则引擎**：6 种权限模式 + allow_always 自动生成规则；pre/post hooks 可拦截、改写或拒绝工具执行。
- **扩展体系**：23 工具 + 17 命令；MCP 工具自动包装为统一 Tool；延迟工具加载按需注入 schema 控制提示词体积。
- **Teams 多 Agent 协作**：基于 mailbox 异步消息通信，支持进程内 / tmux / iTerm2 三后端，可派生子 Agent 后台执行并共享任务列表。

---

## 面试深挖准备（面试官大概率追问）

### 1. 为什么自研而不是用 LangChain / 直接调 SDK？
- 答：这类框架把"循环、上下文、工具调度"都封装死了，而 AI 编码助手的核心差异化恰恰在这些层（上下文压缩策略、权限、流式执行）。自研能精确控制每一层的行为，也更能体现对 Agent 系统的理解。SDK 只解决"调模型"这一层。

### 2. 双层压缩怎么权衡？
- Layer 1 是"无损可控"的：tool 结果太大就落盘，给模型一个预览 + 文件路径，模型需要时再 ReadFile 取回——token 省了，信息没丢。
- Layer 2 是"有损摘要"的：接近窗口上限才触发，用模型生成摘要替换历史；但会保留 RecoveryState（最近读过的文件内容），压缩后重新注入，保证当前任务的工作集不丢。
- 两层配合：Layer 1 控制单条结果体积，Layer 2 控制整体历史体积，避免频繁摘要导致信息丢失。

### 3. 工具"并发安全"怎么判断？
- 由工具自身声明 `is_concurrency_safe`。只读、无副作用、无共享状态的工具（ReadFile/Glob/Grep）可并行；写文件、执行命令、修改状态的工具串行。同一批连续的安全调用合并成一个 batch 用 asyncio.gather 执行。

### 4. 多协议适配的难点？
- 三家协议的消息结构、tool_call 表示、streaming 事件切片都不一样。做法是定义内部统一的 `StreamEvent`（TextDelta/ToolCallDelta/ToolCallComplete/StreamEnd 等）和 `Conversation` 格式，每个协议写一个"序列化器 + 流归一器"。难点在 OpenAI Responses 协议的状态机式 streaming 和 tool_call 分片拼接。

### 5. 权限规则引擎怎么匹配？
- 规则按 (tool_name, pattern, effect) 三元组。pattern 对工具的 content（如文件路径、命令串）做前缀/通配匹配。allow_always 时会自动把用户批准的内容前缀生成一条 allow 规则追加到本地规则集，后续同类调用免询问。

### 6. mailbox 为什么不用消息队列？
- Agent 间通信是同进程或跨 tmux 会话，量级低、延迟敏感，用进程内 mailbox（队列）最简单；跨进程时通过文件/管道桥接。引入 MQ 是过度设计。

---

## 写简历的几条原则（提醒自己）

1. **动词开头**：设计 / 实现 / 抽象 / 优化 / 构建，不要用"参与了 / 负责了"。
2. **量化**：行数、工具数、窗口大小、协议数——能量化就量化，但必须真实。
3. **讲取舍**：面试官爱听"为什么这么做"，而不是"做了什么"。简历里埋一两个取舍点，引导追问。
4. **别抄框架名词**：写"双层上下文压缩"比写"用了 Pydantic"有价值得多。框架是工具，不是亮点。
5. **诚实**：是个人项目就写个人项目，别包装成团队项目。个人项目写出深度一样加分。
