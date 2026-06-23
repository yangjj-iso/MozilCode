# docs

`docs` 用来存放产品、架构和研发过程文档。

## 职责

- PRD。
- 架构设计说明。
- 技术选型记录。
- 安全策略说明。
- 开发里程碑和验收标准。
- 远程控制、设备绑定和云端控制面设计。

## 不放什么

- 不放运行时代码。
- 不放构建产物。
- 不放密钥、Token、私有配置。

## MVP 建议文档

- `PRD-MVP.md`: 第一期 MVP 产品需求文档。
- `ARCHITECTURE.md`: 核心架构和模块依赖关系。
- `SECURITY.md`: 文件和 Shell 工具的安全边界。
- `REMOTE-CONTROL.md`: 手机端控制任务、本地 Runtime 和 Java 云端中继设计。
- `CLOUD-CONTROL-PLANE.md`: 登录、配额、模型网关、策略下发和审计设计。
