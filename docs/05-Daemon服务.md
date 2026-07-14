# 05 - Daemon HTTP/WebSocket 服务

## 1. 概述

Daemon 是基于 **Starlette + Uvicorn** 的本地 HTTP + WebSocket 服务，把无界面的 `Agent` 引擎暴露成网络 API，供 GUI、脚本、A2A 客户端使用。

对应代码：

| 模块 | 路径 | 职责 |
|------|------|------|
| 入口 / 中间件 | `mozilcode/daemon/server.py` | `create_app` / `run_daemon`、Token 鉴权、Origin 守卫、CORS |
| 状态中枢 | `mozilcode/daemon/server_state.py` | `DaemonServer`：会话、任务、事件、pending prompt |
| 路由表 | `mozilcode/daemon/routes/core.py` | 声明全部 HTTP / WS 路径 |
| 会话 | `mozilcode/daemon/session/*` | 创建/懒恢复 runtime、meta、store |
| 任务 | `mozilcode/daemon/tasks/*` | 前台任务 runner、活动任务、事件序列化 |
| 序列化 | `mozilcode/daemon/serialize.py` | `AgentEvent` → JSON（Future → request_id） |
| A2A | `mozilcode/daemon/routes/a2a.py` + `mozilcode/a2a/*` | Agent Card / JSON-RPC / REST 兼容 |

默认监听：`http://127.0.0.1:7800`  
默认会话落盘：`~/.mozilcode/daemon_sessions/{sid}/`

---

## 2. 基础概念

### 2.1 HTTP 控制面 vs WebSocket 数据面

```text
HTTP REST（控制面）
  建会话、发任务、改权限模式、回权限、改配置……
  一问一答，不负责 token 流式推送

WebSocket（数据面）
  订阅某个 session 的事件日志
  实时推 StreamText / ToolUse / PermissionRequest / LoopComplete
  可回放历史事件 + 上行少量 action（如 cancel）
```

### 2.2 三个“会话相关”对象（必须分清）

```text
session_id
  对外主键。所有 API / WS 都用它定位会话。

work_dir
  该会话绑定的项目根目录。决定工具 base_dir、权限沙箱、项目记忆与指令。
  创建会话时写入 meta，不是从用户消息里猜出来的。

ConversationManager.history
  该会话的真对话账本。多轮消息通过“追加到同一个 history”接续。
```

### 2.3 两本账：展示账 vs 模型账

| 账本 | 结构 | 持久化 | 用途 |
|------|------|--------|------|
| **事件日志** `event_logs[sid]` | `list[dict \| None]` | `events.jsonl` | GUI 回放 / WS 实时推送 |
| **对话历史** `conversation.history` | `list[Message]` | **默认仅内存** | 喂给 LLM 的上下文来源 |

> 常见误解：重启 Daemon 后 UI 还能看到历史事件，不代表 `ConversationManager.history` 已自动恢复。当前主路径下，模型多轮上下文依赖**进程内 runtime 常驻**。

### 2.4 Starlette / ASGI

- Starlette：轻量 ASGI Web 框架（`Route` / `WebSocketRoute`）
- Uvicorn：ASGI 服务器
- 中间件顺序（后 add 先执行）：CORS → OriginGuard → TokenAuth → App

### 2.5 安全相关（代码真实行为）

`server.py`：

1. **`DaemonTokenAuthMiddleware`**
   - 环境变量 `MOZILCODE_DAEMON_TOKEN`
   - HTTP：`Authorization: Bearer <token>`
   - WS：query `?token=`
   - 公开路径：`/api/health`、`/.well-known/agent-card.json`、`/a2a/agent-card.json`
2. **`OriginGuardMiddleware` + CORSMiddleware**
   - 默认 origins：`http://localhost:1420,http://127.0.0.1:1420,tauri://localhost`
   - 可用 `MOZILCODE_CORS_ORIGINS` 覆盖
3. **非 loopback 绑定必须带 token**  
   `run_daemon`：host 不是 localhost/127./::1 时，无 token 直接 `RuntimeError`

旧文档里写的 `allow_origins=["*"]` 与当前代码不符；以 `server.py` 为准。

---

## 3. 服务架构

```text
┌────────────────────────────────────────────────────────────┐
│  Uvicorn :7800                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Starlette App                                        │  │
│  │  Middleware: CORS / OriginGuard / TokenAuth          │  │
│  │  app.state.server     = DaemonServer                  │  │
│  │  app.state.a2a_bridge = A2ABridge(server)             │  │
│  │                                                      │  │
│  │  HTTP Routes ─────────────┐                          │  │
│  │  WS /api/stream/{sid} ────┤                          │  │
│  │  A2A /a2a/* ──────────────┘                          │  │
│  └───────────────────────────┬──────────────────────────┘  │
│                              ▼                             │
│  DaemonServer                                              │
│  ├─ SessionManager      sid → Session(agent, conversation) │
│  ├─ _agents             sid → DaemonSessionRuntime         │
│  ├─ SessionRecords      meta + event_logs + 持久化          │
│  ├─ ActiveTaskRegistry  每会话前台任务                       │
│  ├─ PendingPromptRegistry  权限/AskUser 未决请求           │
│  └─ AgentTaskRunner     conversation.add_user + agent.run  │
└────────────────────────────────────────────────────────────┘
```

### 3.1 `DaemonSessionRuntime`（一个会话的内存运行时）

```python
# session/runtime.py
@dataclass(frozen=True)
class DaemonSessionRuntime:
    agent: Agent
    deps: AgentDeps
    conversation: ConversationManager
```

创建时（`create_daemon_session_runtime`）：

1. `create_agent_from_config(config, work_dir, permission_mode, hook_engine)`
2. `agent.session_id = sid`
3. `conversation = ConversationManager()`（空 history）
4. `session_mgr.create_session(sid, agent, conversation)`
5. 放入 `DaemonServer._agents[sid]`

### 3.2 `Session` vs `SessionRecords`

```text
SessionManager._sessions[sid] = Session
  agent / conversation
  _pending_futures: request_id → asyncio.Future   # 权限/AskUser

SessionRecords
  session_meta[sid] = {work_dir, title, provider_name, created_at, ...}
  event_logs[sid]   = [event_dict, ...]
  store             = SessionStore（磁盘）
```

---

## 4. 会话如何维护

### 4.1 创建会话：`POST /api/session`

请求体（`session/payloads.py`）：

```json
{
  "session_id": "可选，不给则随机 12 hex",
  "work_dir": "可选，不给则用 daemon 启动目录",
  "provider_name": "可选，指定用哪个 provider"
}
```

流程（`lifecycle_actions.init_daemon_session`）：

```text
1. sid = validate_session_id(session_id or uuid4.hex[:12])
2. 若 records 已有 sid → ValueError（不能重复创建）
3. resolved_work_dir = work_dir or default_work_dir
4. 校验 Path(resolved_work_dir).is_dir()
5. create_session_runtime(...)
     └─ create_agent_from_config(config, work_dir=resolved_work_dir, ...)
     └─ ConversationManager()
     └─ SessionManager.create_session
6. records.create(sid, resolved_work_dir, provider_name?)
     └─ meta.json 落盘
7. 返回 session_id + session_info
```

### 4.2 Daemon 怎么知道“这是哪个项目”

**唯一权威字段：`meta.work_dir`。**

```text
创建会话时
  body.work_dir 或 daemon 默认 work_dir
       ↓
  SessionRecords.session_meta[sid]["work_dir"] = ...
  SessionStore.persist_meta → meta.json
       ↓
  Agent 工厂用该路径：
    - ToolRegistry base_dir
    - PathSandbox(work_dir)
    - load_instructions(work_dir)
    - build_memory_hub(..., work_dir)
    - agent.work_dir = work_dir
```

后续读取：

- `DaemonServer.session_work_dir(sid)` → `records.work_dir(sid)`
- 文件浏览 `GET /api/fs/{sid}` 以该目录为根
- worktree 进入/退出会 `update_session_work_dir` + 改 `agent.work_dir`

**不是**从 prompt 文本解析项目路径。

### 4.3 懒恢复：`ensure_agent` / `ensure_session_runtime`

Daemon 启动时 `SessionRecords.load_persisted()`：

- 从磁盘加载所有 `meta` + `events`
- **不立刻**重建 Agent（省资源）

当某个 API 需要 runtime 时：

```text
ensure_session_runtime(sid):
  若 sid 已在 runtimes → True
  否则读 meta.work_dir / provider_name
  再 create_session_runtime（新的空 ConversationManager）
```

含义：

| 重启后仍在 | 重启后默认不在 |
|------------|----------------|
| session 列表、title、work_dir | `conversation.history` 多轮模型上下文 |
| events 回放（UI） | 进程内 pending Future |
| provider_name 偏好 | 当时未完成的工具 Future |

### 4.4 关闭会话：`DELETE /api/session/{sid}`

- 取消 pending futures
- 从 SessionManager / runtimes 移除
- 事件日志追加 `None` 哨兵
- 磁盘 `store.delete_session`

### 4.5 会话状态查询

`GET /api/session/{sid}/status` 等会聚合：

- meta（work_dir、title…）
- 是否 busy（活动任务）
- 权限模式 / plan 模式相关字段
- pending permission/askuser 信息

---

## 5. 发送消息时上下文如何接上

### 5.1 API

```http
POST /api/task
Content-Type: application/json

{
  "session_id": "abc123",
  "prompt": "帮我看一下 README"
}
```

返回：

```json
{ "task_id": "1a2b3c4d", "session_id": "abc123" }
```

HTTP 只负责**启动**后台任务；流式内容走 WebSocket。

### 5.2 任务执行链路（核心）

```text
DaemonServer.start_task(sid, prompt)
  → 确保 runtime（agent + conversation）
  → AgentTaskRunner.start(sid, prompt, agent, conversation)
       task_id = uuid4.hex[:8]
       asyncio.create_task(_run_agent_task(...))

_run_agent_task:
  1) conversation.add_user_message(prompt)     # 接到真 history 末尾
  2) emit UserMessage 事件到 event_logs        # 给 GUI
  3) async for event in agent.run(conversation):
        serialize → emit →（权限则 register_future）
  4) emit LoopComplete
  finally: persist_events(sid)
```

代码：`mozilcode/daemon/tasks/runner.py`

### 5.3 多轮上下文接续（同一 session）

```text
会话创建后 conversation.history = []

第 1 次 POST /api/task prompt=U1
  history: [U1]
  agent.run → 写回 assistant / tool_use / tool_result ...
  history: [U1, A1, TR1, ...]

第 2 次 POST /api/task prompt=U2
  history: [..., U2]          # 仍是同一个 ConversationManager
  agent.run 看到完整历史
```

因此：**“上下文接上”= 复用 sid 对应 runtime 的 conversation 对象并追加 user 消息。**

### 5.4 `agent.run` 内部如何组装“发给模型的上下文”

（Agent 循环见 [02](./02-Agent核心运行循环.md)；Layer1/2 与记忆专章见 [10](./10-上下文与记忆系统.md)、摘要见 [07](./07-权限Hook与上下文管理.md)。此处只标 Daemon 视角。）

```text
真 history（可能已很长）
  + inject 环境 / 长期记忆（若尚未注入）
  + system-reminder（plan / hook / deferred tools）
  + system prompt（不进入 history）
  + tools schemas
       │
       ▼
prepare_api_conversation  →  api_conv（Layer1 可裁剪 tool-result）
       │
       ▼
client.stream(api_conv, system=..., tools=...)
       │
       ▼
响应写回 conversation.history（真账本继续增长）
必要时 Layer2 compact 会 replace_history（有损）
```

### 5.5 项目上下文 vs 对话上下文

| 类型 | 来源 | 生命周期 |
|------|------|----------|
| 项目路径/沙箱 | `work_dir` → Agent/Tools | 会话级（可 worktree 切换） |
| 项目指令 MOZILCODE.md | `load_instructions(work_dir)` | 创建 Agent 时加载；compact 后可 reinject |
| 长期记忆 | MemoryHub(work_dir) | run 开始 load；周期性 extract（详 [10](./10-上下文与记忆系统.md)） |
| 多轮对话 | conversation.history | 同 sid 进程内累积 |
| 当次发送视图 | api_conv | 单次 LLM 调用（Layer1 可裁剪） |

### 5.6 权限/提问如何挂起再继续

```text
Agent yield PermissionRequest(future=...)
  → serialize_event: Future 换成 request_id=str(id(future))
  → Session.register_future(request_id, future)
  → WS 推给前端

前端用户点允许/拒绝
  → POST /api/permission/{sid} {request_id, decision...}
  → Session.resolve_future → future.set_result(...)
  → Agent 从 await future 处继续执行工具
```

AskUser 同理：`POST /api/askuser/{sid}`。

---

## 6. 路由与协议清单

### 6.1 路由声明方式

`routes/core.py` 用 `HttpRouteSpec` / `WebSocketRouteSpec` 声明，`build_routes()` 转成 Starlette 路由，并 `assert_no_removed_route_paths` 防止复活已删除能力。

### 6.2 HTTP 端点（当前代码）

#### 健康 / 配置 / 技能 / 设置

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 健康检查（公开） |
| GET/POST | `/api/config` | 读/写模型配置 |
| GET/POST | `/api/skills` | 技能列表 / 创建 |
| POST | `/api/skills/{name}/toggle` | 开关技能 |
| DELETE | `/api/skills/{name}` | 删除技能 |
| GET/POST | `/api/settings/mcp` | MCP 列表 / 添加 |
| POST | `/api/settings/mcp/{name}/toggle` | 开关 MCP |
| DELETE | `/api/settings/mcp/{name}` | 删除 MCP |
| GET/POST | `/api/settings/memory` | 记忆设置 |
| GET/POST | `/api/settings/qqbot` | QQ Bot 桩（未支持） |
| GET/POST | `/api/settings/telegrambot` | Telegram Bot 桩（未支持） |

#### 会话 / 任务 / 交互

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/session` | 创建会话 |
| GET | `/api/sessions` | 列会话 |
| GET/DELETE | `/api/session/{sid}` | 会话信息 / 关闭 |
| GET | `/api/session/{sid}/status` | 状态 |
| POST | `/api/session/{sid}/mode` | 权限模式 |
| POST | `/api/session/{sid}/cancel` | 取消前台任务 |
| POST | `/api/task` | 启动一轮 Agent |
| POST | `/api/permission/{sid}` | 回权限 |
| POST | `/api/askuser/{sid}` | 回 AskUser |
| POST | `/api/compact/{sid}` | 手动压缩 |

#### 后台任务 / worktree / 文件

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/session/{sid}/tasks` | 后台任务列表 |
| POST | `/api/session/{sid}/tasks/{task_id}/cancel` | 取消后台任务 |
| GET/POST | `/api/session/{sid}/worktrees` | 列表 / 创建 worktree |
| POST | `/api/session/{sid}/worktrees/{name}/enter` | 进入 worktree |
| POST | `/api/session/{sid}/worktrees/exit` | 退出 worktree |
| GET | `/api/fs/{sid}` | 列目录（相对 work_dir） |

#### A2A

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/.well-known/agent-card.json` | Agent Card（公开） |
| GET | `/a2a/agent-card.json` | 同上 |
| POST | `/a2a/rpc` | JSON-RPC 2.0 |
| POST | `/a2a/message:send` | REST 发消息 |
| GET | `/a2a/tasks/{task_id}` | 查任务 |
| POST | `/a2a/tasks/{task_id}:cancel` | 取消任务 |

#### WebSocket

| 路径 | 功能 |
|------|------|
| `/api/stream/{sid}` | 事件回放 + 实时推送；上行 `{"action":"cancel"}` |

### 6.3 WebSocket 帧格式

下行统一：

```json
{
  "type": "StreamText",
  "task_id": "1a2b3c4d",
  "data": { "text": "..." }
}
```

`type` 多为 `AgentEvent` 类名，另有控制帧：

| type | 含义 |
|------|------|
| `SessionNotFound` | sid 不存在，随后 close 4404 |
| `ReplayDone` | 历史事件已推完，后续为实时 |
| `UserMessage` | Daemon 记录的用户消息（展示用） |
| `LoopComplete` / 任务取消/错误包装 | 任务收尾 |

`serialize_event`（`daemon/serialize.py`）：

- dataclass → `{type, task_id, data}`
- `future` 字段替换为 `request_id` + `resolved`

### 6.4 事件日志尾随算法

`routes/stream.py` 大致逻辑：

```text
accept WS
log_list = get_event_log(sid)
idx = 0
循环:
  若 idx < len(log_list): 推送新事件
  否则: 若未标记则推 ReplayDone；sleep 短间隔
并行 listen_client_actions 收 cancel
```

这是 **内存 list 轮询 tail**，不是 SSE，也不是独立消息队列中间件。

---

## 7. 请求处理模式

### 7.1 JSON body 解析

`request_body.py` + 各 `parse_*_body`：

```text
request.json()
  → 字段校验（required_string_field / string_field）
  → dataclass body
  → 失败则 400 JSON error
```

### 7.2 路由处理模板

```python
async def create_session(request):
    server = daemon_server(request)
    parsed = await parse_json_object(request, parse_create_session_body)
    if not parsed.ok:
        return parsed.error_response()
    sid = await server.init_session(...)
    return JSONResponse({"session_id": sid, **server.session_info(sid)})
```

### 7.3 上下文取值

`request_context.py`：

- `daemon_server(scope)` → `app.state.server`
- `a2a_bridge(scope)` → `app.state.a2a_bridge`
- `path_param` / `query_param`

---

## 8. 持久化布局

```text
~/.mozilcode/daemon_sessions/
  {sid}/
    meta.json      # work_dir, title, provider_name, created_at...
    events.jsonl   # 追加写的序列化事件
```

`SessionStore`：

- `validate_session_id`：`[A-Za-z0-9_-]{1,64}`
- meta 原子写
- events 增量 append（`persisted_count` 记录已写条数）

**注意：conversation.history 不在此目录。**

---

## 9. 配置与会话的关系

`DaemonServer.config_application_status()` 语义：

```json
{
  "applies_to": "new_sessions",
  "active_sessions_unchanged": <当前 runtime 数>
}
```

含义：改全局 config 主要影响**新会话**；已创建 runtime 的 Agent/Client 不会自动热替换。

会话级 provider 选择：创建时 `provider_name` 会通过 `_select_provider` 重排 providers 列表再 `create_agent_from_config`。

---

## 10. 与 TUI / A2A 的差异

| 入口 | 会话持有 | 通信 |
|------|----------|------|
| TUI `app.py` | 进程内单个/少量 conversation | 无 HTTP，直接消费 `AgentEvent` |
| Daemon+GUI | 多 sid 并行 runtime | HTTP + WS |
| A2A | Bridge 调 `init_session`/`start_task` | HTTP JSON-RPC/REST，内部仍用 Daemon |

---

## 11. 完整时序：从打开 GUI 到第二轮对话

```text
1. 启动 daemon（work_dir=某默认目录）
2. GUI POST /api/session {work_dir: 项目路径}
     → sid, meta.work_dir=项目, Agent 焊死到该目录
3. GUI WS /api/stream/{sid}
     → 回放（空）→ ReplayDone → 等待
4. 用户发消息1
     POST /api/task {sid, prompt:U1}
     runner: history=[U1]; agent.run
     WS: UserMessage, StreamText..., ToolUse..., LoopComplete
5. 用户发消息2
     POST /api/task {sid, prompt:U2}
     runner: history=[U1,A1,...,U2]
     模型带着完整多轮上下文继续
6. 若中途 PermissionRequest
     WS 推事件 → 用户点允许
     POST /api/permission/{sid} → Future 完成 → 工具继续
```

---

## 12. 排障清单

| 现象 | 可能原因 |
|------|----------|
| WS 立刻 SessionNotFound | sid 未创建或已删除 |
| 401 / WS 1008 | 需要 Bearer/token，或 Origin 不在白名单 |
| 工具总在错误目录读写 | 创建会话时 work_dir 传错 / worktree 状态 |
| UI 有历史但模型“失忆” | Daemon 重启后 history 未恢复，仅 events 回放 |
| 发 task 无流式输出 | 未连对应 sid 的 WS，或连错会话 |
| 权限点了没反应 | request_id 不匹配 / session 已关闭 / future 已 done |
| 改 config 不生效 | 只影响新会话，旧 runtime 仍用旧 client |

---

## 13. 相关代码地图

```text
daemon/server.py                 启动与中间件
daemon/server_state.py           DaemonServer 门面
daemon/session/lifecycle_actions 创建/懒恢复
daemon/session/runtime.py        DaemonSessionRuntime
daemon/session/records.py        meta + event_logs
daemon/session/store.py          磁盘
daemon/session/core.py           Session / SessionManager
daemon/tasks/runner.py           追加 prompt + agent.run
daemon/serialize.py              事件 JSON
daemon/routes/core.py            路由表
daemon/routes/stream.py          WS
agent/factory.py                 work_dir → Agent 装配
conversation.py                  真 history
```

---

## 14. 一句话总结

**Daemon 用 `session_id` 索引一套内存 runtime；用 `meta.work_dir` 绑定项目；用同一个 `ConversationManager` 追加消息来接多轮上下文；用 `event_logs` 服务前端；HTTP 发命令，WebSocket 推事件。**

补充：权限模式切换、Future 回传、任务取消等“把 Agent 拴住”的协议视角，见 [11-驾驭工程](./11-驾驭工程.md)。