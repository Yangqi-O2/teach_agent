# 教材库（library 能力）

> 上传教材 → 解析（含扫描件 OCR）→ 按课程分类 → 选定一本提问，**只用这本书的内容**作答，
> 并在每个结论后面标出页码 / 章节。查询不到就直说「教材没有提到」，不拿常识填空。
>
> 页面入口：左侧导航「教材库」→ `/cap/library`。
>
> **本文档**：教材库的实现契约——解析矩阵、OCR 方案、问答约束、API、异常处理总表、验收标准
> ｜ **路径**：`docs/LIBRARY.md` ｜ **状态**：✅ 与 v0.3.0 代码一致

---

## 1. 这个能力之前是什么状态

`app/capabilities/library/` 原本只有 `parsers.py` / `chunking.py` / `models.py` / 一份迁移，
**没有 `capability.py`，也没有 `__init__.py`**。`capabilities.discover()` 用 `pkgutil` 扫不到它，
于是：迁移从未执行（`courses` / `documents` / `chunks` / `chunks_fts` 四张表根本不存在）、
导航里没有入口、`retrieval.py` 是一个只有 6 行 import 的残桩。

这一版把它接成了真能力，并顺手修掉两个会静默丢数据的 bug（见 §9）。

---

## 2. 数据模型

| 表 | 用途 |
|---|---|
| `courses` | 课程 / 分类（名称、颜色、学期、可见性） |
| `documents` | 教材主表：状态、解析统计、OCR 元数据、完整诊断 JSON |
| `chunks` | 分块正文 + 标题路径 + 位置标签（`loc_label` / `loc_index`） |
| `chunks_fts` | FTS5 全文索引（`rowid` 与 `chunks.id` 严格对齐） |
| `qa_threads` / `qa_messages` | 问答会话与历史（引用随答案一起落库） |

`documents.status` 的取值：

```
queued → parsing → indexing → ready
                      ↓
                   partial   （文本可用但有告警）
                      ↓
                    error    （整份不可用）
```

- `ready`：解析完整，可以直接问答。
- `partial`：**能用但不完整**——例如 300 页里 3 页 OCR 失败、或整份扫描件置信度偏低。
  正文照样入库、照样可检索，但详情页会列出具体页码，提示人工核对。
- `error`：一个字都没提取出来。此时**旧索引会被清空**（避免「状态是 error 但还能搜到旧内容」
  的自相矛盾），问答接口对该教材返回 409。

---

## 3. 接入管道

```
上传 ──→ 落盘 data/uploads/library/<id>.<ext>
          │
          ├─ 解析（按格式分发）
          │    docx / pptx / pdf / epub / md / txt / html
          │
          ├─ 判断是否需要 OCR（仅 pdf / image）
          │    pdf：逐页看文本层，< 30 字的页进 OCR 队列
          │    auto = 只补缺口；force = 整本重跑；off = 不做
          │
          ├─ 分块（标题感知 + 物理分页隔离 + 句子边界切长块）
          │
          ├─ FTS5 建索引（jieba 预切词）
          │
          └─ 可选：若供应商配了 embed_model，补向量索引
```

全流程跑在任务中心（线程池）里，进度写库，前端每 2 秒轮询。
任何非预期异常都会被 `service.mark_failed()` 兜住，**不会让文档卡在 `queued` 让前端一直转圈**。

### 3.1 多格式解析矩阵

| 格式 | 解析器 | 位置标签 | 已知失败模式 | 兜底 |
|---|---|---|---|---|
| `.docx` | python-docx | 标题路径（Heading 1–9） | 老式 `.doc` 不支持（扩展名不是 docx） | 明确提示转换格式 |
| `.pptx` | python-pptx | `第 N 张` + 备注 | 纯图片幻灯片无文本 | 该页无块，前端提示 |
| `.pdf` | pypdf → pdfplumber 双引擎 | `第 N 页` | **扫描件无文本层** | 逐页 OCR |
| `.epub` | EbookLib + BeautifulSoup | `第 N 章` | DRM 加密、无 spine | 报 `empty_document` |
| `.md` | 自研（标题栈） | 标题路径 | — | — |
| `.txt` | 自研（空行分段） | `第 N 段` | 编码不是 UTF-8 | `errors="ignore"` 读取 |
| `.html` | BeautifulSoup + lxml | 标题路径 | 纯 JS 渲染页 | 正文为空则报错 |
| `.png/.jpg/.webp` | 无（直接进 OCR） | `第 1 页` | 图片过小 / 严重倾斜 | 置信度告警 |

PDF 的两个引擎是有意叠加的：`pypdf` 快但对复杂排版会漏，`pdfplumber` 慢但还原度好。
判定规则是「平均每页少于 20 字就换 `pdfplumber` 再试一次」。

### 3.2 分块参数

| 参数 | 值 | 说明 |
|---|---|---|
| `TARGET_CHARS` | 520 | 累积到这个长度就切 |
| `MAX_CHARS` | 900 | 超过就按句边界二次切分 |
| `OVERLAP_CHARS` | 80 | 长块切分时保留的重叠上下文 |
| `MIN_KEEP_CHARS` | 10 | 低于此长度且形如页码才当噪声丢弃 |

**PDF / PPT 每页强制独立成块**，否则引用会指到错误的页码。

---

## 4. 扫描件 OCR

### 4.1 后端选择

| 平台 | 引擎 | 栅格化 | 依赖 |
|---|---|---|---|
| macOS（**本项目的唯一目标平台**） | **Vision**（`VNRecognizeTextRequest`，accurate 模式，`zh-Hans` + `en-US`） | PDFKit（同一个 Swift 工具里完成） | 只需 Xcode Command Line Tools 提供 `swiftc` |
| Linux / Windows | tesseract（需 `chi_sim` 语言包） | PyMuPDF | `tesseract-ocr` + `pip install pymupdf` |

> **平台支持**：三个平台都可部署，只是后端不同——macOS 用系统 Vision（识别质量最好、零 Python 依赖），
> Linux / Windows 用 tesseract + pypdfium2 栅格化。macOS 上若没有 `swiftc`，会**自动退回 tesseract**，
> 不会因为缺工具就让整条链路不可用。实际用的是哪个引擎，`python3 scripts/task.py doctor` 会直接打印。
> 部署细节见 `docs/DEPLOY.md`。

macOS 走的是「一个自编译的小工具干完全部」：Swift 源码内嵌在 `ocr.py` 里，首次使用用
`swiftc -O` 编译到 `data/cache/ocr/ocr_tool` 并缓存。这样**不需要安装任何 Python 包**，
也不需要把 PDF 先落成 PNG 再读回来。

> 为什么不用 `swift script.swift`：解释执行首次要 40 秒以上；预编译约 2 秒（一次性），
> 之后按页计费。**实测（10 页密集中文正文 / 每页约 970 字 / 150 DPI）**：
> 纯 OCR 4.17 秒（**约 0.42 秒/页**），端到端「解析→OCR→分块→建索引」4.98 秒，识别置信度 0.97。
> 稀疏页（只有几行字）能到 0.17 秒/页，但**不要用稀疏页的数字估算整本书**——
> 耗时与检测到的文本行数正相关，差三倍很常见。

### 4.2 质量判定

每页返回「文本 + 平均置信度」，并按三条规则产出告警：

| 情况 | 告警码 | 等级 | 处理 |
|---|---|---|---|
| 整份都是 OCR 出来的 | `ocr_all` | info | 详情页注明来源，不阻塞 |
| 只有部分页 OCR | `ocr_used` | info | 注明补了几页 |
| 有页识别为空 | `ocr_partial` | warn | 列出失败页码，状态 → `partial` |
| 平均置信度 < 0.55 | `ocr_low_quality` | warn | 提示「引用前请核对原文」 |
| OCR 后仍有页无字 | `pdf_no_text_layer` | warn | 保持告警 |
| 没有可用引擎 | `ocr_unavailable` | error | 状态 → `error` + 安装指引 |

**低置信度文本仍然入库。** 这是有意的取舍：一团糊的字可能只错几个，
但整页丢弃就是 100% 的信息损失；把判断权交给用户，比替用户做决定更合理。

### 4.3 已知限制

- 公式与表格结构不做结构化还原（OCR 只出线性文本）。
- 竖排 / 手写体识别率明显下降，会体现在置信度上。
- 单页渲染宽上限 2600px，A0 图纸会被降采样，小字号可能丢。
- 整本强制 OCR 是线性耗时，500 页大约 3~5 分钟，建议走任务中心异步等。

---

## 5. 教材问答

### 5.1 三条硬约束

1. **检索不到就不调模型。** 命中为空时直接返回固定话术（"这份教材里没有找到…"），
   既省钱，也彻底杜绝编造。这条有单测守着（`test_ask_without_match_skips_model` 断言
   假模型的调用次数为 0）。
2. **引用必须回验。** 模型写 `[3]`，就必须真的存在第 3 段；`[99]` 这种越界编号会被丢弃，
   并记进 `meta.bad_markers`。这和英语能力里「span 必须在原文中出现」是同一个原则：
   **不信模型自报的定位信息**。
3. **没标注就明说。** 一个引用都没有时置 `citation_ok=false`，前端在答案下方提示核对，
   不假装它是有据的。

### 5.2 检索

- **BM25**：`chunks_fts` 用 jieba 预切词后的空格串建索引，查询同样切词后 `OR` 连接。
  中文必须预切词——SQLite 的 unicode61 不理解分词，`应力张量` 会被当成一个 token，
  用户搜「张量」就命中不了。
- **向量（可选）**：供应商配了 `embed_model` 才启用；两路结果用 **RRF** 融合。
  RRF 只看名次不看分数，省掉了「BM25 分与余弦相似度不可比」的问题。
- **兜底**：FTS 一条都没命中时退回 `LIKE` 逐词扫描。OCR 文本常有奇怪断行，
  「能搜到」优先于「排得好」。

参数：候选池 50，向量池 2000，`RRF_K=60`，上下文上限 5200 字。

### 5.3 权限

```
读：user_id = 我  or  visibility = 'shared'
写/删：owner 或 管理员
问答检索范围 = （我能看到的教材）∩（我点名的教材）
```

越权传别人的 private 教材 id → 403；带 shared 教材 → 可读可问，改删 403。

---

## 6. API（前缀 `/api/c/library`，全部要求登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | OCR 引擎状态、可解析格式、文档计数 |
| GET/POST | `/courses` | 分类列表 / 新建 |
| PATCH/DELETE | `/courses/{id}` | 改名改色 / 删除（文档转未分类） |
| GET | `/documents` | 列表（`course` / `status` / `q` 过滤） |
| GET | `/documents/{id}` | 详情（含 warnings、parse、ocr 诊断） |
| GET | `/documents/{id}/chunks` | 分块预览；带 `q` 时走检索，用来核对解析质量 |
| POST | `/documents/upload` | multipart：`file` / `course_id` / `visibility` / `ocr_mode` / `title` |
| PATCH | `/documents/{id}` | 改标题 / 分类 / 可见性 / OCR 策略 |
| POST | `/documents/{id}/reparse` | 重新解析（可换 OCR 策略） |
| DELETE | `/documents/{id}` | 删除教材与索引 |
| POST | `/qa` | **SSE**：`status` → `delta`* → `citations` → `done` / `error` |
| GET | `/qa/threads`、`/qa/threads/{id}` | 问答历史 |
| GET | `/search` | 直接检索（调试用） |

Agent 工具：`library_search`、`library_list_documents`。

---

## 7. 异常处理总表

所有告警用**闭合枚举**（`WARN` 表，14 个码），每种都有确定的等级与用户可执行动作：

| 码 | 等级 | 用户看到什么 | 能做什么 |
|---|---|---|---|
| `empty_document` | error | 没有解析出任何文本 | 检查文件是否为空 / 换格式 |
| `encrypted` | error | 文件已加密 | 去掉密码后重传 |
| `corrupt_file` | error | 文件损坏或扩展名不符 | 重新导出 |
| `ocr_unavailable` | error | 没有可用 OCR 引擎 | macOS 装 Xcode CLT；其他装 tesseract |
| `pdf_no_text_layer` | warn | 缺少可检索文本层 | 开 OCR 重新解析 |
| `ocr_partial` | warn | 有页面 OCR 失败 | 看失败页码，必要时对该页单独处理 |
| `ocr_low_quality` | warn | 置信度偏低 | 对照原文核对引用 |
| `ocr_render_failed` | warn | 页面渲染失败 | 换 PyMuPDF 或降低 DPI 重试 |
| `text_layer_low` | warn | 文本层偏少（图文混排） | 开 OCR 补全 |
| `no_chunks` | warn | 切不出可检索段落 | 内容过短，属正常 |
| `embedding_failed` | warn | 向量索引失败 | 已退化为关键词检索，可忽略 |
| `ocr_used` / `ocr_all` | info | 已 OCR | 无 |
| `embedding_skipped` | info | 未配向量模型 | 无（纯 BM25 可用） |

**原则：error 一定有下一步动作，warn 一定带具体位置，info 只做说明。**

---

## 8. 验收标准

### 8.1 自动化（随仓库可复跑）

```bash
cd apps/server && .venv/bin/python -m pytest -q
```

| 断言 | 结果 |
|---|---|
| 后端测试总数 | **192 passed**（新增 38 项：18 API + 20 核心） |
| 一次运行耗时 | 6.2 s |
| 能力被 `discover()` 扫到 | ✅ `library (教材库)` |
| 迁移自动执行 | ✅ `library/001` + `library/002` |

新增用例覆盖：

- 分块：中文断句、小数点/缩写不切断、短页不丢失、页码噪声过滤、跨页不合并
- 切词：停用词过滤、中文 token 分离
- 解析：txt 段落定位、docx 标题路径、不支持格式拒绝、图片交给 OCR
- OCR：探测结果结构、无引擎时报 `ocr_unavailable`、置信度统计、低质量页标记
- 引用：越界编号丢弃、无引用标记 `citation_ok=false`
- 检索：RRF 融合、上下文编号、超长截断、纯停用词返回空
- 上传：txt 全链路可检索、reparse、删除、不支持扩展名 415
- 权限：private 对他人 404、shared 可读不可改、越权提问 403
- 问答：带引用回答、无命中不调模型、越界引用记录、空 scope 走全库
- 异常：扫描件无引擎→error、OCR 成功→ready 且可检索定位到页码、OCR off→可执行报错、
  解析失败清空旧索引
- 注册：工具进 `/api/tools`、能力进导航

### 8.2 人工验收（10 分钟）

| # | 步骤 | 期望 |
|---|---|---|
| 1 | 打开「教材库」，点「上传教材」 | 弹窗出现，OCR 策略可选 自动/强制/关闭 |
| 2 | 传一份带标题的 docx，勾选「公开给所有成员」 | 左侧出现该教材，进度条走完变「可问答」，标「共享」 |
| 3 | 点「解析内容」 | 能看到分块、标题路径、字数；检索框可搜到关键词 |
| 4 | 回到「教材问答」，问书里明确写过的概念 | 流式输出，答案下方出现出处；点开显示原文与页码 |
| 5 | 问一个书里没有的（如跨学科问题） | 回答「没有找到相关内容」，**不出现模型自由发挥** |
| 6 | 传一份扫描版 PDF（或直接传手机拍的 png） | 进度完成后状态「可问答」，详情显示 `OCR: vision` 与置信度 |
| 7 | 对第 6 步的教材提问 OCR 出来的内容 | 能命中，且出处页码正确 |
| 8 | 同一教材点「重新解析」并选「关闭」OCR | 状态变「解析失败」，错误信息说明是扫描件、建议开 OCR |
| 9 | 用第二个账号登录 | 看不到 private 教材；shared 能读、不能删 |
| 10 | `GET /api/c/library/health` | `ocr.available=true`、`pdf_ready=true`、格式列表含 image |

### 8.3 性能基线（本机 M 系列、2 页扫描件实测）

| 指标 | 实测 |
|---|---|
| Swift OCR 工具首次编译 | 0.8 s（之后复用） |
| 单页 OCR | 0.10 ~ 0.20 s |
| 2 页扫描件端到端（含索引） | 1.7 s |
| txt 全链路（上传 → 可检索） | < 0.5 s |

---

## 9. 本次修掉的两个静默丢数据 bug

这两个都不是「功能缺失」，而是**已经在跑、但会悄悄丢内容**的缺陷：

1. **`chunking.py` 双重转义。** `re.split(r"(?<=[。！？；.!?])\\s*", text)` 里是 `\\s*`
   而不是 `\s*`，正则实际匹配「反斜杠 + s」，句子根本切不开；`"\\n".join(...)` 同理，
   段落之间拼进去的是字面量 `\n` 两个字符。表现是：整份教材变成一坨，检索精度极差。
   已改为正确的 `\s*` / `"\n"`，并补了断句单测。

2. **短页被整段丢弃。** 原来的过滤条件是 `n_chars >= 30`，扫描件里「一页就两三行字」
   的页会被无声删掉，`chunk_count` 显示 0，用户只看到「解析成功但搜不到」。
   现在只过滤长度 < 10 且形如页码的噪声（`- 12 -`、`第 3 页`）。

另外修掉一个并发下的确定性故障：`last_insert_rowid()` 是**连接级**的，
先 `execute(INSERT)` 再 `one(SELECT ... last_insert_rowid())` 会落到连接池里的不同连接，
拿到 0 → 上传直接 500。改为 `store.insert()` 在同一连接内取 `lastrowid`。
这个问题单独跑不会复现，**只有在多次上传后连接池换连接时才炸**，是测试跑出来的。

---

## 10. 已知限制

- 分类不做嵌套（一层），够用但不支持「课程 → 章节」两级。
- 问答历史按会话存库，但前端目前只展示单次会话内的轮次，跨会话回看接口已有、UI 未接。
- 教材删除是硬删除，没有回收站。
- 大文件（>60MB）直接拒绝，不做分片上传。
- Agent 工具已注册但主站还没有 Agent 主循环去调用它们（与 `FRAMEWORK.md §12` 的限制一致）。
