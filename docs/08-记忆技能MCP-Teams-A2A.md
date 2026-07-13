# 08 - 记忆、技能、MCP、Teams 与 A2A

## 1. 记忆系统（Memory）

### 1.1 为什么需要记忆？

LLM 本身是无状态的——每次对话都是全新的。但实际使用中，用户希望 Agent "记住"项目偏好、历史决策、常见问题等。记忆系统通过在对话开始前注入相关记忆，在对话结束后提取新记忆来实现这一点。

### 1.2 记忆的工作流程

```
对话开始
    ↓
1. 加载记忆: 从记忆存储中检索与当前查询相关的记忆
    ↓
2. 注入上下文: 将记忆作为系统提示注入对话历史
    ↓
3. Agent 正常运行（多轮对话）
    ↓
4. 观察记忆: 每轮结束时，通知记忆系统观察对话内容
    ↓
5. 提取记忆: 每隔 N 轮，让 LLM 从对话中提取值得记住的信息
    ↓
6. 持久化: 将提取的记忆保存到存储中
    ↓
对话结束
```

### 1.3 MemoryHub

`MemoryHub` 是记忆系统的统一入口，管理多个 Provider：

```python
class MemoryHub:
    def __init__(self, providers: list[MemoryProvider]):
        self._providers = providers

    async def load_context(self, query: str, session_id: str) -> str:
        """从所有 Provider 加载记忆，合并返回。"""
        contexts = []
        for p in self._providers:
            if not p.enabled:
                continue
            items = await p.recall(query, session_id)
            contexts.extend(items)
        return _format_memory_context(contexts)

    async def observe(self, conversation, event_type, session_id, agent_id):
        """通知所有 Provider 观察对话。"""
        for p in self._providers:
            await p.observe(conversation, event_type, session_id)

    async def extract_memories(self, conversation, session_id, agent_id, query):
        """从对话中提取记忆。"""
        for p in self._providers:
            await p.extract(conversation, session_id, agent_id, query)
```

### 1.4 记忆 Provider 类型

| 类型 | 说明 | 存储 |
|------|------|------|
| `builtin.markdown` | Markdown 文件存储 | `.mozilcode/memory/` 目录 |
| `builtin.tencentdb` | TencentDB 存储 | 远程数据库 |
| `python` | 自定义 Python 模块 | 用户实现 |

### 1.5 MarkdownMemoryProvider

最简单的内置 Provider，将记忆存储为 Markdown 文件：

```python
class MarkdownMemoryProvider(MemoryProvider):
    def __init__(self, work_dir: str, manager: MemoryManager):
        self._memory_dir = Path(work_dir) / ".mozilcode" / "memory"
        self._manager = manager

    async def recall(self, query: str, session_id: str) -> list[MemoryItem]:
        """读取所有 Markdown 记忆文件。"""
        items = []
        for md_file in self._memory_dir.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            items.append(MemoryItem(
                content=content,
                source=str(md_file),
                relevance=_compute_relevance(query, content),
            ))
        return items

    async def extract(self, conversation, session_id, agent_id, query):
        """让 LLM 从对话中提取记忆。"""
        prompt = f"从以下对话中提取值得长期记住的信息:\n{conversation}"
        result = await self._manager.llm_extract(prompt)
        if result:
            self._save_memory(result, session_id)
```

### 1.6 AgentMemoryBridge

`AgentMemoryBridge` 是 Agent 与 MemoryHub 之间的桥梁：

```python
class AgentMemoryBridge:
    def __init__(self, memory_hub, client, protocol, project_root):
        self.memory_hub = memory_hub
        self._client = client
        self._protocol = protocol
        self._root = project_root

    async def load_context(self, query: str = "", session_id: str = "") -> str:
        if self.memory_hub is None:
            return ""
        return await self.memory_hub.load_context(query, session_id)

    async def extract_memories(self, conversation, session_id, agent_id, query):
        if self.memory_hub is None:
            return
        await self.memory_hub.extract_memories(
            conversation, session_id, agent_id, query
        )
```

### 1.7 记忆提取间隔

为避免每轮都做昂贵的记忆提取，Agent 每 5 轮才提取一次：

```python
MEMORY_EXTRACTION_INTERVAL = 5

# Agent 主循环中
if not response.tool_calls:
    self._loop_count += 1
    if self._loop_count % MEMORY_EXTRACTION_INTERVAL == 0 and self.memory_hub:
        asyncio.ensure_future(self._extract_memories(conversation))  # 后台提取
```

## 2. 技能系统（Skills）

### 2.1 什么是技能？

技能（Skill）是预定义的**提示词模板**，让用户可以通过简短的命令触发复杂的行为。类似于 Claude Code 的 slash commands。

```
用户输入: /commit
    ↓
激活 "commit" 技能
    ↓
技能提示词: "分析 git diff 并生成规范的 commit message..."
    ↓
Agent 按照技能提示词执行
```

### 2.2 技能定义格式

技能用 Markdown + YAML frontmatter 定义：

```markdown
---
name: commit
description: 分析 git diff 并生成规范的 commit message
mode: inline        # inline（内联执行）| fork（fork 子 Agent）
context: full       # full（完整上下文）| recent（近期上下文）| none
allowedTools:       # 允许使用的工具
  - Bash
  - ReadFile
model: null          # null 表示用默认模型
---
分析当前 git diff，生成符合 Conventional Commits 规范的 commit message。
执行 git add -A 然后 git commit。
```

### 2.3 SkillDef 数据结构

```python
@dataclass
class SkillDef:
    name: str                    # 技能名称（小写字母+数字+连字符）
    description: str             # 描述
    prompt_body: str = ""        # 提示词正文
    allowed_tools: list[str] = []  # 允许的工具
    mode: Literal["inline", "fork"] = "inline"  # 执行模式
    model: str | None = None     # 指定模型
    context: Literal["full", "recent", "none"] = "full"  # 上下文模式
    source_path: Path | None = None  # 源文件路径
    is_directory: bool = False   # 是否目录形式
```

### 2.4 SkillLoader

```python
class SkillLoader:
    def __init__(self, work_dir: str):
        self._project_dir = Path(work_dir) / ".mozilcode" / "skills"
        self._user_dir = Path("~/.mozilcode/skills").expanduser()

    def load_all(self) -> dict[str, SkillDef]:
        seen = {}
        # 1. 项目级技能
        for skill in self._scan_directory(self._project_dir, "project"):
            if skill.name not in seen:
                seen[skill.name] = skill
        # 2. 用户级技能
        for skill in self._scan_directory(self._user_dir, "user"):
            if skill.name not in seen:
                seen[skill.name] = skill
        # 3. 内置技能
        for skill in self._load_builtins():
            if skill.name not in seen:
                seen[skill.name] = skill
        return seen
```

技能加载优先级：项目级 > 用户级 > 内置。

### 2.5 技能执行模式

| 模式 | 说明 |
|------|------|
| `inline` | 在当前 Agent 中执行，共享完整上下文 |
| `fork` | Fork 一个子 Agent 执行，隔离上下文 |

### 2.6 自定义工具

技能目录可以包含 `tool.json` 和 `references/` 目录，定义自定义工具：

```
.mozilcode/skills/my-skill/
├── SKILL.md              # 技能定义
├── tool.json             # 自定义工具 Schema
└── references/
    └── my_tool.py        # 工具实现（execute 函数）
```

```python
# references/my_tool.py
def execute(param1: str, param2: int) -> str:
    """工具实现。"""
    return f"Result: {param1} {param2}"
```

## 3. MCP 协议集成

### 3.1 什么是 MCP？

MCP（Model Context Protocol）是一个开放协议，允许 LLM 与外部工具和数据源交互。类似于"插件系统"——你可以接入文件系统、数据库、API 等各种 MCP 服务器，让 LLM 使用它们提供的工具。

### 3.2 MCP 架构

```
Agent  ←→  MCPManager  ←→  MCPClient  ←→  MCP Server
                                         (stdio 或 HTTP)
```

MCP 服务器有两种传输方式：
- **stdio**：通过标准输入/输出通信（子进程）
- **HTTP**：通过 HTTP 请求通信（远程服务）

### 3.3 MCPManager

```python
class MCPManager:
    def __init__(self):
        self._configs: dict[str, MCPServerConfig] = {}  # 服务器配置
        self._clients: dict[str, MCPClient] = {}          # 活跃连接

    def load_configs(self, configs: list[MCPServerConfig]):
        """加载 MCP 服务器配置。"""
        for cfg in configs:
            self._configs[cfg.name] = cfg

    async def register_all_tools(self, registry: ToolRegistry) -> list[str]:
        """连接所有 MCP 服务器，注册它们的工具。"""
        errors = []
        for name, config in self._configs.items():
            try:
                client = MCPClient(config)
                await client.connect()
                tools = await client.list_tools()
                for tool_def in tools:
                    wrapper = MCPToolWrapper(name, tool_def, client)
                    registry.register(wrapper)  # 注册为 Agent 工具
            except Exception as e:
                errors.append(f"MCP server '{name}': {e}")
        return errors
```

### 3.4 MCPToolWrapper

MCP 服务器的工具被包装为 `MCPToolWrapper`，实现标准的 `Tool` 接口：

```python
class MCPToolWrapper(Tool):
    def __init__(self, server_name: str, tool_def, client: MCPClient):
        self.name = f"mcp_{server_name}_{tool_def.name}"
        self.description = tool_def.description
        self._client = client
        self._tool_def = tool_def

    async def execute(self, params: BaseModel) -> ToolResult:
        # 调用 MCP 服务器执行工具
        result = await self._client.call_tool(
            self._tool_def.name,
            params.model_dump(),
        )
        return ToolResult(output=str(result))
```

## 4. Teams 多智能体协作

### 4.1 概念

Teams 系统允许多个 Agent 协作完成复杂任务。一个"Lead Agent"可以创建"Teammate Agent"来并行处理子任务。

### 4.2 架构

```
Lead Agent
    ├── 创建 Teammate 1 (Agent A)
    ├── 创建 Teammate 2 (Agent B)
    └── 创建 Teammate 3 (Agent C)

通信方式: Mailbox（邮箱模型）
    - Lead → Teammate: 分配任务
    - Teammate → Lead: 汇报结果
```

### 4.3 TeamManager

```python
class TeamManager:
    def __init__(self, worktree_manager, trace_manager):
        self._teams: dict[str, Team] = {}
        self._worktree_mgr = worktree_manager
        self._trace_mgr = trace_manager

    def has_teams(self) -> bool:
        return len(self._teams) > 0

    def team_names(self) -> list[str]:
        return list(self._teams.keys())

    def drain_lead_mailbox(self) -> list[str]:
        """读取所有 Teammate 发给 Lead 的消息。"""
        messages = []
        for team in self._teams.values():
            messages.extend(team.lead_mailbox.drain())
        return messages
```

### 4.4 邮箱模型

Agent 之间通过邮箱（Mailbox）通信，避免直接耦合：

```python
class Mailbox:
    def __init__(self):
        self._messages: list[str] = []

    def send(self, message: str):
        self._messages.append(message)

    def drain(self) -> list[str]:
        """取出所有消息并清空邮箱。"""
        msgs = self._messages
        self._messages = []
        return msgs
```

### 4.5 通知注入

Agent 主循环中，每轮开始前检查邮箱并注入通知：

```python
def _inject_external_notifications(self, conversation):
    """将外部通知（Teammate 消息等）注入对话。"""
    if self.notification_fn:
        notes = self.notification_fn()  # drain_lead_mailbox
        for note in notes:
            conversation.add_system_reminder(note)
```

## 5. A2A 协议桥接

### 5.1 什么是 A2A？

A2A（Agent-to-Agent）是一个标准协议，允许不同的 AI Agent 之间互相通信和协作。本项目的 A2A Bridge 将 Daemon 暴露为一个 A2A 兼容的 Agent 端点。

### 5.2 A2ABridge

```python
class A2ABridge:
    """将 Daemon Agent 暴露为 A2A 兼容的任务桥接器。"""

    def __init__(self, daemon_server, default_wait_timeout=120.0):
        self._server = daemon_server
        self._tasks: dict[str, A2ATask] = {}  # A2A 任务追踪

    def agent_card(self, base_url: str = "") -> dict:
        """返回 A2A Agent Card（Agent 能力描述）。"""
        return {
            "name": "MozilCode",
            "description": "AI coding assistant",
            "version": _package_version(),
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
            },
            "url": f"{base_url}/a2a/rpc",
        }

    async def handle_rpc(self, request: dict) -> dict:
        """处理 JSON-RPC 请求。"""
        method = request.get("method")
        params = request.get("params", {})

        if method == "message/send":
            return await self._handle_message_send(params)
        elif method == "tasks/get":
            return await self._handle_task_get(params)
        elif method == "tasks/cancel":
            return await self._handle_task_cancel(params)
```

### 5.3 A2A 任务生命周期

```python
TASK_SUBMITTED = "submitted"        # 已提交
TASK_WORKING = "working"            # 处理中
TASK_INPUT_REQUIRED = "input-required"  # 需要额外输入
TASK_COMPLETED = "completed"        # 已完成
TASK_CANCELED = "canceled"          # 已取消
TASK_FAILED = "failed"              # 失败

TERMINAL_STATES = {TASK_COMPLETED, TASK_CANCELED, TASK_FAILED}
```

### 5.4 A2A 与 Daemon 的集成

A2A Bridge 复用 Daemon 现有的会话/任务/事件日志接口：

```python
async def _handle_message_send(self, params: dict) -> dict:
    # 1. 从 A2A 消息中提取 prompt
    message = parse_message_request(params)
    prompt = message["content"]["text"]

    # 2. 创建 Daemon 会话
    sid = await self._server.init_session()

    # 3. 启动任务
    task_id = await self._server.start_task(sid, prompt)

    # 4. 追踪 A2A 任务
    a2a_task = A2ATask(
        id=task_id,
        session_id=sid,
        state=TASK_WORKING,
    )
    self._tasks[task_id] = a2a_task

    # 5. 如果需要等待结果
    if should_wait(params):
        result = await self._wait_for_completion(task_id)
        return task_to_a2a_payload(result)

    return task_to_a2a_payload(a2a_task)
```

## 6. Worktree（工作树）管理

### 6.1 什么是 Git Worktree？

Git Worktree 允许在同一个仓库中创建多个工作目录，每个工作目录可以在不同的分支上工作。这在多智能体场景中很有用——每个 Teammate Agent 可以在自己的 Worktree 中独立工作，互不干扰。

### 6.2 WorktreeManager

```python
class WorktreeManager:
    def __init__(self, repo_root: str, symlink_directories: list[str]):
        self._repo_root = Path(repo_root)
        self._symlink_dirs = symlink_directories  # 需要软链接的目录

    def create(self, name: str, base_branch: str = "HEAD") -> Path:
        """创建 Worktree。"""
        wt_path = self._repo_root / ".worktrees" / name
        # git worktree add <path> <base_branch>
        subprocess.run(["git", "worktree", "add", str(wt_path), base_branch])

        # 软链接共享目录（如 node_modules）
        for d in self._symlink_dirs:
            src = self._repo_root / d
            dst = wt_path / d
            if src.exists() and not dst.exists():
                dst.symlink_to(src)

        return wt_path

    def remove(self, name: str):
        """移除 Worktree。"""
        subprocess.run(["git", "worktree", "remove", str(path)])
```
