# src

`src` 是 MozilCode 的 TypeScript 源码根目录。

## 模块划分

- `core`: Agent 核心逻辑。
- `tools`: Agent 可调用的工具。
- `providers`: LLM Provider 适配。
- `adapters`: TUI/GUI 等外部交互适配器。
- `context`: 项目上下文感知。
- `memory`: 长期记忆。
- `auth`: 鉴权和配额。
- `store`: UI 状态。
- `types`: 全局类型补充。

## 依赖方向

推荐依赖方向：

```text
adapters -> core -> ports
providers -> core/ports
tools -> core/ports
index.ts -> 组装所有模块
```

禁止依赖方向：

```text
core -> adapters
core -> providers
core -> tools 具体实现
core -> store
```
