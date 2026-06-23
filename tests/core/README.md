# tests/core

`tests/core` 存放核心层测试。

## MVP 测试目标

- Agent 可以直接回答。
- Agent 可以调用工具并继续推理。
- 未知工具调用会返回错误给模型。
- 高风险工具会触发确认。
- 用户拒绝确认时不会执行工具。
- 达到最大步数时会停止。

## 测试方式

不要在 core 测试里调用真实模型。

推荐使用：

- Fake LLM。
- Fake Tool。
- Fake Confirmation。
- 内存 EventBus。

这样可以保证核心逻辑稳定、快速、可重复测试。
