# 05 - Daemon HTTP/WebSocket 服务

## 1. 概述

Daemon 是一个基于 Starlette 的本地 HTTP + WebSocket 服务器，它将 Agent 核心引擎暴露为网络接口，让 GUI、CLI、A2A 客户端等前端能够通过标准 HTTP 协议与之交互。

对应代码：`mozilcode/daemon/`

## 2. 基础概念

### 2.1 HTTP 协议基础

HTTP（HyperText Transfer Protocol）是 Web 通信的基础协议。一次 HTTP 交互包含请求和响应：

```
请求:
  POST /api/session HTTP/1.1       ← 方法 + 路径
  Content-Type: application/json   ← 请求头
  {"work_dir": "/project"}          ← 请求体

响应:
  HTTP/1.1 200 OK                   ← 状态码
  Content-Type: application/json    ← 响应头
  {"session_id": "abc123"}          ← 响应体
```

常见 HTTP 方法：
| 方法 | 语义 | 本项目用途 |
|------|------|-----------|
| GET | 获取资源 | 获取会话列表、状态 |
| POST | 创建/操作 | 创建会话、启动任务 |
| DELETE | 删除资源 | 关闭会话、删除技能 |

### 2.2 WebSocket 协议

WebSocket 是一种全双工通信协议，允许服务器主动推送消息给客户端。本项目用它实现事件流式传输。

```
HTTP: 客户端请求 → 服务器响应（单向，一问一答）
WebSocket: 客户端 ←→ 服务器（双向，持续连接）
```

在 Agent 场景中，WebSocket 用于实时推送 Agent 事件（流式文本、工具调用、工具结果等）。

### 2.3 Starlette 框架

Starlette 是一个轻量级 ASGI（Asynchronous Server Gateway Interface）Web 框架，Uvicorn 是其推荐的 ASGI 服务器。

```python
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
import uvicorn

async def hello(request):
    return JSONResponse({"hello": "world"})

async def ws_handler(websocket):
    await websocket.accept()
    await websocket.send_json({"event": "connected"})
    await websocket.close()

app = Starlette(routes=[
    Route("/api/hello", hello, methods=["GET"]),
    WebSocketRoute("/ws", ws_handler),
])

uvicorn.run(app, host="127.0.0.1", port=7800)
```

### 2.4 CORS（跨域资源共享）

浏览器的同源策略会阻止网页请求不同源（协议+域名+端口）的 API。CORS 是解决这个问题的标准方式——服务器在响应头中声明允许哪些来源访问。

```
浏览器: http://localhost:1420 (Vue 前端)
API:    http://127.0.0.1:7800 (Daemon)

→ 不同端口 = 不同源 = 被浏览器拦截

解决: Daemon 添加 CORS 中间件
→ 响应头: Access-Control-Allow-Origin: http://localhost:1420
→ 浏览器放行
```

## 3. 服务架构

```
┌─────────────────────────────────────────────────┐
│              Daemon Server (server.py)          │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │     Starlette App + CORS Middleware     │    │
│  │                                         │    │
│  │  ┌──────────┐  ┌──────────┐            │    │
│  │  │ HTTP     │  │ WebSocket│            │    │
│  │  │ Routes   │  │ Routes   │            │    │
│  │  └────┬─────┘  └────┬─────┘            │    │
│  │       │              │                  │    │
│  │  ┌────┴──────────────┴──────────────┐   │    │
│  │  │       DaemonServer (状态)         │   │    │
│  │  │  ┌─────────────────────────┐     │   │    │
│  │  │  │    SessionManager       │     │   │    │
│  │  │  │    SessionStore         │     │   │    │
│  │  │  │    ActiveTaskRegistry   │     │   │    │
│  │  │  │    AgentTaskRunner      │     │   │    │
│  │  │  │    PendingPromptRegistry│     │   │    │
│  │  │  └─────────────────────────┘     │   │    │
│  │  └──────────────────────────────────┘   │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  Uvicorn (ASGI Server)                          │
│  http://127.0.0.1:7800                         │
└─────────────────────────────────────────────────┘
```

## 4. 路由系统

### 4.1 路由声明

路由在 `routes/core.py` 中用 dataclass 声明式定义：

```python
@dataclass(frozen=True)
class HttpRouteSpec:
    path: str                        # URL 路径
    endpoint: Callable[..., Any]     # 处理函数
    methods: tuple[str, ...]         # 允许的 HTTP 方法

HTTP_ROUTES: tuple[HttpRouteSpec, ...] = (
    HttpRouteSpec("/api/health", health, ("GET",)),
    HttpRouteSpec("/api/session", create_session, ("POST",)),
    HttpRouteSpec("/api/sessions", list_sessions, ("GET",)),
    HttpRouteSpec("/api/task", start_task, ("POST",)),
    HttpRouteSpec("/api/session/{sid}/status", session_status, ("GET",)),
    HttpRouteSpec("/api/session/{sid}", close_session, ("DELETE",)),
    HttpRouteSpec("/api/config", get_config, ("GET",)),
    HttpRouteSpec("/api/config", save_config, ("POST",)),
    HttpRouteSpec("/api/skills", list_skills, ("GET",)),
    # ... 更多路由
)
```

### 4.2 完整 API 端点表

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 获取模型配置 |
| POST | `/api/config` | 保存模型配置 |
| GET | `/api/skills` | 获取技能列表 |
| POST | `/api/skills` | 创建技能 |
| POST | `/api/skills/{name}/toggle` | 开关技能 |
| DELETE | `/api/skills/{name}` | 删除技能 |
| GET | `/api/settings/mcp` | 获取 MCP 服务器列表 |
| POST | `/api/settings/mcp` | 添加 MCP 服务器 |
| POST | `/api/settings/mcp/{name}/toggle` | 开关 MCP 服务器 |
| DELETE | `/api/settings/mcp/{name}` | 删除 MCP 服务器 |
| GET | `/api/settings/memory` | 获取记忆配置 |
| POST | `/api/settings/memory` | 保存记忆配置 |
| POST | `/api/session` | 创建会话 |
| GET | `/api/sessions` | 列出会话 |
| POST | `/api/task` | 启动任务 |
| GET | `/api/session/{sid}/status` | 查询会话状态 |
| POST | `/api/session/{sid}/mode` | 切换权限模式 |
| POST | `/api/session/{sid}/cancel` | 取消当前任务 |
| POST | `/api/permission/{sid}` | 响应权限请求 |
| POST | `/api/askuser/{sid}` | 响应用户提问 |
| POST | `/api/compact/{sid}` | 手动压缩上下文 |
| DELETE | `/api/session/{sid}` | 关闭会话 |
| WS | `/api/stream/{sid}` | 流式事件推送 |

### 4.3 路由构建

```python
def build_routes() -> list[BaseRoute]:
    # 安全检查：确保没有已移除的路由路径
    assert_no_removed_route_paths(
        [spec.path for spec in HTTP_ROUTES] + [spec.path for spec in WEBSOCKET_ROUTES]
    )
    routes: list[BaseRoute] = [
        Route(spec.path, spec.endpoint, methods=list(spec.methods))
        for spec in HTTP_ROUTES
    ]
    routes.extend(
        WebSocketRoute(spec.path, spec.endpoint)
        for spec in WEBSOCKET_ROUTES
    )
    return routes
```

## 5. 请求处理模式

### 5.1 请求体解析

项目实现了统一的 JSON 请求体解析工具：

```python
@dataclass(frozen=True)
class ParsedJsonObject(Generic[T]):
    value: T | None = None
    error: JSONResponse | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

async def parse_json_object(request, parser) -> ParsedJsonObject[T]:
    # 1. 读取 JSON
    try:
        payload = await request.json()
    except ValueError:
        return ParsedJsonObject(error=error_response("Invalid JSON body", 400))

    # 2. 解析和校验
    try:
        return ParsedJsonObject(value=parser(payload))
    except BodyFieldError as e:
        return ParsedJsonObject(error=bad_request_response(str(e)))
```

### 5.2 路由处理函数示例

```python
async def create_session(request: Request) -> JSONResponse:
    server = daemon_server(request)    # 从 app.state 获取 DaemonServer
    parsed = await parse_json_object(request, parse_create_session_body)
    if parsed.error is not None:
        return parsed.error
    body = parsed.unwrap()
    try:
        sid = await server.init_session(body.session_id, body.work_dir)
    except ValueError as e:
        return bad_request_response(str(e))
    return JSONResponse({"session_id": sid, **server.session_info(sid)})
```

### 5.3 上下文工具函数

```python
def daemon_server(scope: Any) -> Any:
    """从 Starlette scope 获取 DaemonServer 实例。"""
    return scope.app.state.server

def path_param(scope: Any, name: str) -> str:
    """获取 URL 路径参数，如 /api/session/{sid} 中的 sid。"""
    return str(scope.path_params[name])

def query_param(request: Request, name: str, default: str = "") -> str:
    """获取 URL 查询参数，如 ?path=src 中的 path。"""
    value = request.query_params.get(name)
    return default if value is None else value
```

## 6. WebSocket 事件流

### 6.1 连接生命周期

```python
async def stream_events(websocket: WebSocket) -> None:
    await websocket.accept()          # 1. 接受连接
    sid = path_param(websocket, "sid")
    server = daemon_server(websocket)

    # 2. 回放历史事件
    log_list = server.get_event_log(sid)
    if log_list is None:
        await websocket.send_json({"type": "SessionNotFound"})
        await websocket.close(code=4404)
        return

    # 3. 启动客户端消息监听（处理 cancel 等操作）
    listener = asyncio.create_task(listen_client_actions(websocket, ...))

    # 4. 尾随事件日志（实时推送新事件）
    idx = 0
    while not disconnected.is_set():
        if idx < len(log_list):
            # 推送新事件
            batch = log_list[idx:]
            idx = len(log_list)
            for event in batch:
                await websocket.send_json(event)
        else:
            # 发送 ReplayDone 标记
            if not replay_marked:
                await websocket.send_json({"type": "ReplayDone"})
                replay_marked = True
            await asyncio.sleep(0.02)  # 轮询间隔
```

### 6.2 事件日志

每个会话有一个事件日志（`list[dict | None]`），Agent 的每个事件都会被序列化并追加到日志中。WebSocket 客户端通过尾随（tail）这个日志来获取实时事件：

```python
# server_state.py
def _emit(self, sid: str, event: dict | None) -> None:
    """将序列化的事件追加到会话日志。WebSocket 流会尾随它。"""
    self._records.emit(sid, event)
```

### 6.3 客户端操作

WebSocket 客户端可以发送 JSON 消息来执行操作（如取消任务）：

```python
CLIENT_ACTIONS = {"cancel"}

def parse_client_action(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    action = payload.get("action")
    return action if action in CLIENT_ACTIONS else ""

async def listen_client_actions(websocket, server, sid, disconnected):
    while True:
        action = parse_client_action(await websocket.receive_text())
        if action == "cancel":
            server.cancel_active_task(sid)
```

## 7. DaemonServer 状态管理

`DaemonServer` 是核心状态容器，持有所有会话和运行时状态：

```python
class DaemonServer:
    def __init__(self, config, work_dir, hook_engine, session_store):
        self.config = config
        self.work_dir = work_dir
        self.session_mgr = SessionManager()           # 会话管理
        self._records = SessionRecords(session_store) # 会话记录（持久化）
        self._agents: dict[str, DaemonSessionRuntime] = {}  # 会话运行时
        self._active_tasks = ActiveTaskRegistry()      # 活跃任务
        self._pending_prompts = PendingPromptRegistry() # 待处理的权限/用户请求
        self._agent_task_runner = AgentTaskRunner(...)  # 任务执行器
```

### 关键方法

```python
    async def init_session(self, session_id=None, work_dir=None) -> str:
        """创建新会话，返回 session_id。"""

    async def ensure_agent(self, sid: str) -> bool:
        """确保会话有 Agent 实例（懒创建）。"""

    async def start_task(self, sid: str, prompt: str) -> str:
        """启动 Agent.run() 作为后台任务。返回 task_id。"""

    async def resolve_permission(self, sid, request_id, response) -> bool:
        """解决权限请求（用户点击了允许/拒绝）。"""

    def status(self, sid: str) -> dict:
        """获取会话状态。"""
```

## 8. CORS 配置

```python
def create_app(config, work_dir, hook_engine, session_store) -> Starlette:
    server = DaemonServer(config, work_dir, hook_engine, session_store)
    app = Starlette(routes=build_routes())

    # 添加 CORS 中间件，允许前端跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],         # 允许所有来源
        allow_methods=["*"],         # 允许所有 HTTP 方法
        allow_headers=["*"],         # 允许所有请求头
        allow_credentials=True,      # 允许携带凭证
    )

    app.state.server = server
    return app
```

## 9. 前后端对接

### Vite 代理配置

`mewcode-gui/vite.config.js` 配置了开发代理，将 `/api` 请求转发到 daemon：

```javascript
export default defineConfig(({ mode }) => {
  const daemonTarget = env.VITE_MEWCODE_DAEMON_HTTP || 'http://127.0.0.1:7800';
  return {
    server: {
      port: 1420,
      proxy: {
        '/api': {
          target: daemonTarget,    // 转发到 daemon
          changeOrigin: true,
          ws: true,                // WebSocket 代理
        },
      },
    },
  };
});
```

但前端代码中有些请求直接用了完整 URL（`http://127.0.0.1:7800/api/...`），这就需要 CORS。如果改用相对路径（`/api/...`），则走 Vite 代理，不会有 CORS 问题。
