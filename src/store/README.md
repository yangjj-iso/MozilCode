# store

`store` 是全局状态管理层，主要服务 UI。

## 可能职责

- 当前聊天消息流。
- Agent 当前状态。
- 工具调用展示状态。
- SSH 连接状态。
- 用户界面偏好。

## 重要边界

`core` 不应该依赖 `store`。

推荐：

```text
core -> event-bus -> store -> UI
```

不推荐：

```text
core -> store
```

## MVP 状态

第一期可以先不引入复杂 store。TUI 可以直接订阅 EventBus 并渲染。
