# 前端整理与上线加固说明

> 本轮目标：把「能跑」变成「能上线」。范围覆盖前端代码质量、状态标注准确性、
> 隐私信息清理、Web 安全加固与易用性；后端只改了安全边界相关部分，业务逻辑未动。
>
> **本文档**：一次整理的完整记录（改了什么、为什么、对上线有什么影响）
> ｜ **路径**：`docs/CLEANUP.md` ｜ **状态**：📦 2026-10-26 记录，结论仍然有效
> ｜ 上线操作步骤见 [`DEPLOY.md`](DEPLOY.md)

---

## 1. 整理范围

| 维度 | 做了 | 没做 |
|---|---|---|
| 代码清理 | 死导出、未使用依赖、失效注释 | 没有重构页面结构（风险大于收益） |
| 状态标注 | 全站状态文案与后端真实状态对齐 | 没有新增「版本/路线图」类页面 |
| 隐私 | 配置中的个人域名、绝对路径、服务器路径外显 | 没有改数据模型 |
| 安全 | 响应头、CSRF、限流、路径校验、部署配置 | 未引入 CSRF token（理由见 §5） |
| 易用性 | 错误边界、空态与状态提示、导航主入口 | 未重做视觉设计 |

前端规模：51 个源文件 / 9,939 行。扫描结果：**没有整文件级别的死代码**
（所有组件都被引用），死代码集中在「未使用的导出」。

---

## 2. 状态标注修正

这是本轮最实质的一类问题：页面在说谎。

| 位置 | 原状态 | 现状态 | 说明 |
|---|---|---|---|
| 首页「接下来会接进来的能力」 | 含**教材库**、**答疑台**，标注「规划中」 | 移除这两项，只留校园雷达 / 联想记忆 / 练习场 / 学习台 | 教材库与答疑已上线，挂在路线图里等于长期误导 |
| 首页 Hero 文案 | 「总体框架已就位，能力会一个个接进来」 | 「教材库、情景英语、群聊简报、速记已经上线……」 | 与事实一致 |
| 首页 Hero 浮动卡片 | 校园雷达、联想记忆无状态标记 | 加「规划中」角标 | 未实现的功能不能看起来像已实现 |
| 首页「从这里开始」三步 | 第二步引导去「速记」，第三步说「后续教材库会接入」 | 改为「上传一本教材 → 就着教材提问」 | 主路径应指向当前的主力能力 |
| 首页主按钮 | 「进入速记」 | 「进入教材库」 | 同上 |
| 能力卡片 | 只有「已启用 / 已禁用」 | 增加 manifest 真实成熟度徽章：已上线 / 公测中 / 规划中 | 后端一直有 `status` 字段，前端之前从未展示 |
| 能力管理页 | 只有版本号 | 同上增加成熟度徽章 | 群聊简报是 `beta`，之前被当作稳定功能展示 |
| 任务中心空态 | 「等教材库、校园雷达这些能力接进来以后……」 | 「上传教材后，解析与建立索引会作为后台任务出现在这里」 | 教材库已上线 |
| 任务中心图标 | 按 `library.ingest` 查表，永远查不到 | 按 `.` 后段匹配，正确显示教材库图标 | 之前所有任务都退化成默认图标 |
| 任务中心未知状态 | 兜底显示「排队中」 | 兜底显示状态原值 + 中性色 | 把「失败」显示成「排队中」是最坏的一种错觉 |
| 侧栏版本号 | 兜底硬编码 `0.2.0` | 取真实版本，取不到则不显示 | 实际版本已是 0.3.0 |

状态真源统一为后端 `CapabilityManifest.status`（`stable | beta | planned`），
前端只在 `lib/utils.ts: capabilityStatusMeta()` 做一次映射，不再各处各写一套。

---

## 3. 废弃代码与依赖清理

**移除的依赖**（`package.json` + `pnpm-lock.yaml` 同步）：

- `@radix-ui/react-slot` —— 0 处引用
- `@radix-ui/react-tooltip` —— 0 处引用

说明：`react-slot` 仍作为 dialog / dropdown-menu / switch 的**传递依赖**保留在
lockfile 的 `packages` 段，只是不再是我们直接声明的依赖。

**移除的死导出**：

- `components/Icon.tsx :: Spinner`（0 处使用）
- `lib/utils.ts :: titleCaseFallback`（0 处使用）

**新增**：`lib/utils.ts :: capabilityStatusMeta`、`maskPath`。

---

## 4. 隐私信息移除

| 文件 | 原内容 | 处理 |
|---|---|---|
| `deploy/nginx/tianjianhu.conf` | 注释里出现个人隧道域名 `www.<个人域名>.qzz.io` | 删除，改为 `<DOMAIN>` 占位符 |
| 同上 | 绝对路径 `/Users/<用户名>/teach_agent/apps/web/dist`（暴露系统用户名与目录结构） | 改为 `<SITE_ROOT>` 占位符 |
| 同上 | 为个人隧道定制的 `:12345` server 块 | 合并为单一 server 块，端口按需自行添加 |
| `deploy/README.md` | 「你现在的 12345 端口配置正是为这个准备的」等个人化描述 | 改写为通用部署说明，并迁入 `docs/DEPLOY.md` |
| 首页「数据目录」指标 | 直接展示服务器绝对路径 `/Users/<用户名>/teach_agent/data` | `maskPath()` 只保留末两级，且该字段原本就仅管理员可见 |
| `data/README.md` | 文件缺失（被误删） | 恢复，并补充权限建议与当前能力清单 |

**已暴露面评估**：nginx 注释与首页指标两处会暴露「用户名 + 目录结构」，
单独看危害有限，但配合任意一个路径穿越或报错回显就会变成攻击地图。
这类信息没有业务价值，删掉即可。

---

## 5. 安全加固

### 5.1 新增 `app/core/security.py`（纯 ASGI 中间件）

刻意不用 `BaseHTTPMiddleware`：它会给响应套缓冲层，**SSE 会被攒到结束才吐**，
教材问答与情景英语的流式输出会直接失效。

| 威胁 | 措施 |
|---|---|
| XSS 执行 | `Content-Security-Policy`：`script-src 'self'`、`object-src 'none'`、`base-uri 'self'` |
| 点击劫持 | `X-Frame-Options: DENY` + `frame-ancestors 'none'` |
| MIME 嗅探 | `X-Content-Type-Options: nosniff` |
| Referer 泄漏路径 | `Referrer-Policy: strict-origin-when-cross-origin` |
| 设备能力滥用 | `Permissions-Policy` 关闭地理位置 / 麦克风 / 摄像头 / 支付 |
| 跨站写请求（CSRF） | `OriginGuard`：写方法校验 Origin / Referer 主机名，跨站直接 403 |
| 协议降级 | `Strict-Transport-Security`（仅在配置 `TJH_HSTS_SECONDS` 时下发） |

**CSP 的连带改动**：`index.html` 里原本有一段内联主题脚本（防深色模式闪白），
`script-src 'self'` 会拦掉它。已外置为 `public/theme-init.js`，仍以同步脚本引入，
首屏行为不变，但 CSP 不需要为它开 `'unsafe-inline'`。

### 5.2 其余加固

- **接口文档**：`TJH_ENV=production` 时 `/api/docs` 与 `/api/openapi.json` 直接 404。
  公网暴露 Swagger 等于把攻击面画成地图。
- **CORS 收紧**：`allow_methods` / `allow_headers` 从 `*` 改为显式清单。
- **登录限流字典**：`_attempts` 加了 10,000 条上限，超限按最久未活动淘汰。
  原先用不同用户名扫号会让这个字典无限增长（慢速内存泄漏）。
- **静态文件路径校验**：`str.startswith()` 改为 `Path.is_relative_to()`。
  前者对 `/dist-evil` 这类同级目录会误判为合法。
- **nginx**：
  - `server_tokens off`（不回显版本号）
  - 认证接口 `limit_req`：同 IP 10 次/分钟、突发 20
  - `location ~ /\.` 拒绝 `.env` / `.git` / `.DS_Store`
  - 静态资源补安全头（HTML/JS 由 nginx 直出，应用层响应头管不到）
  - 配置底部提供 443 + TLS 1.2/1.3 模板

### 5.3 为什么没上 CSRF token

Cookie 已是 `HttpOnly + SameSite=Lax`，再加上 `OriginGuard` 校验来源，
两道防线覆盖了主流 CSRF 场景。引入 token 需要改动全部 20+ 个写接口与前端封装，
在单机部署、同源访问的前提下收益不成比例。**如果未来做前后端分域部署，应重新评估。**

---

## 6. 易用性

- **全局错误边界**（`components/ErrorBoundary.tsx`）：渲染异常不再白屏，保留侧栏导航，
  给出「重试 / 回到首页」两条出路，并回显错误信息便于反馈。按路由 key 重置，
  一次异常不会让整站永久卡在错误页。
- **状态可见性**：能力成熟度、任务状态、教材解析状态现在都有明确的文字标签，
  不再依赖用户猜颜色。
- **空态文案**：任务中心从「这里空着很正常」改为「怎么让它不空」。
- **导航**：首页主按钮、三步引导、能力卡片、命令面板（⌘K）全部指向已上线能力。

---

## 7. 对上线的实际影响

### 必须做的事（否则行为不符合预期）

1. **设 `TJH_ENV=production`**：否则 `/api/docs` 仍然对外开放。
2. **HTTPS 部署时设 `TJH_COOKIE_SECURE=true`**：否则 Cookie 明文传输。
3. **上 HTTPS 后设 `TJH_HSTS_SECONDS=31536000`**：否则不下发 HSTS。
4. **nginx 配置要填占位符**：`<SITE_ROOT>`、`<DOMAIN>` 两处，漏填 nginx 起不来。
   旧配置里如果有 12345 端口之类的自定义 server 块，需要照新模板自己加回。
5. **若前后端跨域部署**：把来源写进 `TJH_CORS_ORIGINS`，否则写请求会被 `OriginGuard` 拒绝。

### 行为变化（用户可感知）

- 首次加载多一个 `/theme-init.js` 请求（约 300 字节，可缓存）。主题不闪白的行为不变。
- `/api/docs` 在生产环境返回 404。本地开发不受影响。
- 跨站表单直接 POST 到本站接口会被 403。正常页面操作不受影响。

### 不变的部分

- 业务接口签名、数据库结构、能力协议、Agent 工具注册方式均未改动。
- 已有数据无需迁移。

### 风险与待办

| 项 | 说明 |
|---|---|
| CSP 需人工过一遍浏览器 | 只做了构建与响应头验证，没有真实点击。若页面出现空白，先看控制台是否报 CSP 拦截 |
| 限流仍是进程内 | 单机部署够用；多进程 / 多实例需要换 Redis |
| 未做真实浏览器 E2E | 建议上线前按 §8 手点一遍 |
| `index.html` 不要加内联 `<script>` | 会破坏 `script-src 'self'`，需要同步改 CSP |

---

## 8. 验收结果与清单

自动化验证：

```
pytest -q                    203 passed in 5.84s   （含新增 11 项安全测试）
tsc --noEmit                 通过
vite build                   通过（JS 608 KB / gzip 185 KB，CSS 65 KB / gzip 12 KB）
```

手工验证（已在临时实例上确认）：

```
GET  /                       200，带 CSP / X-Frame-Options / nosniff / Referrer-Policy
GET  /theme-init.js          200
GET  /api/docs               404（TJH_ENV=production）
POST 跨站 Origin             403 cross_origin_blocked
POST 同站 Origin             200
GET  带外部 Origin           200（只校验写方法）
```

上线人工清单：

- [ ] 配置模型，上传一份带文本层的 PDF，确认「可问答」状态
- [ ] 上传一份扫描件，确认 OCR 后能检索到页内文字
- [ ] 就 OCR 内容提问，确认答案带页码出处
- [ ] 上传一个不支持的格式，确认报错文案可执行
- [ ] 任务中心能看到 `library.ingest` 任务并实时更新进度
- [ ] 能力管理页里群聊简报显示「公测中」
- [ ] 深色模式下刷新页面不闪白
- [ ] 关闭注册后，注册入口消失且直接调接口返回 403
