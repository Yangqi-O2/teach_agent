# 群聊简报（wechat_digest）验收记录

> 验收日期：2026-10-22 · 验收人：独立验收（verifier teammate）
> 对应契约：[docs/WECHAT-DIGEST.md](WECHAT-DIGEST.md) §9 验证清单
> 结论：**通过**（下方逐项列出证据；两处前端小修在 §7 说明）
>
> **本文档**：群聊简报的独立验收记录（契约核对、E2E、导出、UI、边界）
> ｜ **路径**：`docs/VERIFICATION-WECHAT.md` ｜ **状态**：📦 2026-10 快照，不随代码更新

## 1. 验收环境

| 项 | 值 |
|---|---|
| 仓库 | 仓库根目录（提交 `7dfd0a0` + 当时工作区改动） |
| Python | 3.11.17（`apps/server/.venv`，FastAPI 0.159.1 / SQLModel 0.0.48） |
| Node / pnpm | v26.8.1 / 11.24.0 |
| 临时后端 | `TJH_DATA_DIR=/tmp/tjh-digest-e2e .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8799`（**全新数据目录**，未动 8787 正式实例） |
| 模型服务 | **本地 mock 服务 `http://127.0.0.1:8797/v1`**（OpenAI 兼容，返回固定的中文结构化总结） |

> ⚠️ **模型链路说明：E2E 的模型服务是本地 mock（127.0.0.1:8797），未使用真实 Key、无外部请求。**
> 没有读取任何真实 `.env` / API Key，没有访问外网模型服务。数据库中 provider 展示名为
> `DeepSeek`、模型名 `deepseek-chat`，只是为了让页面与导出看起来接近真实产品；实际
> Base URL 全部指向本机 8797。

## 2. 单元测试与构建

```text
$ cd apps/server && .venv/bin/python -m pytest -q
58 passed in 0.73s
```

覆盖：粘贴解析（内联时间 / 微信 / QQ / 混合 / 多行续行）、多级清洗与丢弃原因、
token 估算与分块、`----JSON----` 与脏输出 JSON 提取、解析失败降级、三种风格注册表、
四种导出（含 ICS 转义）、`/options` / `/preview` / 409 / 413 / 422 / 404 / 导出未完成 409、
完整创建→任务→详情流程、任务失败置 error、取消置 cancelled、Agent 工具、多群进度单调。

```text
$ cd apps/web && pnpm build        # tsc --noEmit && vite build
vite v8.3.5 building client environment for production...
✓ 2042 modules transformed.
dist/index.html                   1.44 kB │ gzip:   0.80 kB
dist/assets/index-FEV-3ssU.css   55.10 kB │ gzip:  10.13 kB
dist/assets/index-CaCMXqPi.js   497.87 kB │ gzip: 156.30 kB
✓ built in 184ms
```

## 3. 契约核对（路由 / 字段 / 状态机）

- 路由前缀 `/api/c/wechat_digest`：`GET /options`、`POST /preview`、`POST /digests`(202)、
  `GET /digests`、`GET|DELETE /digests/{id}`、`GET /digests/{id}/export?format=` 全部存在。
- `/api/capabilities` 返回 `['notes', 'wechat_digest']`；manifest 字段（id / name / icon /
  nav / settings_schema）与契约一致。
- 任务：`type=wechat_digest`，进度阶段 5 / 15 / 20→80 / 88 / 95 / 100，
  测试覆盖多群进度单调不回退；取消后 digest 置 `cancelled`。
- 详情：`status=done` 时 `result` 非空，`queued/running/error/cancelled` 时 `result=null`。
- 结果字段：`version/source/group_name/style/provider/model/created_at/stats/groups`，
  group 内含 `name/message_count/one_line/items/schedules/structured_text`，schedule 内含
  `title/datetime/note/done/source_sender` —— 与契约 §4.2 一致。
- 数据源 / 风格 / 导出格式均走注册表（`register_source` / `STYLES` / `EXPORTERS`），
  `GET /options` 自动暴露；新增 OneBot / wechat-cli 只需加一个 `sources/*.py`。

## 4. 解析 + 清洗实测（`POST /preview`）

| 样例 | 格式 | 原始消息 | 清洗后 | 丢弃 | 丢弃原因 |
|---|---|---|---|---|---|
| `.tmp/sample_chat_inline.txt`（55 行） | `[时间] 昵称: 内容` | 55 | **37** | 18 | `low_value: 18` |
| `.tmp/sample_chat_wechat.txt`（32 行） | 微信 PC 复制（昵称 时间 / 内容两行） | 16 | 10 | 6 | `low_value: 6` |

- `sample` 为清洗后前 5 条，`{time,sender,text}` 三元组，与契约 §3.2 一致。
- 错误路径实测：空文本 / 空 params / 全为低价值消息 → `422 empty_source`；
  60027 字 → `413 too_long`；未知数据源 → `422 invalid_source`；
  未知风格 → `422 invalid_style`；未知导出格式 → `422 invalid_format`；
  记录不存在 → `404 not_found`；无 provider 创建 → `409 no_provider`。

## 5. 模型链路 E2E（本地 mock 模型，`/tmp/tjh-digest-e2e` 全新数据）

一次运行完整流程（脚本保存在 `.tmp/verify_e2e.py`，41 项断言全部 PASS）：

1. 配置 provider：`DeepSeek` / `http://127.0.0.1:8797/v1` / `deepseek-chat`（mock key）。
2. `POST /preview`（55→37）→ `POST /digests` 返回 **202** + `job_id`。
3. 轮询 `GET /api/jobs/{job_id}` → `status=done`、`type=wechat_digest`、progress 到 100。
4. `GET /digests/{id}`：字段齐全、`status=done`、`provider=DeepSeek`、`model=deepseek-chat`、
   `message_count=55` / `kept_count=37`、`result.version=1`、
   `groups[0]` 含 `one_line` / 4 条 `items` / 4 条 `schedules` / 保留【】层次的 `structured_text`、
   `stats={before:55, after:37, dropped:18, chunks:1}`。
5. 四种导出（见 §6）。
6. `GET /api/tools` 新增 `summarize_group_chat`、`list_group_digests`。
7. 大文本 Map-Reduce：构造 23,507 字 / 180 条聊天记录 → `preview 180→180` →
   创建 202 → job done → `stats.chunks=2`，结果结构正常（走 Map → Reduce 合并分支）。

## 6. 导出校验

| 格式 | 内容 | 校验结果 |
|---|---|---|
| `txt` | 979 字符 | 含标题 / 生成时间 / 模型 / 清洗统计（`原始 55 条 → 保留 37 条`）与【】层次 |
| `md` | 671 字符 | 含 `- [ ]` 待办 checkbox、重要事项、日程（提出人） |
| `ics` | 932 字符 | `BEGIN:VCALENDAR` / `BEGIN:VEVENT` / `SUMMARY` / `DTSTART` / `DESCRIPTION` / `END:VCALENDAR`，事件数 4 = 日程数 4 |
| `json` | 1980 字符 | 合法 JSON，与详情 `result` 完全一致 |

四种响应的 `Content-Disposition` 同时带 ASCII 兜底名与 RFC 5987 中文名
（如 `filename*=UTF-8''%E9%AB%98%E6%95%B0A%E7%8F%AD...`），浏览器可直接下载。

## 7. 前端 UI / 响应式验收（含两处小修）

### 7.1 必改项：两栏断点 `lg:` → `xl:`

`apps/web/src/capabilities/wechat_digest/page.tsx` 的两栏 grid 断点由 `lg`（1024px）改为
`xl`（1280px）：**<1280px 单栏**，≥1280px 恢复「左表单 420px + 右结果」双栏。
修复了 1024px 下右栏被挤到约 250px 的拥挤问题。

### 7.2 验收中额外发现并修复：移动端横向溢出

改断点后复检移动端，发现页面在 390px 下 `scrollWidth=649`（卡片被内容撑宽、右侧被裁切）。
根因是单列 grid 隐式列按 max-content 撑开（「最近简报」里 `truncate` 的 nowrap 文本贡献了
最小宽度）。修复：显式 `grid-cols-1`（等价 `minmax(0,1fr)`），约束列宽后
复测 `scrollWidth = innerWidth = 390`，无横向溢出。
桌面布局不受影响（1440/1280 截图目检一致）。

### 7.3 断点目检（headless Chrome + CDP 截图，设备像素比 2）

| 视口 | 结论 |
|---|---|
| 1024×768 | 单栏；表单/结果卡片满宽、无挤压、无溢出；结果区完整可读 |
| 1280×900 | 双栏（左 420 / 右自适应）；右栏不再被挤压 |
| 1440×900 | 双栏，左 420 / 右约 716，留白舒适 |

桌面截图与 `docs/screenshots/home-light.png`、`notes.png` 逐项比对：同一套
`PageHeader`（eyebrow / 标题 / 描述 / 右上 actions）、同款 `card`（圆角、边框、阴影、内边距）、
同样的 `Badge` 软色（jade 表示完成、neutral 计数、outline 模型、brand 风格）、
同样的主按钮（湖蓝渐变）与 ghost 次级按钮、同样的字体层级与留白节奏；明暗两套主题都正常，
未出现加载态 / 报错态 / 空态缺失（空列表、无待办、无日程均有 EmptyState）。
`grep` 检查页面与新增文件：无 `gray-*` / `blue-*` / `slate-*` / 十六进制原始色，
只使用设计令牌（`bg-surface` / `text-ink-soft` / `border-line` / `brand` / `jade` / `amber` / `danger`）。

### 7.4 页面交互实测（DOM 断言）

- 「填入示例」→ 文本框填入示例、群名变为「高数A班」。
- 「预览清洗」→ 展示 `原始 3 条 → 保留 2 条 / 降噪 1 条` + 清洗后样例，无报错。
- 历史列表自动选中最近一条，结果区展示「一句话 / 总结·待办·日程」三 tab；
  待办 tab（4 项待办 + 4 个日程、时间徽章、@提出人）与日程 tab（按时间排序）实测正常。
- 1440 视口 `scrollWidth=1440`，无横向溢出。

## 8. 截图产物（`docs/screenshots/`，CDP 设备像素比 2，逻辑尺寸如下）

| 文件 | 逻辑尺寸 | 说明 |
|---|---|---|
| `wechat-digest-light.png` | 1440×900 | 亮色：一条已完成简报选中，展示「已完成 / 保留 37 条 / DeepSeek · deepseek-chat / 课程学习」徽章、四个导出按钮、一句话与结构化总结 |
| `wechat-digest-dark.png` | 1440×900 | 同上，深色主题 |
| `wechat-digest-mobile.png` | 390×844 | 移动端：结果区（已完成简报）在窄屏下的完整展示，无横向溢出 |

截图前后均确认：8799 上存在 `status=done` 的简报且页面已选中；无加载 shimmer、无红色错误块。
（1024 / 1280 / 明暗 / 待办 / 日程 的过程截图留在 `.tmp/`，未入库。）

## 9. 已知限制 / 边界

- **仅「粘贴文本」数据源**：不支持多群自动拆分（一次粘贴 = 一个会话名）；
  架构上数据源 / 风格 / 导出均为注册表，后续接 OneBot、wechat-cli 只需新增适配器文件，前端零改动。
- **模型输出不保证 100% 合法 JSON**：解析失败会降级为纯文本总结（`items=[]`、`schedules=[]`），
  不会让任务失败或白等；该降级路径有单测覆盖。
- **隐私**：粘贴内容只存本机 SQLite，但生成时会发送给用户配置的模型服务；页面已明示。
- **E2E 的模型是本地 mock**（127.0.0.1:8797），验证的是「调用 / 解析 / 落库 / 导出」链路与 UI，
  不代表真实模型输出质量；mock 返回固定中文结构化总结。
- **正式实例 8787 尚未重启**：验收使用 8799 临时实例（独立 `TJH_DATA_DIR`），
  8787 的重启由 Lead 统一执行（重启后用户即可在侧栏看到「群聊简报」）。
- 未接入定时总结、多用户、云端存储（契约 §10 的非目标）。
