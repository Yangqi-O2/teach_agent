# 群聊简报 · 实现契约（wechat_digest）

> 状态：**已实现并通过独立验收**（2026-10-22）。本文既是设计说明，也是前后端并行开发的接口契约；实现与契约一致，验收证据见 [docs/VERIFICATION-WECHAT.md](VERIFICATION-WECHAT.md)。
> 背景：`python_work/wechat_ai` 已把「微信群聊 AI 总结」跑通（粘贴解析、多级清洗、防幻觉提示词、Map-Reduce、结构化日程/待办）。
> 本次目标：**把它作为天健湖的一个能力接进来，复用天健湖的内核与设计系统，而不是复制一个独立小应用。**

---

## 0. 范围（已与用户确认）

**做：**

- 新增能力 `wechat_digest`（导航名「群聊简报」，页面 `/cap/wechat-digest`）
- **唯一数据源：粘贴文本**（微信/QQ 复制出的聊天记录，多格式解析）。不做 OneBot、不做 wechat-cli、不做定时任务。
- 架构必须可扩展：数据源适配器、提示词风格、导出格式都走注册表；以后加数据源 = 加一个文件，前端零改动。
- 复用天健湖内核：`Capability` / `Tool` 注册表 / 任务中心（进度、取消）/ `LLMClient` / SQL 迁移 / 统一错误 / 设置 Schema。
- UI 完全统一到天健湖设计系统（`src/styles.css` 令牌 + `components/ui/primitives.tsx`），明暗主题、响应式、空状态、动效一致。

**不做（保留扩展位，不写实现）：**

- QQ / OneBot 数据源、真实微信（wechat-cli）数据源
- 定时自动总结 / 后台调度
- 多用户、云端存储

---

## 1. 目录结构

后端（全部为新增文件，不改内核）：

```
apps/server/app/capabilities/wechat_digest/
├── __init__.py
├── capability.py            # CAPABILITY：manifest / router / migrations / tools / on_startup 注册 job
├── router.py                # /api/c/wechat_digest/* 全部接口
├── models.py                # Digest（SQLModel）
├── jobs.py                  # run_digest_job(ctx, payload)、错误落库、取消处理
├── service.py               # 解析/清洗/落库/导出等可复用逻辑（router、jobs、tools 共用）
├── sources/
│   ├── __init__.py          # 数据源注册表：register_source / get_source / list_sources
│   ├── base.py              # Message、MessageSource、SourceDescriptor、注册表
│   └── paste.py             # 粘贴文本适配器（移植 wechat_ai/src/paste_source.py 的解析规则）
├── pipeline/
│   ├── __init__.py
│   ├── cleaners.py          # 多级清洗（移植并统计丢弃原因）
│   ├── prompts.py           # 防幻觉纪律 + 输出格式 + 风格注册表
│   ├── summarizer.py        # 分块 / Map-Reduce / 调用 LLM / 解析结构化结果
│   └── exporters.py         # payload → txt / json / md / ics
└── migrations/001_wechat_digest.sql
```

前端（新增 + 两处增量）：

```
apps/web/src/capabilities/wechat_digest/
├── index.tsx                # 能力注册（id 必须 = wechat_digest，路由 /cap/wechat-digest）
└── page.tsx                 # 页面
apps/web/src/lib/api.ts      # 追加 digest 类型与 api.digest（只增量，不改已有）
apps/web/src/components/Icon.tsx  # 追加用到的 lucide 图标映射（只增量）
```

测试：

```
apps/server/tests/test_wechat_digest_pipeline.py   # 解析 / 清洗 / 分块 / JSON 提取 / 导出
apps/server/tests/test_wechat_digest_api.py        # 路由 + job + 迁移（用假 provider / monkeypatch）
```

---

## 2. 数据模型

`migrations/001_wechat_digest.sql`：

```sql
CREATE TABLE IF NOT EXISTS wechat_digests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'paste',
    group_name     TEXT NOT NULL DEFAULT '',
    style          TEXT NOT NULL DEFAULT 'general',
    status         TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error | cancelled
    job_id         TEXT,
    provider       TEXT NOT NULL DEFAULT '',         -- 供应商展示名
    model          TEXT NOT NULL DEFAULT '',
    message_count  INTEGER NOT NULL DEFAULT 0,       -- 清洗前
    kept_count     INTEGER NOT NULL DEFAULT 0,       -- 清洗后
    result_json    TEXT NOT NULL DEFAULT '{}',       -- DigestPayload（见 §4.2）
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wechat_digests_created ON wechat_digests (created_at DESC);
```

`models.py` 用 SQLModel 映射同名表（时间字段用 ISO 字符串存 TEXT，避免与核心表的时区格式纠缠）。

---

## 3. API 契约

统一前缀 `/api/c/wechat_digest`，错误沿核心 `ApiError`：

- 数据源为空 / 解析不出消息：`422`，`code=empty_source`
- 超出字符上限：`413`，`code=too_long`
- 没有可用模型供应商：`409`，`code=no_provider`（message 引导去「设置 → 模型接入」）
- 记录不存在：`404`，`code=not_found`

实现中还补齐了以下向后兼容的细分错误码（不改变上述契约）：`invalid_source` / `invalid_style` / `invalid_format`（422）、`source_unavailable` / `source_error`（422）、`not_ready` / `empty_result`（409）。

### 3.1 `GET /options` → 页面启动元数据

```json
{
  "sources": [
    {
      "id": "paste",
      "name": "粘贴文本",
      "description": "把微信 / QQ 的聊天记录复制进来，零权限、零账号。",
      "badge": "推荐",
      "available": true,
      "hint": null,
      "sample_params": {"text": "[2026-10-22 17:50] 李老师: 周五前交实验报告\n张三: 收到\n李老师: 下周三随堂测验，范围第 3-4 章", "group_name": "高数A班"},
      "params_schema": {
        "type": "object",
        "properties": {
          "text": {"type": "string", "format": "textarea", "title": "聊天记录", "description": "支持 [时间] 昵称: 内容、微信/QQ 复制格式、纯「昵称: 内容」", "required": true},
          "group_name": {"type": "string", "title": "会话 / 群名", "default": "粘贴内容"}
        }
      }
    }
  ],
  "styles": [
    {"id": "general", "label": "通用", "description": "均衡：重点、待办、日程都抓"},
    {"id": "course", "label": "课程 / 学习", "description": "更关注作业、考试、截止时间"},
    {"id": "club", "label": "社团 / 活动", "description": "更关注活动、报名、地点、负责人"}
  ],
  "settings": {"default_style": "general", "max_chars": 60000, "history_limit": 30}
}
```

### 3.2 `POST /preview` → 只解析 + 清洗，不调用模型

请求：`{"source": "paste", "params": {"text": "...", "group_name": "高数A班"}}`

```json
{
  "ok": true,
  "source": "paste",
  "total_before": 120,
  "total_after": 48,
  "groups": [
    {"name": "高数A班", "before": 120, "after": 48, "dropped": 72,
     "drop_reasons": {"low_value": 50, "duplicate": 10, "placeholder_limit": 12}}
  ],
  "sample": [
    {"time": "2026-10-22 17:50", "sender": "李老师", "text": "周五交实验报告"}
  ]
}
```

`sample` 为清洗后前 5 条，格式为 `[time] sender: text` 拆好的三元组（time/sender 可为空串）。

### 3.3 `POST /digests` → 创建并异步生成（202）

请求：

```json
{"source": "paste", "params": {"text": "...", "group_name": "高数A班"},
 "style": "general", "provider_id": null}
```

`provider_id` 为空 = 用默认供应商。创建前先校验：文本可解析、长度、provider 可用（若不可用立即 409，不建任务）。

响应 `202`：

```json
{"ok": true, "job_id": "ab12cd34ef56", "digest": { /* DigestSummary，见 3.5 */ }}
```

### 3.4 任务进度

走核心任务中心：`GET /api/jobs/{job_id}`。`type` 固定为 `wechat_digest`，`progress` 阶段：

| progress | message |
|---|---|
| 5 | 解析聊天记录 |
| 15 | 清洗降噪 |
| 20 → 80 | 总结第 i/n 个群 |
| 88 | 解析结构化结果 |
| 95 | 保存简报 |
| 100 | 已完成 |

取消：`POST /api/jobs/{job_id}/cancel`；job 收到取消后把 digest 置为 `cancelled`。

### 3.5 `GET /digests?limit=20&q=` → 历史列表

```json
[
  {
    "id": 1,
    "title": "高数A班 · 群聊简报",
    "group_name": "高数A班",
    "source": "paste",
    "style": "general",
    "status": "done",
    "provider": "AMD Radeon",
    "model": "DeepSeek-V4-Flash",
    "message_count": 120,
    "kept_count": 48,
    "one_line": "周五交实验报告，下周三随堂测验。",
    "created_at": "2026-10-22T20:31:00"
  }
]
```

`q` 对 title / group_name 做 LIKE 过滤（可选实现）。

### 3.6 `GET /digests/{id}` → 详情

```json
{
  "id": 1,
  "title": "高数A班 · 群聊简报",
  "group_name": "高数A班",
  "source": "paste",
  "style": "general",
  "status": "done",
  "job_id": "ab12cd34ef56",
  "provider": "AMD Radeon",
  "model": "DeepSeek-V4-Flash",
  "message_count": 120,
  "kept_count": 48,
  "one_line": "周五交实验报告，下周三随堂测验。",
  "error": null,
  "created_at": "2026-10-22T20:31:00",
  "updated_at": "2026-10-22T20:31:12",
  "result": { /* DigestPayload，见 §4.2；未完成时为 null */ }
}
```

### 3.7 `DELETE /digests/{id}` → `{"ok": true}`

### 3.8 `GET /digests/{id}/export?format=txt|json|md|ics` → 文件下载

- `txt`：可直接读 / 复制回群的结构化文本（含生成时间、模型、清洗统计）
- `json`：`DigestPayload` 原样
- `md`：待办 + 日程清单（`- [ ]` / `- [x]`）
- `ics`：标准 VCALENDAR（含 SUMMARY / DTSTART / DESCRIPTION）

`Content-Disposition` 用 `filename*=UTF-8''...` 兼容中文文件名。

---

## 4. 结果数据结构

### 4.1 Message（内部）

```python
@dataclass
class Message:
    group: str
    sender: str
    text: str
    time: str = ""
    def to_ai_line(self) -> str: ...   # "[时间] 发送者: 内容"
```

### 4.2 DigestPayload（`result_json`，同时是导出 json 的内容）

```json
{
  "version": 1,
  "source": "paste",
  "group_name": "高数A班",
  "style": "general",
  "provider": "AMD Radeon",
  "model": "DeepSeek-V4-Flash",
  "created_at": "2026-10-22T20:31:00",
  "stats": {"before": 120, "after": 48, "dropped": 72, "chunks": 1},
  "groups": [
    {
      "name": "高数A班",
      "message_count": 48,
      "one_line": "周五交实验报告，下周三随堂测验。",
      "items": ["周五前交实验报告", "下周三随堂测验"],
      "schedules": [
        {"title": "交实验报告", "datetime": "2026-10-24T23:59", "note": "提交到学习通", "done": false, "source_sender": "李老师"}
      ],
      "structured_text": "【一句话】...\n【重要事项】\n1. ...\n【待办】\n1. ..."
    }
  ]
}
```

模型原始输出解析失败时：`one_line` 用文本兜底，`items=[]`，`schedules=[]`，`structured_text` 保留原文（不抛错）。

---

## 5. 可扩展性（关键）

### 5.1 数据源适配器协议

```python
# sources/base.py
@dataclass
class Message: ...

class MessageSource(ABC):
    id: str
    name: str
    description: str
    params_schema: dict          # JSON Schema 子集，前端据此渲染参数表单
    badge: str | None = None
    sample_params: dict | None = None   # 「填入示例」的预填参数（可选）

    def available(self) -> tuple[bool, str | None]:
        """返回 (是否可用, 不可用提示)"""
        return True, None

    @abstractmethod
    def load(self, params: dict) -> dict[str, list[Message]]:
        """返回 {群名: [Message, ...]}（未清洗）"""

_SOURCES: dict[str, MessageSource] = {}
def register_source(source: MessageSource) -> None: ...
def get_source(source_id: str) -> MessageSource: ...
def list_sources() -> list[dict]: ...   # 转成 §3.1 的 sources 描述
```

**以后接 OneBot / wechat-cli 只要**：新增 `sources/onebot.py` 实现 `load()` 并在 `sources/__init__.py` 里 `register_source(OneBotSource())`；前端 `/options` 自动多一个数据源、自动按 `params_schema` 渲染参数表单、`POST /preview` 与 `POST /digests` 自动可用。

### 5.2 其它扩展点

- 提示词风格：`pipeline/prompts.py` 的 `STYLES` 注册表，新增风格只加一项（`GET /options` 自动暴露）。
- 导出格式：`pipeline/exporters.py` 的 `EXPORTERS` 注册表（`txt/json/md/ics`），新增格式只加函数。
- 总结策略：`summarizer.py` 只依赖 provider 的 `chat()`，换模型/换供应商不影响管道。

---

## 6. 前端页面（统一 UI）

路由 `/cap/wechat-digest`，能力 id `wechat_digest`，manifest icon `message-square`。

**布局**（复用 `PageHeader`、`card`、`Button/Badge/Input/Textarea/Field/Segmented/Progress/EmptyState/SectionHeading`、`useApp().toast`、`relativeTime`）：

```
PageHeader  eyebrow="能力 · 群聊"  title="群聊简报"
            描述：粘贴微信群 / QQ 群聊天记录，先清洗降噪，再交给模型整理成
                  「一句话 + 重要事项 + 待办 + 日程」。数据只留在本机。
            actions：模型状态 / 去设置

grid lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]
  左：新建简报 card
    - 数据源（来自 /options，当前只有「粘贴文本」；有 badge）
    - 按 params_schema 渲染：聊天记录 Textarea（mono）、会话/群名 Input
    - 「填入示例」「从剪贴板读取」快捷按钮
    - 总结风格 select + 模型 select（来自 store.providers；空则提示去设置）
    - 「预览清洗」→ 显示 原始 N 条 → 保留 M 条 + 前 5 条样例
    - 「生成简报」主按钮；生成中显示 Progress + 阶段文案 + 取消
  右：结果区
    - 无记录：EmptyState + 最近简报列表
    - 有记录：标题 + 状态/条数/模型徽章 + 「一句话」引用块
      + 导出：TXT / 待办 MD / 日程 ICS / JSON（下载链接）
      + Segmented：总结 | 待办 | 日程
        - 总结：structured_text（pre-wrap，保留【】层次）
        - 待办：items + schedules 的 checklist（按群分组）
        - 日程：时间 / 标题 / 备注 列表，空状态
    - 最近简报：点击切换、hover 删除、relativeTime
```

**约束**：只用设计令牌（`bg-surface`、`text-ink-soft`、`border-line`、`brand/jade/amber/danger`…），不出现 `gray-*` / `blue-*` 等原始色；标题用 `font-display`；动效用 `page-enter` / `stagger`；明暗两套主题都要正常；**≥1280px 双栏（`xl` 断点），<1280px 单栏**（单列用 `grid-cols-1` 约束列宽，避免长文本撑出横向滚动）；失败用 toast + 页面内错误态。

**交互细节**：

- 创建后轮询 `GET /api/jobs/{job_id}`（约 1s），完成后拉详情、刷新历史、toast「简报已生成」。
- 生成失败：toast 展示后端返回的引导文案（如「还没有配置模型供应商」）。
- 删除：确认后删除并回退到最近一条。
- 文本框 ⌘/Ctrl + Enter 触发生成。

---

## 7. Agent 工具

| 工具 | 参数 | 行为 |
|---|---|---|
| `summarize_group_chat` | `text`(必填), `group_name`, `style` | 同步走完整管道并入库，返回 `{digest_id, one_line, stats, groups:[{name, one_line, items, schedules}]}` |
| `list_group_digests` | `limit` | 返回最近的简报摘要列表 |

---

## 8. 能力设置（settings_schema）

```json
{
  "type": "object",
  "properties": {
    "default_style": {"type": "string", "title": "默认总结风格", "enum": ["general", "course", "club"], "default": "general"},
    "max_chars": {"type": "integer", "title": "单次粘贴上限（字符）", "default": 60000, "description": "超过会拒绝，避免一次塞进太多内容"},
    "history_limit": {"type": "integer", "title": "最多保留历史条数", "default": 30, "description": "超出后自动清理最早的简报"}
  }
}
```

设置存 `capability_state`（核心已实现），后端读取时用默认值兜底。

---

## 9. 验证清单（已执行）

1. `cd apps/server && .venv/bin/python -m pytest -q` 全绿（**58 passed**）
2. `cd apps/web && pnpm build`（tsc --noEmit + vite build）通过
3. 全新数据目录起后端，验证：
   - `GET /api/capabilities` 出现 `wechat_digest`
   - `/options`、`/preview`、错误路径（空文本 / 超长 / 无 provider / 404）
   - 配置 OpenAI 兼容 provider 后 `POST /digests` → 轮询 job done → 详情结构完整 → 四种导出可下载
   - 大文本触发 Map-Reduce 多块（实测 23,507 字 → `chunks=2`）
4. 浏览器截图：亮/暗两套 + 移动端，与天健湖其他页视觉一致
5. `GET /api/tools` 出现两个新工具
6. 重启 8787 正式实例，用户打开即可看到「群聊简报」

验收证据（含 mock 模型 E2E、导出校验、截图、UI 一致性结论）：[docs/VERIFICATION-WECHAT.md](VERIFICATION-WECHAT.md)。

---

## 10. 非目标与已知边界

- 不支持多群混在一条粘贴记录里自动拆分（一次粘贴 = 一个会话名；如需多群，分多次）。
- LLM 输出不保证 100% 合法 JSON：解析失败降级为纯文本总结，不让用户白等。
- 粘贴内容只在内存与本地 SQLite 里，不经第三方存储；但会发给用户配置的模型服务，页面需明示。

---

## 11. 实现落点（给维护者）

| 关注点 | 位置 |
|---|---|
| 能力装配（manifest / 工具 / job 注册） | `apps/server/app/capabilities/wechat_digest/capability.py` |
| HTTP 接口 | `apps/server/app/capabilities/wechat_digest/router.py` |
| 业务编排（预览 / 落库 / 导出） | `apps/server/app/capabilities/wechat_digest/service.py` |
| 后台任务（进度 / 取消 / 失败落库） | `apps/server/app/capabilities/wechat_digest/jobs.py` |
| 数据源注册表 + 粘贴适配器 | `apps/server/app/capabilities/wechat_digest/sources/` |
| 清洗 / 提示词 / 总结 / 导出 | `apps/server/app/capabilities/wechat_digest/pipeline/` |
| 数据表迁移 | `apps/server/app/capabilities/wechat_digest/migrations/001_wechat_digest.sql` |
| 页面 | `apps/web/src/capabilities/wechat_digest/page.tsx` |
| API 客户端与类型 | `apps/web/src/lib/api.ts` → `api.digest` |
| 测试 | `apps/server/tests/test_wechat_digest_{pipeline,api}.py` |
| 截图 | `docs/screenshots/wechat-digest-{light,dark,mobile}.png` |

**新增一个数据源**（例如 QQ OneBot）：在 `sources/` 下实现 `MessageSource`（声明 `params_schema` / `sample_params` / `available()` / `load()`），在 `sources/__init__.py` 里 `register_source(...)`，重启即可——`/options`、参数表单、预览、生成、导出全部自动生效，前端无需改动。步骤模板见 `sources/base.py` 顶部注释。
