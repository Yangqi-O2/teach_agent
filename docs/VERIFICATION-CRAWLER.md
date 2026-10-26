# 可行性验证记录（校园雷达 / 高校通知爬取）

> 调研时间 2026-10-22。方法：每站一次只读 GET（Chrome UA），配合人工核对列表与详情页；另各请求一次 `/robots.txt`。全程未登录、未使用校园网、未尝试规避任何访问控制。
> 结论：**纯 `httpx + lxml` 可覆盖约 85%–90% 的高校教务处通知列表**，零配置启发式在 15/15 个页面正确定位列表容器，trafilatura 正文抽取 6/6 成功。
>
> **本文档**：校园雷达的爬虫可行性实测（站点覆盖、页面骨架分类、合规红线）
> ｜ **路径**：`docs/VERIFICATION-CRAWLER.md` ｜ **状态**：📦 快照，不随代码更新
> ｜ 该能力本身仍为 🧭 规划中，仅完成可行性验证

## 1. 站点验证表

| 学校（单位） | 列表页 URL | 可访问性 | 渲染 | RSS | robots | 备注 |
|---|---|---|---|---|---|---|
| 北京大学 教务部 | `https://dean.pku.edu.cn/web/notice.php` | 200 | 静态 | 无 | 403（WAF 页） | 自建 PHP；15 条/页，47 页；`?page=N` |
| 上海交大 教务处 | `https://jwc.sjtu.edu.cn/xwtg/tztg.htm` | 200 | 静态 | 无 | 404 | 博达 Webplus(JSP)；10 条/页，237 页；分页递减 |
| 复旦 教务处 | `https://jwc.fudan.edu.cn/9397/list.htm` | GET 200 / **HEAD 403** | 静态 | 无 | 404 | 博达 PHP；14 条/页，35 页；`list2.htm…` |
| 华中科大 本科生院 | `https://ugs.hust.edu.cn/tzgg.htm` | GET 200 / **HEAD 403** | 静态 | 无 | 404 | 博达 JSP；20 条/页，141 页；旧域已无 DNS |
| 武汉大学 本科生院 | `https://uc.whu.edu.cn/tzgg.htm` | 200 | 静态 | 无 | 404 | 博达定制；25 条/页，49 页；链接两种形态 |
| 西安交大 教务处 | `https://jwc.xjtu.edu.cn/jxxx/jxtz2.htm` | 200 | 静态 | 无 | 404 | 博达 JSP；9 条/页，625 页；标题带 `[分类]` |
| 北航 教务部 | `https://jiaowu.buaa.edu.cn/tzgg/xszq.htm` | 200 | 静态 | 无 | 404 | 博达 + WAF；10 条/页，4 页 |
| 中山大学 教务部 | `https://jwb.sysu.edu.cn/newscenter/notice` | 200 | 静态 SSR | 无 | 403（WAF 屏蔽） | Drupal；20 条/页；约 70% 条目外链公众号 |

反例（对覆盖率判断很重要）：

- **清华**：`tsinghua.edu.cn/jwc/` 只有部门概况，**无通知公告栏目**；本科通知走校内信息门户（需登录）→ 不抓。
- **浙大**：本科生院无「通知公告」栏目；研究生院是 **Vue SPA**，纯 HTML 只能拿到空壳。

## 2. 页面骨架的 3 类（覆盖 8/8）

1. **博达 Webplus 家族（6/8）**：列表 `li`/`tr`，标题在 `a`，日期为兄弟节点文本；详情正文容器固定为 `#vsb_content` / `.v_news_content`。指纹：`/system/resource/js/`、`line_u12_*`、`list.jsp?urltype=tree.TreeTempUrl`、`info/1234/5678.htm`。
2. **自建 PHP（北大）**：`div.notice_item > div.notice_box > span(日期) + a(标题)`。
3. **Drupal（中大）**：`div.newslists > div.newslist`，日期在 `time[datetime]`。注意 `js-view-dom-id-<hash>` 每次渲染都会变，**不能写进选择器**。

## 3. 日期落位（真正的难点）

| 落位方式 | 站点 | 策略 |
|---|---|---|
| 完整日期文本 | PKU / FUDAN / HUST / WHU / XJTU / BUAA | 正则直取 |
| 拆成两个节点（`19` + `2026.10`） | SJTU | 年月 + 日号合并回退 |
| `time[datetime]` ISO 属性 | SYSU | 优先属性，其次文本 |

## 4. 实测数据

- 零配置启发式（同构兄弟节点 + 可解析日期）在 **15/15** 页面（8 基线 + 7 抽检，含子栏目与第 2 页）命中正确容器，条目数与实际一致。
- trafilatura 抽详情正文 **6/6** 成功（北大 1888 字、武大 682、华科 1180、西交 1331、北航 887、中大 1075）；仅武大尾部残留 ICP 备案信息。
- **标题不能取详情页 h1**（博达详情 h1 常是栏目名，如北航取到「学生专区 通知公告」）→ 标题取列表页 `a[title]` 或 `a` 文本。
- 附件：北大、中大详情页带 `.doc/.docx` 附件 → 只收集链接，不下载解析。

## 5. 结论与架构建议

```
调度器（夜间、按校错峰、单站并发=1）
  └─ httpx.AsyncClient（仅 GET / 真实 UA / 2–5s 抖动 / 退避 / 304 缓存）
       └─ 列表解析：适配器优先 → 启发式兜底（失败自动生成候选适配器，人工确认）
       └─ 归一化：相对 URL 绝对化、日期→ISO、标题取 a[title]、hash(url|title) 去重
       └─ 详情：trafilatura 抽正文 + 收集附件链接
       └─ 仅 requires_js=true 或连续空结果时：Playwright 单页渲染（缓存 24h）
存储：SQLite（school/unit/url/title/published_at/fetched_at/content/hash）
监控：0 条目、日期解析失败率 >20%、403 → 告警并停抓该域
```

关键取舍：**默认不引入 Playwright**（Windows/macOS 分发体积大），做成可选插件；**不做全站镜像**，只做「列表增量 + 按需详情」。

## 6. 合规红线（实测依据）

1. `robots.txt` 缺失 ≠ 授权（6/8 站点 404，2 站返回 403 错误页）。
2. 只用 GET：HEAD 会被 WAF 拒绝，健康检查必须 GET。
3. 单站 1 请求 / 2–5s，带 ±30% 抖动；单轮只抓前 1–3 页；夜间执行；403/429 立即停止并退避，不换 IP、不换 UA、重试 ≤2 次。
4. UA 声明用途与联系方式（如 `EduNoticeBot/0.1 (+mailto:…)`）。
5. 绝不触碰：正方/URP 教务系统（登录、成绩、学籍）、统一身份认证、验证码、校园网限定资源。
6. 微信公众号外链条目只存标题 + 链接，不镜像正文（版权）。
7. 持久化 ETag/Last-Modified，命中 304 不重复解析；只存必要字段。
