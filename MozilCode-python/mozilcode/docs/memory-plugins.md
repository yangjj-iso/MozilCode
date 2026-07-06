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

配置中的 `name` 必须唯一；provider 实例最终暴露的 `name` 也必须唯一。这样 `MemoryHub` 的上下文标题、状态输出和错误隔离都能稳定指向同一个 provider。

## 核心组件

- `mozilcode/memory/providers/base.py`：定义 `MemoryProvider` 协议、`MemoryScope`、`MemoryEvent`、`MemoryItem`。
- `mozilcode/memory/providers/contract.py`：校验 provider 元数据/方法合约，并按名称注入构造函数参数。
- `mozilcode/memory/providers/hub.py`：聚合多个 provider，并隔离单个 provider 的异常和超时。
- `mozilcode/memory/providers/markdown.py`：内置 Markdown provider，兼容原来的 `MemoryManager`。
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
