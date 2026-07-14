# MozilCode Cloud

产品化云端控制台：账号登录、套餐/用量、模型目录、管理员配置。
**网页端不提供对话，也不选默认模型**（类似 Cursor 账号页）；模型选择与 AI 对话只在本地客户端。

默认数据库：**PostgreSQL**。

## 产品模型

```
本地客户端                     云端网页 / API
────────                       ─────────────
登录账号  ──────────────────► JWT / 账号页（套餐·用量）
GET /api/models  ◄──────────── 已启用模型目录（只读，无密钥）
客户端自己选模型
对话请求 body.model ─────────► POST /api/gateway/chat/completions
                              │  （仅 API，网页无对话 UI）
管理员后台                     ├─ 校验订阅/配额/限流
配置 Provider + API Key        ├─ 按目录解析 model 并注入密钥
发布可用模型                   └─ 转发上游并计费
```

- **云端网页（用户）**：账号、套餐、用量、模型目录。**无对话、无默认模型选择、无管理入口**。
- **管理入口（独立）**：`/ops`，仅管理员可进；用户侧控制台不显示。
- **本地客户端**：登录同一账号 → 拉目录 → 自己选模型 → 对话。
- **用户**：不能自定义 model / API Key。
- **管理员**：配置提供商 `base_url` + `api_key`，启用/停用模型。

默认管理员（首次启动种子）：

- 邮箱：`admin@mozilcode.local`
- 密码：`admin123`
- 入口：http://127.0.0.1:8000/ops

## Docker 启动（推荐）

```powershell
cd mozilcode-cloud

# 1) 打包 jar
mvn -DskipTests package

# 2) 构建镜像
docker compose build cloud

# 3) 启动 PG + Cloud
docker compose up -d
```

- 用户控制台：http://127.0.0.1:8000/
- 管理入口：http://127.0.0.1:8000/ops
- 健康检查：http://127.0.0.1:8000/api/health
- Postgres：`localhost:5432` / db=`mozilcode` / user=`postgres` / pass=`postgres`

停止：

```powershell
docker compose down
```

## 非 Docker 启动

先准备 PostgreSQL：

```sql
CREATE DATABASE mozilcode;
```

```powershell
cd mozilcode-cloud
mvn spring-boot:run
```

环境变量（可选）：

| 配置 | 默认值 |
|------|--------|
| `MOZILCODE_DB_URL` | `jdbc:postgresql://127.0.0.1:5432/mozilcode` |
| `MOZILCODE_DB_USER` | `postgres` |
| `MOZILCODE_DB_PASSWORD` | `postgres` |

## 主要能力

| 模块 | 说明 |
|------|------|
| Auth | 注册/登录，JWT 72h，角色 `user` / `admin` |
| Plans | 套餐列表 + 兑换码开通订阅 |
| Models | 云端可用模型目录（只读发布）；**不在云端选默认模型** |
| Admin | 提供商 / 模型 / 用户管理；密钥仅管理员可见掩码 |
| Gateway | `/api/gateway/**` 代理上游：按请求 `model` 解析目录、服务端取钥 / 计费 / 限流 |
| Usage | 按模型 / 近 7 日 / 最近请求 |

## 用户侧 API（本地客户端对接）

1. `POST /api/auth/login` → `token`
2. `GET /api/models` + `Authorization: Bearer <token>` → 可用模型目录
3. `POST /api/redeem` `{ "code": "..." }` → 开通套餐（首次）
4. `POST /api/gateway/chat/completions` 请求体带 `model`（OpenAI 兼容；**不要**传上游 API Key）

## 管理侧 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/overview` | 运营总览 |
| GET/POST | `/api/admin/providers` | 提供商列表 / 创建 |
| PUT/DELETE | `/api/admin/providers/{id}` | 更新密钥/状态 / 删除 |
| POST | `/api/admin/models/{id}/test` | 测试模型可用性（最小 chat/completions） |
| GET/POST | `/api/admin/models` | 模型列表 / 创建 |
| PUT/DELETE | `/api/admin/models/{id}` | 更新 / 删除 |
| GET | `/api/admin/users` | 用户列表 |

## 本地兑换码（development）

- `MozilCode-FREE-500K`
- `MozilCode-PRO-5M`
- `MozilCode-MAX-20M`

## 测试

```powershell
mvn test
```

单元/冒烟测试用 H2 `MODE=PostgreSQL` 内存库，不依赖本机 PostgreSQL。