# 天健湖 · 框架说明（v0.3.0）

> v0.1 做了「总体框架」；v0.2 补上了**账号体系、按用户的数据隔离**，并把所有运行期数据收进仓库根的 `data/`。
> v0.3 把独立子项目「情景式英语对话」全量移植为 `english` 能力并入主站；教材库 / 校园雷达 / 联想记忆等
> 能力继续按同一套能力协议逐个接入，**不需要改内核**。
>
> **本文档**：讲内核怎么搭、能力协议怎么用、怎么接入新能力 ｜ **路径**：`docs/FRAMEWORK.md`
> ｜ **状态**：✅ 与 v0.3.0 代码一致 ｜ **读者**：要改代码的人（必读）

---

## 1. 目录与职责

```
apps/server/                     Python 后端（FastAPI）
├── app/
│   ├── main.py                  应用装配：发现能力 → 迁移 → 建表 → 挂路由（公开/受保护）→ 托管前端
│   ├── config.py                配置（TJH_ 环境变量 / .env）、数据目录、会话参数
│   ├── db.py                    SQLite 引擎、会话、迁移执行器、旧数据目录迁移
│   ├── models.py                users / sessions / providers / settings / jobs / capability_state / events
│   ├── core/
│   │   ├── auth.py              密码哈希、会话、current_user / require_admin、注册登录、限流
│   │   ├── capability.py        能力协议 + 自动发现 + 挂载（统一加登录依赖）
│   │   ├── tools.py             Tool / ToolContext / 工具注册表
│   │   ├── llm.py               OpenAI 兼容客户端（按用户解析供应商）
│   │   ├── jobs.py              任务中心（线程池 + 进度 + 取消 + user_id）
│   │   ├── crypto.py            Fernet 加密 API Key（data/secret.key）
│   │   └── errors.py            统一错误 JSON
│   ├── api/
│   │   ├── auth.py              注册 / 登录 / 登出 / 改密 / 配置
│   │   ├── users.py             管理员：成员管理、注册开关
│   │   ├── system.py            信息、能力、工具、事件（按用户）
│   │   ├── providers.py         供应商 CRUD / 测试 / 默认（按用户）
│   │   ├── jobs.py              任务列表 / 取消 / SSE（按用户）
│   │   └── settings.py          站点设置（管理员可写）
│   ├── capabilities/            能力插件（notes 速记、wechat_digest 群聊简报、english 情景英语、library 教材库）
│   ├── migrations/              核心迁移（预留）
│   └── cli.py                   run / doctor / migrate / new-capability / 用户管理
├── requirements.txt
└── .env.example

apps/web/                        React 前端（Vite + Tailwind v4）
├── src/
│   ├── App.tsx                  启动：读配置 → 校验会话 → 工作区数据；未登录进登录页
│   ├── app/                     Shell、Sidebar、Topbar、CommandPalette、router、ThemeToggle
│   ├── components/              Brand、PageHeader、StatCard、Icon、ProviderPanel、CapabilityPanel、UserMenu
│   │   └── ui/                  primitives + overlay（Modal / Dropdown / Toast）
│   ├── capabilities/            前端能力注册表（import.meta.glob）+ 各能力页面
│   ├── lib/                     api.ts（含 auth/admin）、utils.ts
│   ├── pages/                   Login / Home / Settings / Jobs / AdminUsers / NotFound
│   ├── store/app.ts             zustand：初始化、登录态、工作区、主题、通知
│   └── styles.css               设计令牌与动效
└── dist/                        构建产物（后端托管）

data/                            唯一的运行期数据目录（gitignore，见 §5）
docs/  scripts/  Makefile
```

---

## 2. 启动链路

```
uvicorn app.main:app
  └─ create_app()
       ├─ settings.ensure_dirs()              创建 data/、uploads/、cache/
       ├─ _migrate_legacy_data_dir()          旧位置 apps/server/data → 仓库根 data/
       ├─ capabilities.discover()             扫描 app/capabilities/*/capability.py
       ├─ init_db(capabilities.migration_dirs())
       │    ├─ 执行核心迁移 → 各能力 migrations/*.sql（只执行一次）
       │    └─ SQLModel.metadata.create_all() 建核心表
       ├─ capabilities.register_tools()       收集 Tool 进全局注册表
       ├─ 公开路由：/api/health、/api/auth/*
       ├─ 受保护路由：system / providers / jobs / settings / admin（统一 Depends(current_user)）
       └─ 托管 apps/web/dist，其余路径回 index.html
```

开发模式（`make dev`）：后端 8787 + Vite 5174，Vite 把 `/api` 代理到 8787。

---

## 3. 账号、会话与数据隔离

### 3.1 表

| 表 | 说明 |
|---|---|
| `users` | `username`（小写唯一）、`display_name`、`password_hash`（scrypt）、`role`（admin/user）、`is_active`、`last_login_at` |
| `sessions` | 主键是 `sha256(token)`；`user_id`、`expires_at`（默认 30 天）、`last_seen_at`、`user_agent` |

业务表（`providers` / `jobs` / `events` / 能力表）都带 `user_id`；`capability_state` 用 `(user_id, capability_id)` 联合主键。

### 3.2 密码与会话

```python
# core/auth.py
hash_password("...")   # scrypt$n$r$p$salt$digest，每用户独立盐
verify_password(pw, stored)  # 常量时间比较
create_session(db, user, request) -> token   # 库里只存 sha256(token)
resolve_user(db, token) -> User | None       # 校验过期、is_active，每小时刷新 last_seen
```

- Cookie：`tjh_session`，`HttpOnly`、`SameSite=Lax`、`Path=/`，`secure` 由 `TJH_COOKIE_SECURE` 控制。
- 登录限流：默认 5 分钟 8 次（进程内字典，单实例够用）。
- 停用账号 / 重置密码 / 删除成员 → 删除该用户全部 session，已登录设备立即 401。

### 3.3 依赖与保护

```python
from ..core.auth import current_user, require_admin

@router.get("/items")
async def list_items(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return db.exec(select(Note).where(Note.user_id == user.id)).all()
```

- **路由级保护**：`main.py` 给业务路由统一加 `dependencies=[Depends(current_user)]`；能力路由由 `capabilities.mount()` 统一加。
- **管理员保护**：`/api/admin/*` 的 router 级依赖 `require_admin`。
- **数据过滤**：所有查询/写入都必须带 `user_id`；「按 id 取一条」时要校验 `row.user_id == user.id`（否则 404）。
- **工具调用**：`ToolContext.user_id` 由调用方注入，能力工具据此隔离数据。

### 3.4 注册策略

- 首个注册者自动成为 `admin`；之后注册者为 `user`。
- 管理员可关闭自助注册（`PUT /api/admin/registration`）；关闭后仍可在「成员管理」里新建成员。
- 用户名 3–24 位字母/数字/下划线；密码至少 8 位。
- 旧版本（v0.1 单用户）数据库会被自动备份为 `data/app.db.v0.1-<时间>.bak`，再创建多用户新库。

---

## 4. 能力协议

一个能力 = 继承 `Capability` 的类 + 模块级 `CAPABILITY` 实例：

```python
class NotesCapability(Capability):
    manifest = CapabilityManifest(
        id="notes", name="速记", description="...", icon="notebook-pen",
        nav=NavItem(label="速记", path="/cap/notes", order=10),
        settings_schema={...},          # 前端自动渲染设置表单（按用户保存）
    )

    def router(self):         return router              # 挂到 /api/c/notes，自动要求登录
    def migrations_dir(self): return Path(__file__).parent / "migrations"
    def tools(self):          return [Tool(name="create_note", ..., handler=_create_note)]
    async def on_startup(self, app): ...                 # 可选
```

| 项 | 约定 |
|---|---|
| 发现 | 启动扫描 `app/capabilities/*/capability.py`；坏插件只告警 |
| 路由 | 自动挂 `/api/c/<id>`，并统一要求登录 |
| 工具 | 自动进入 `/api/tools`；handler 第一个参数是 `ToolContext` |
| 迁移 | 能力自带 `migrations/*.sql`，按文件名执行一次 |
| 设置 | `settings_schema`（JSON Schema 子集），按用户存 `capability_state` |
| 开关 | 禁用后导航消失、工具不暴露；数据保留 |

> **参考实现**：`english`（情景英语）是目前用到全部协议要素的能力——路由（20 个接口，含 SSE）、
> 14 张迁移表的 SQLite schema、按用户设置（9 项）、3 个 Agent 工具、以及 `agents/` 下 17 个可测试模块。
> 新能力可以先读 `docs/ENGLISH.md`，再对照 `app/capabilities/english/` 抄结构。
>
> **另一个参考**：`library`（教材库）演示了「文件上传 + 任务中心 + 后台解析 + 二次消费」这类
> 非对话型能力怎么写——multipart 上传、`jobs.submit` 异步解析、状态机与告警回填、SSE 问答。
> 契约见 `docs/LIBRARY.md`。

---

## 5. 数据目录 `data/`

```
data/
├── app.db          SQLite 主库（WAL）
├── app.db-wal      WAL 日志（运行时）
├── app.db-shm      共享内存（运行时）
├── secret.key      API Key 加密密钥（0600；必须与库一起备份）
├── uploads/        教材等上传文件（后续能力使用）
└── cache/          解析 / 模型响应缓存
```

- **GitHub 协作**：`.gitignore` 排除 `data/*`（只保留 `data/README.md`）与 `.env`；每个人本地跑自己的实例，代码共享、数据不共享。
- **备份/恢复**：`make backup` → `backups/tianjianhu-*.tar.gz`；恢复时停服务、解压覆盖 `data/`。
- **重置**：`make reset-data FORCE=1`。
- **换位置**：`TJH_DATA_DIR=/srv/tianjianhu-data`。
- **升级迁移**：旧位置 `apps/server/data/` 会在启动时整体搬到 `data/`。

---

## 6. 工具注册表（给 Agent 用）

```python
@dataclass
class ToolContext:
    user_id: int = 0
    capability: str = ""

Tool(
    name="create_note",
    description="把一段内容记成速记",
    parameters={... JSON Schema ...},
    handler=_create_note,        # async def handler(ctx: ToolContext, **kwargs)
    scopes=["notes:write"],      # 预留权限位
    needs_confirm=False,
)
```

- `GET /api/tools` 返回当前用户可见的工具（含所属能力、是否启用）。
- 执行：`await registry.execute(name, args, ToolContext(user_id=user.id))` → `{ok, data}` / `{ok:false, error}`。
- 后续接入 Agent 主循环时，`LLMClient.chat(tools=registry.openai_specs(...))` 即可。

---

## 7. 数据库迁移

- 核心表由 `SQLModel.metadata.create_all()` 创建；能力表由能力 SQL 创建。
- 迁移按文件名排序，记录在 `_migrations`，每个文件作为一个事务执行；请写幂等 SQL（`CREATE TABLE IF NOT EXISTS`）。
- 修改已有表结构时：新增迁移文件（不要改历史迁移），或按版本约定清理数据目录（框架早期）。

---

## 8. 前端能力注册表

```ts
// src/capabilities/notes/index.tsx
const capability: CapabilityModule = {
  id: "notes",
  routes: [{ path: "/cap/notes", element: <NotesPage /> }],
};
export default capability;
```

- **导航与开关以服务端 manifest 为准**（`/api/capabilities`），前端只提供页面。
- 只挂载「已启用」能力的前端路由；设置表单由 `settings_schema` 自动渲染。
- 登录态由 `store/app.ts` 管理：`initialize()` → `/api/auth/config` + `/api/auth/me`；401 时全局事件 `tjh:unauthorized` 会清空登录态回到登录页。

---

## 9. CLI

```bash
cd apps/server
.venv/bin/python -m app.cli run              # 启动
.venv/bin/python -m app.cli doctor           # 环境自检
.venv/bin/python -m app.cli migrate          # 迁移
.venv/bin/python -m app.cli new-capability flashcards --name 记忆卡 --icon brain --order 20

# 账号（适合无浏览器的服务器）
.venv/bin/python -m app.cli create-user admin --admin          # 随机密码并打印
.venv/bin/python -m app.cli list-users
.venv/bin/python -m app.cli set-password admin --password '...'
```

---

## 10. HTTP API（v0.3.0）

**公开**：`GET /api/health`、`GET /api/auth/config`、`POST /api/auth/register`、`POST /api/auth/login`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/logout` | 销毁会话并清 Cookie |
| GET | `/api/auth/me` | 当前用户（未登录 401） |
| PUT | `/api/auth/password` | 改密（会重新签发当前会话） |
| GET | `/api/info` | 版本、当前用户、数据目录（仅管理员可见）、供应商/能力/工具数量 |
| GET | `/api/capabilities` | 能力清单（含当前用户的开关与设置） |
| PUT | `/api/capabilities/{id}` | `{enabled?, settings?}` |
| GET | `/api/tools` | 当前用户可见的 Agent 工具 |
| GET | `/api/events?limit=` | 当前用户的事件日志 |
| GET/POST | `/api/providers` | 自己的供应商列表 / 新建 |
| PUT/DELETE | `/api/providers/{id}` | 更新 / 删除（仅本人） |
| POST | `/api/providers/{id}/default` | 设为默认 |
| POST | `/api/providers/{id}/test` | 连通性测试 |
| GET | `/api/providers/{id}/models` | 模型列表 |
| GET/PUT | `/api/settings` | 读取（全员）/ 写入（管理员） |
| GET | `/api/jobs`、`/api/jobs/{id}` | 自己的任务 |
| POST | `/api/jobs/{id}/cancel` | 取消自己的任务 |
| GET | `/api/jobs/stream/events` | SSE：自己的任务快照 |
| GET | `/api/admin/users` | 成员列表（管理员） |
| POST | `/api/admin/users` | 新建成员 |
| PATCH/DELETE | `/api/admin/users/{id}` | 改角色/昵称/启停、删除 |
| POST | `/api/admin/users/{id}/password` | 重置密码 |
| PUT | `/api/admin/registration` | 开放 / 关闭自助注册 |
| GET/POST | `/api/c/notes/items` | 速记（按用户） |
| GET/POST | `/api/c/wechat_digest/*` | 群聊简报（按用户） |
| GET | `/api/c/english/*` | 情景英语：场景、话题、对话（SSE）、词汇、统计等 20 个接口 |
| GET | `/api/c/library/health` | 教材库自检（支持的格式、OCR 引擎状态） |
| GET/POST/PATCH/DELETE | `/api/c/library/courses` | 教材分类（private / shared） |
| GET/POST/PATCH/DELETE | `/api/c/library/documents` | 教材：列表、详情、分块预览、上传、改名、重解析、删除 |
| GET | `/api/c/library/search` | 原文检索（BM25 + 向量 RRF） |
| POST | `/api/c/library/qa`、`/qa/stream` | 基于指定教材的问答（普通 / SSE 流式） |
| GET | `/api/c/library/qa/threads` | 问答历史 |
| GET/PUT | `/api/profile` | 用户画像：学校 / 年级 / 院系 / 专业 / 班级 / 兴趣 / 目标（局部更新） |
| GET | `/api/c/campus/feed` · `/digest` · `/health` | 校园雷达信息流（按画像排序）/ 概览 / 源状态 |
| POST | `/api/c/campus/ask` | 结合画像总结校园通知 |
| POST/PUT/PATCH/DELETE | `/api/c/campus/*`（config / crawl / sources / seed-demo） | **仅管理员**：抓取间隔、手动更新、源开关、示例数据 |
| GET | `/api/docs` | Swagger UI（`TJH_ENV=production` 时关闭） |

错误统一 `{code, message, detail?}`；401 未登录、403 权限不足。

---

## 11. 接入新能力

**A. 脚手架（推荐）**

```bash
cd apps/server
.venv/bin/python -m app.cli new-capability flashcards --name 记忆卡 --icon brain --order 20
```

**B. 手工**：复制 `app/capabilities/notes/`，改 manifest / 路由 / 迁移 / 工具。

**C. 只加工具**：在已有能力里多返回几个 `Tool`，Agent 立刻多出几种动作。

**接入多用户时必须做**：每张表加 `user_id`；每个查询按 `user.id` 过滤；`GET /x/{id}` 校验归属；工具 handler 使用 `ctx.user_id`。

---

## 12. 已知限制

- **单进程**：登录限流与任务上下文都在进程内；多 worker / 多实例需要换 Redis 与外部任务队列。
- **无邮箱验证 / 找回密码**：忘记密码由管理员重置；服务器场景可用 CLI `set-password`。
- **会话固定 30 天**，不做滚动续期（只刷新 `last_seen`）。
- **能力禁用是软隔离**：路由仍可达（但强制登录），仅隐藏导航、移除工具。
- **Agent 主循环尚未接入**：工具已带 user 上下文，但还没有聊天界面调用它们。
- **CSRF**：`SameSite=Lax` Cookie + 写请求的来源校验（`core/security.py: OriginGuard`，
  跨站 Origin/Referer 直接 403）。仍未引入 CSRF token——**前后端分域部署时要重新评估**。
- **安全头由应用下发**（CSP / X-Frame-Options / nosniff 等）；用 nginx 直出静态文件时，
  需要在 nginx 侧补同样的头（`deploy/nginx/security-headers.conf`），两处 CSP 必须保持一致。
- **接口文档**：`TJH_ENV=production` 时 `/api/docs` 与 `/api/openapi.json` 返回 404。
- 中文界面，无 i18n。
