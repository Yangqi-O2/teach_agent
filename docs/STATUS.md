# 功能状态总表

> **本文档**：全项目每个模块的**唯一状态真源**——是否可用、代码在哪、文档在哪、有没有测试。
> ｜ **路径**：`docs/STATUS.md` ｜ **状态**：✅ 随代码更新（最后核对 2026-10-26 / v0.3.0）
>
> 其他文档里的状态描述若与本表冲突，**以本表为准**，并请回来修正那一处。

图例：`✅ 已上线` · `🟡 部分可用` · `🧭 规划中` · `⚠️ 半成品（接口在、调用方不在）`

---

## 一、能力（Capability）

能力是插件，由后端 `manifest` 的 `status` 字段决定前端徽章展示
（`stable` → 已上线 / `beta` → 公测中 / `planned` → 规划中）。

| 能力 | 状态 | 成熟度 | 前端入口 | 后端位置 | 契约文档 |
|---|---|---|---|---|---|
| **教材库** Library | ✅ 已上线 | `stable` | `/cap/library` | `app/capabilities/library/` | [LIBRARY.md](LIBRARY.md) |
| **情景英语** English | ✅ 已上线 | `stable` | `/cap/english` | `app/capabilities/english/` | [ENGLISH.md](ENGLISH.md) |
| **群聊简报** WeChat Digest | ✅ 已上线 | `beta` | `/cap/wechat` | `app/capabilities/wechat_digest/` | [WECHAT-DIGEST.md](WECHAT-DIGEST.md) |
| **速记** Notes | ✅ 已上线 | `stable` | `/cap/notes` | `app/capabilities/notes/` | [FRAMEWORK.md](FRAMEWORK.md) §11（作为模板） |
| **校园雷达** Campus | ✅ 已上线 | `beta` | `/cap/campus` | `app/capabilities/campus/` | 本文档 §五 + [VERIFICATION-CRAWLER.md](VERIFICATION-CRAWLER.md)（爬虫可行性） |
| 联想记忆 Mnemonic | 🧭 规划中 | — | — | — | [DESIGN.md](DESIGN.md) §1.3 |
| 练习场 Practice | 🧭 规划中 | — | — | — | [DESIGN.md](DESIGN.md) §1.3 |
| 学习台 Dashboard | 🧭 规划中 | — | — | — | [DESIGN.md](DESIGN.md) §1.3 |

## 二、平台层

| 模块 | 状态 | 说明 | 代码位置 |
|---|---|---|---|
| 账号与会话 | ✅ | scrypt 密码、sha256 存 token、HttpOnly + SameSite=Lax Cookie | `app/core/auth.py` |
| 按用户数据隔离 | ✅ | 每张业务表带 `user_id`，越权断言在测试里 | `tests/` |
| 用户画像 | ✅ | 学校/年级/院系/专业/班级/兴趣/目标；注册第二步收集，`PUT /api/profile` 是唯一写入口 | `app/core/profile.py`、`app/api/profile.py` |
| 能力插件协议 | ✅ | manifest + router + migrations + tools + settings_schema | `app/core/capability.py` |
| 数据库迁移 | ✅ | 按能力目录扫描，`_migrations` 记录已执行 | `app/db.py` |
| 任务中心 | ✅ | 进程内任务 + SSE 进度；只有 `library.ingest` 一个真实任务类型 | `app/core/jobs.py` |
| 模型接入 | ✅ | OpenAI 兼容，API Key 用 Fernet 加密落库 | `app/core/llm.py` |
| 全局搜索 / 命令面板 | 🟡 | ⌘K 命令面板可用（导航 + 主题切换）；跨模块全文搜索未做 | `app/CommandPalette.tsx` |
| 私人 / 共享双池 | 🟡 | 教材、分类、速记已支持 `private`/`shared`；其他模块尚无 | `library/store.py: scope_sql()` |
| Agent 工具注册表 | ⚠️ | 8 个工具已注册、`/api/tools` 可查、`ToolContext` 带 `user_id`；**但没有 Agent 主循环消费它们** | `app/core/tools.py` |

## 三、安全与部署

| 项 | 状态 | 说明 | 代码位置 |
|---|---|---|---|
| 安全响应头 | ✅ | CSP / X-Frame-Options / nosniff / Referrer-Policy / Permissions-Policy / HSTS（可配） | `app/core/security.py` |
| 跨站写请求防护 | ✅ | `SameSite=Lax` + Origin/Referer 主机名校验 | `app/core/security.py: OriginGuard` |
| 登录限流 | ✅ | 按「用户名 + IP」计数，进程内，字典有 10,000 上限 | `app/core/auth.py` |
| 上传限制 | ✅ | 流式落盘，超限即中断并回滚记录 | `library/router.py` |
| 生产环境关闭文档 | ✅ | `TJH_ENV=production` → `/api/docs` 404 | `app/config.py: expose_docs` |
| nginx 加固 | ✅ | `server_tokens off`、登录限流、拒绝隐藏文件、静态资源安全头 | `deploy/nginx/` |
| 跨平台运行 | ✅ | macOS / Linux / Windows 同一入口 `scripts/task.py`；Linux 有 systemd 与 nginx 配置；另有 Dockerfile + compose | `scripts/`、`deploy/`、`Dockerfile` |

## 四、测试覆盖

| 范围 | 测试文件 | 数量 |
|---|---|---|
| 教材库（解析 / 分块 / 检索 / API / OCR 降级） | `tests/test_library_{core,api}.py` | 38 |
| 校园雷达 + 用户画像（分类 / 日期 / 推荐 / 去重 / 权限） | `tests/test_campus.py` | 35 |
| 情景英语（核心 / 状态 / API / 集成） | `tests/test_english_*.py` | 多 |
| 群聊简报 | `tests/test_wechat_digest_api.py` | 多 |
| 安全边界 | `tests/test_security.py` | 11 |
| **合计** | `pytest -q` | **238 passed** |

复跑：`cd apps/server && .venv/bin/python -m pytest -q`

---

## 五、校园雷达的实现边界

覆盖率能说明「现在能用什么」，比状态标签更重要：

| 项 | 现状 |
|---|---|
| 覆盖学校 | **仅郑州大学**（`school_key = zzu`）。加学校 = 在 `campus/sources.py` 加几行，不用改代码 |
| 抓取源 | 4 个：通知公告（实测 200，50+ 条）、主页要闻（实测 200）、教务处、信息公开网 |
| 源可达性 | 教务处与信息公开网在本机返回 502，**如实记录为 `error` 并自动重试**，不伪装成「没有通知」 |
| 抓取间隔 | 管理员可设 1 小时 / 3 小时 / 6 小时 / 12 小时 / 每天 / 只手动；改完立即重排所有源 |
| 手动更新 | 管理员一键触发全部源，或单源重试 |
| 去重 | 三层：`url` UNIQUE → 标题归一化（同一通知多个入口）→ 正文 hash（内容变更才更新） |
| 调度 | 进程内 asyncio 循环，60 秒检查一次；`next_run_at` 落库，重启不会全量重抓 |
| 权限 | 读与问答：所有登录用户；抓取/间隔/源开关/示例数据：仅管理员 |
| 数据归属 | `campus_items` 是全校共享的公共信息，**不带 user_id**；个性化在推荐层现算，不落库 |
| 离线演示 | `POST /api/c/campus/seed-demo` 导入 8 条示例数据，带 `is_demo=1`，界面显示「示例」标记 |

**已知限制**：只覆盖一所学校；详情页抓取有单次上限（默认 24 篇），未抓详情的条目没有正文与截止日期；
关键词分类对边界情况会分错（如「班集体评选」可能落到活动而非公示），界面上有原文链接可核对。

---

## 维护规则

改完功能后只做一件事就够：**先改这张表，再改对应的契约文档**。
如果某个功能从 🧭 变成 ✅，除本表外还需要改：
`app/capabilities/<name>/capability.py` 的 `status` 字段 → 前端徽章会自动跟着变。
