# 天健湖 · 框架说明（v0.1.0）

> 这一版只做「总体框架」：内核、能力插件、工具注册、迁移、任务中心、模型接入、设计系统与前端骨架。
> 教材库 / 校园雷达 / 联想记忆等能力会按同一套协议逐个接进来，**不需要改内核**。

---

## 1. 目录与职责

```
apps/server/                     Python 后端（FastAPI）
├── app/
│   ├── main.py                  应用装配：发现能力 → 迁移 → 建表 → 挂路由 → 托管前端
│   ├── config.py                配置（TJH_ 环境变量 / .env）+ 数据目录
│   ├── db.py                    SQLite 引擎、会话、迁移执行器
│   ├── models.py                核心表：providers / settings / jobs / capability_state / events
│   ├── core/
│   │   ├── capability.py        能力协议 + 自动发现 + 全局注册表
│   │   ├── tools.py             工具注册表（Agent function calling 清单）
│   │   ├── llm.py               OpenAI 兼容客户端（chat / stream / embed / 测试连接）
│   │   ├── jobs.py              任务中心（线程池 + 进度 + 取消）
│   │   ├── crypto.py            Fernet 加密 API Key（本机 secret.key，0600）
│   │   └── errors.py            统一错误 JSON
│   ├── api/                     system / providers / jobs / settings 四组接口
│   ├── capabilities/            能力插件目录（目前只有 notes 示例）
│   │   └── notes/               capability.py · router.py · models.py · migrations/
│   ├── migrations/              核心迁移（预留）
│   └── cli.py                   run / doctor / migrate / new-capability
├── data/                        运行期数据（gitignore）：app.db、secret.key、uploads/
└── requirements.txt

apps/web/                        React 前端（Vite + Tailwind v4）
├── src/
│   ├── App.tsx                  Bootstrap：加载 /api/info、能力、供应商；主题；⌘K
│   ├── app/                     Shell、Sidebar、Topbar、CommandPalette、router
│   ├── components/              Brand、PageHeader、StatCard、Icon、ProviderPanel、CapabilityPanel
│   │   └── ui/                  primitives（Button/Input/Badge/Switch/...）+ overlay（Modal/Toast）
│   ├── capabilities/            前端能力注册表（import.meta.glob）+ 各能力页面
│   │   └── notes/               index.tsx（路由）+ page.tsx（页面）
│   ├── lib/                     api.ts（类型化客户端）、utils.ts
│   ├── pages/                   Home / Settings / Jobs / NotFound
│   ├── store/app.ts             zustand：bootstrap、主题、通知
│   └── styles.css               设计令牌（@theme）、组件类、动效
└── dist/                        构建产物（由后端托管）
```

---

## 2. 启动链路

```
uvicorn app.main:app
  └─ create_app()
       ├─ settings.ensure_dirs()              创建 data/、uploads/、cache/
       ├─ capabilities.discover()             扫描 app/capabilities/*/capability.py
       ├─ init_db(capabilities.migration_dirs())
       │    ├─ 执行 core/app/migrations/*.sql
       │    ├─ 执行 <cap>/migrations/*.sql（按文件名顺序，只执行一次）
       │    └─ SQLModel.metadata.create_all() 建核心表
       ├─ capabilities.register_tools()       收集 Tool 进全局注册表
       ├─ include_router(/api/...)            系统 / 供应商 / 任务 / 设置
       ├─ capabilities.mount(app)             每个能力挂到 /api/c/<id>
       └─ _mount_frontend(app)                托管 apps/web/dist，其余路径回 index.html
```

开发模式（`make dev`）：后端 8787 + Vite 5174，Vite 把 `/api` 代理到 8787。

---

## 3. 能力协议（后端）

一个能力就是一个继承了 `Capability` 的类，并在模块里暴露 `CAPABILITY`：

```python
# app/capabilities/notes/capability.py
from app.core.capability import Capability, CapabilityManifest, NavItem
from app.core.tools import Tool

class NotesCapability(Capability):
    manifest = CapabilityManifest(
        id="notes",
        name="速记",
        description="随手记下课堂灵感、待办与摘录",
        icon="notebook-pen",                       # lucide 图标名
        nav=NavItem(label="速记", path="/cap/notes", order=10),
        settings_schema={                          # 前端自动渲染设置表单
            "type": "object",
            "properties": {
                "default_tags": {"type": "string", "title": "默认标签", "default": "课堂"}
            },
        },
    )

    def router(self):            return router            # 挂载到 /api/c/notes
    def migrations_dir(self):    return Path(__file__).parent / "migrations"
    def tools(self):             return [Tool(name="create_note", ..., handler=_create_note)]
    async def on_startup(self, app): ...                   # 可选

CAPABILITY = NotesCapability()
```

约定与保证：

| 项 | 说明 |
|---|---|
| 发现 | 启动时扫描 `app/capabilities/*/capability.py`；模块加载失败只告警不崩 |
| 路由 | `router()` 返回的 APIRouter 自动挂到 `/api/c/<cap_id>` |
| 工具 | `tools()` 返回的 Tool 自动进入 `/api/tools` 与 Agent 工具表 |
| 迁移 | `migrations/*.sql` 按文件名执行一次，记录在 `_migrations` 表 |
| 设置 | `settings_schema` 是 JSON Schema 子集，前端据此渲染表单并回写 `capability_state` |
| 开关 | 禁用后：导航消失、工具不再暴露；数据保留、路由仍在（单用户本地场景下不做硬隔离） |

---

## 4. 工具注册表（给 Agent 用）

```python
Tool(
    name="create_note",                 # 函数名，全局唯一
    description="把一段内容记成速记",
    parameters={... JSON Schema ...},
    handler=_create_note,               # async 或 sync，参数按 schema 传入
    scopes=["notes:write"],             # 预留权限位
    needs_confirm=False,                # 高风险操作可要求前端确认
)
```

- `GET /api/tools` 返回全部工具（含所属能力、参数、权限、是否启用）。
- 后续接入 Agent 主循环时，直接 `registry.openai_specs(allowed=已启用能力)` 作为 `tools` 参数；执行统一走 `registry.execute(name, args)`，返回 `{ok, data}` / `{ok:false, error}`。

---

## 5. 数据与迁移

核心表（`SQLModel` 定义在 `models.py`）：

| 表 | 用途 |
|---|---|
| `providers` | 模型供应商；`api_key_enc` 是 Fernet 密文，`key_hint` 只存掩码 |
| `settings` | 全局键值设置（JSON 文本） |
| `jobs` | 任务：queued/running/done/error/cancelled + progress/message/result |
| `capability_state` | 能力开关与设置 JSON |
| `events` | 事件日志（首页动态、操作审计） |
| `_migrations` | 迁移执行记录 |

能力自带表（如 `notes`）由能力自己的 SQL 迁移创建，核心不感知。

**迁移规则**：`文件名排序 → 已执行则跳过 → 整个文件一个事务执行 → 记录到 `_migrations`**。写迁移时请用 `CREATE TABLE IF NOT EXISTS` 等幂等语句。

---

## 6. 前端能力注册表

```ts
// src/capabilities/notes/index.tsx
const capability: CapabilityModule = {
  id: "notes",
  routes: [{ path: "/cap/notes", element: <NotesPage /> }],
};
export default capability;

// src/capabilities/registry.ts
const modules = import.meta.glob("./*/index.tsx", { eager: true });
```

- **导航与开关以服务端 manifest 为准**（`/api/capabilities`），前端只提供页面。
- 路由：`AppRoutes` 只挂载「已启用」能力的前端路由。
- 设置表单：`CapabilityPanel` 读取 `settings_schema`，支持 string / number / integer / boolean / enum，改动回写 `PUT /api/capabilities/<id>`。

---

## 7. CLI

```bash
cd apps/server
.venv/bin/python -m app.cli run            # 启动后端
.venv/bin/python -m app.cli doctor         # 环境自检（Python/依赖/端口/前端产物）
.venv/bin/python -m app.cli migrate        # 执行迁移
.venv/bin/python -m app.cli new-capability flashcards --name 记忆卡 --icon brain --order 20
```

`new-capability` 会同时生成：

```
app/capabilities/<id>/{capability.py, router.py, migrations/001_init.sql}
src/capabilities/<id>/{index.tsx, page.tsx}
```

重启后端 → 侧栏出现新能力 → `/api/tools` 出现 `<id>_ping` 工具。

---

## 8. HTTP API（v0.1.0 已实现）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/info` | 版本、数据目录、供应商/能力/工具数量 |
| GET | `/api/capabilities` | 能力清单（manifest + enabled + settings） |
| PUT | `/api/capabilities/{id}` | `{enabled?, settings?}` |
| GET | `/api/tools` | Agent 工具清单 |
| GET | `/api/events?limit=` | 事件日志 |
| GET/POST | `/api/providers` | 供应商列表 / 新建 |
| PUT/DELETE | `/api/providers/{id}` | 更新 / 删除（key 留空=不改，空串=清除） |
| POST | `/api/providers/{id}/default` | 设为默认 |
| POST | `/api/providers/{id}/test` | 连通性测试（models + 1 token chat） |
| GET | `/api/providers/{id}/models` | 拉模型列表 |
| GET/PUT | `/api/settings` | 全局键值设置 |
| GET | `/api/jobs`、`/api/jobs/{id}` | 任务列表 / 详情 |
| POST | `/api/jobs/{id}/cancel` | 取消任务 |
| GET | `/api/jobs/stream/events` | SSE：任务快照（0.9s 轮询推送） |
| GET/POST | `/api/c/notes/items` | 速记列表（`?q=` 搜索）/ 新建 |
| PATCH/DELETE | `/api/c/notes/items/{id}` | 修改 / 删除 |
| GET | `/api/docs` | Swagger UI |

错误统一：`{code, message, detail?}`。

---

## 9. 接入新能力的三条路

**A. 用脚手架（推荐）**

```bash
cd apps/server
.venv/bin/python -m app.cli new-capability flashcards --name 记忆卡 --icon brain --order 20
```

然后把 `router.py`、`capability.py`、`page.tsx` 填上业务逻辑即可。

**B. 手工加一个后端能力**：复制 `app/capabilities/notes/` 改名，修改 manifest、路由、迁移，重启。

**C. 只加工具不改 UI**：在已有能力里多返回几个 `Tool`，Agent 立刻多出几种动作。

---

## 10. 下一步建议（对应 DESIGN.md 路线图）

| 阶段 | 要加的东西 | 框架已提供的 |
|---|---|---|
| P1 教材库 | `parsers/`（docx/pptx/pdf/epub）、分块、嵌入、FTS5+向量检索、SSE 聊天 | 任务中心、LLM 客户端（chat/stream/embed）、迁移、设置表单、SSE 经验 |
| P2 校园雷达 | 订阅源、适配器、抓取 job、LLM 抽取、通知表、日历 | 任务中心、能力路由、工具注册 |
| P3 联想记忆 | 画像、知识点抽取、卡片生成、FSRS 复习 | 设置表单、工具、迁移、事件 |
| P4 练习场 | 出题/批改/错题本 | 全部同上 |
| P5 打磨 | 动效、移动端、Docker、示例数据 | 设计系统已就绪 |

---

## 11. 已知限制

- **单用户本地**：默认只监听 `127.0.0.1`，没有登录体系。
- **Agent 主循环尚未接入**：工具已经注册好，但还没有聊天界面去调用它们（P1 一起做）。
- **能力禁用是软隔离**：路由仍可访问，仅隐藏导航、移除工具。
- **任务 SSE 是轮询快照**（0.9s），不是逐事件推送；任务量大时再改。
- **中文界面**，无 i18n。
- 前端没有引入 React Query，简单页面用 `useEffect` + store；复杂数据流接入后再评估。
