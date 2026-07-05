# 记忆系统插件化

MozilCode 的长期记忆入口是 `MemoryHub`。Agent 不直接依赖具体记忆实现，而是通过一组 `MemoryProvider` 加载上下文、观察对话事件、搜索和写入记忆。

## 核心组件

- `mozilcode/memory/providers/base.py`：定义 `MemoryProvider` 协议、`MemoryScope`、`MemoryEvent`、`MemoryItem`。
- `mozilcode/memory/providers/hub.py`：聚合多个 provider，并隔离单个 provider 的异常和超时。
- `mozilcode/memory/providers/markdown.py`：内置 Markdown provider，兼容原来的 `MemoryManager`。
- `mozilcode/memory/providers/loader.py`：从配置创建 `MemoryHub`，支持内置 provider 和 Python provider。

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

## Tencent agent-memory 的接入方式

Tencent 的 `agent-memory` 不应直接绑进 MozilCode 核心依赖。推荐把它做成一个独立 Python provider：

1. Provider 内部初始化 agent-memory 的存储、检索和写入组件。
2. `load_context()` 将检索结果渲染成适合注入 system reminder 的文本。
3. `observe(turn_committed)` 从对话里抽取可沉淀内容并写入 agent-memory。
4. 配置中通过 `type: python`、`module`、`class` 启用。

这样核心协议稳定，默认 Markdown 记忆继续工作，向量库、数据库、云端记忆或 agent-memory 都可以作为可替换模块存在。
