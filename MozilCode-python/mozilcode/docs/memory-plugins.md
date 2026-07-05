# 记忆系统插件化

MozilCode 的长期记忆入口是 `MemoryHub`。Agent 不直接依赖具体记忆实现，而是通过一组 `MemoryProvider` 加载上下文、观察对话事件、搜索和写入记忆。

## 标准接入边界

一个记忆模块只要实现 `MemoryProvider` 协议，就属于标准接入。Agent 只认识这些方法和事件，不为具体 provider 写特殊分支：

| 方法 | 调用时机 | 返回/行为 |
|---|---|---|
| `initialize()` | provider 首次使用前 | 建立连接、检查 sidecar、初始化索引 |
| `load_context(query, scope)` | 每次请求进入模型前 | 返回要注入 system reminder 的文本 |
| `observe(event)` | Agent 生命周期事件 | 接收 `turn_completed`、`turn_committed`、`session_end` 等事件 |
| `search(query, limit)` | 需要显式检索时 | 返回 `MemoryItem` 列表 |
| `write(item)` | 外部主动写入记忆时 | 写入 provider 自己的后端 |
| `clear(scope)` | 清理记忆时 | 清空指定范围 |
| `shutdown()` | session/进程结束时 | flush 或释放资源 |

标准事件常量从 `mozilcode.memory.providers` 导出：

```python
MEMORY_EVENT_TURN_COMPLETED = "turn_completed"
MEMORY_EVENT_TURN_COMMITTED = "turn_committed"
MEMORY_EVENT_SESSION_END = "session_end"
```

第三方 provider 不需要改 Agent，只需要通过配置声明：

```yaml
memory:
  providers:
    - name: my-memory
      type: python
      module: my_memory.provider
      class: MyMemoryProvider
```

## 核心组件

- `mozilcode/memory/providers/base.py`：定义 `MemoryProvider` 协议、`MemoryScope`、`MemoryEvent`、`MemoryItem`。
- `mozilcode/memory/providers/hub.py`：聚合多个 provider，并隔离单个 provider 的异常和超时。
- `mozilcode/memory/providers/markdown.py`：内置 Markdown provider，兼容原来的 `MemoryManager`。
- `mozilcode/memory/providers/tencentdb.py`：内置 TencentDB Agent Memory Gateway provider，它只是标准 provider 的一个实现。
- `mozilcode/memory/providers/loader.py`：从配置创建 `MemoryHub`，支持声明式内置 provider registry 和 Python provider。

默认配置等价于：

```yaml
memory:
  enabled: true
  providers:
    - name: markdown
      type: builtin.markdown
      enabled: true
      config: {}
```

关闭记忆：

```yaml
memory:
  enabled: false
```

接入自定义 Python provider：

```yaml
memory:
  enabled: true
  providers:
    - name: vector
      type: python
      module: my_memory.provider
      class: VectorMemoryProvider
      enabled: true
      config:
        top_k: 8
```

Provider 类建议继承 `BaseMemoryProvider`，并实现需要的异步方法：

```python
from mozilcode.memory.providers import BaseMemoryProvider, MemoryEvent, MemoryItem, MemoryScope


class VectorMemoryProvider(BaseMemoryProvider):
    name = "vector"
    kind = "python.vector"
    version = "1.0"

    def __init__(self, project_root: str, config: dict) -> None:
        self.project_root = project_root
        self.config = config

    async def load_context(self, query: str, scope: MemoryScope) -> str:
        return ""

    async def observe(self, event: MemoryEvent) -> None:
        if event.type == "turn_committed":
            ...

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        return []
```

## TencentDB Agent Memory

TencentDB Agent Memory 是 Node.js/OpenClaw/Hermes 侧的记忆系统。MozilCode 里的 `TencentDBMemoryProvider` 是一个标准 `MemoryProvider` 实现；它不改 Agent 主循环，也不把 Node 包作为 Python 核心依赖，而是通过 TencentDB Agent Memory 的本地 HTTP Gateway 接入：

- `GET /health`
- `POST /recall`
- `POST /capture`
- `POST /search/memories`
- `POST /session/end`

先按官方方式启动 Gateway，默认监听 `http://127.0.0.1:8420`。然后在 MozilCode 配置里启用：

```yaml
memory:
  enabled: true
  providers:
    - name: markdown
      type: builtin.markdown
      enabled: true

    - name: tencentdb
      type: builtin.tencentdb
      enabled: true
      config:
        base_url: http://127.0.0.1:8420
        # 如果 Gateway 设置了 TDAI_GATEWAY_API_KEY，这里填写同一份值。
        api_key: ""
        session_prefix: mozilcode
        capture: true
        recall: true
```

如果你希望 MozilCode 自动拉起 Gateway，可以配置：

```yaml
memory:
  enabled: true
  providers:
    - name: tencentdb
      type: builtin.tencentdb
      config:
        gateway_cmd: "node --import tsx C:/path/to/tdai-memory-openclaw-plugin/src/gateway/server.ts"
        gateway_cwd: "C:/path/to/tdai-memory-openclaw-plugin"
        auto_start: true
```

Gateway 的 LLM、Embedding、SQLite/TCVDB 后端仍由 TencentDB Agent Memory 自己的配置管理，例如 `TDAI_LLM_*`、`TDAI_DATA_DIR` 或 `tdai-gateway.json`。MozilCode provider 只负责把对话轮次和召回请求转发过去。

这样核心协议稳定，默认 Markdown 记忆继续工作，TencentDB Agent Memory、向量库、数据库或云端记忆都可以作为可替换模块存在。
