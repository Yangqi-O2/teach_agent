# 技术可行性验证记录（后端 / 解析 / 检索）

> 环境：macOS / Apple M4 / Python 3.11.17（`/opt/homebrew/bin/python3.11`）/ SQLite 3.53.4 / venv。
> 结论：**所选后端依赖全部一次安装成功，四种格式解析、FTS5、sqlite-vec、混合检索均验证通过。**
>
> **本文档**：技术选型阶段的实测记录（依赖版本、解析能力、检索性能）
> ｜ **路径**：`docs/VERIFICATION.md` ｜ **状态**：📦 2026-10 快照，记录当时结果，不随代码更新
> ｜ 相关：[`VERIFICATION-CRAWLER.md`](VERIFICATION-CRAWLER.md)（爬虫）、[`VERIFICATION-WECHAT.md`](VERIFICATION-WECHAT.md)（能力验收）

## 1. 依赖版本（实测）

| 包 | 版本 | 状态 |
|---|---|---|
| fastapi | 0.159.1 | ✅ |
| uvicorn[standard] | 0.54.0 | ✅ |
| sqlmodel | 0.0.48（SQLAlchemy 2.1.6 / pydantic 2.14.1） | ✅ |
| pypdf | 6.21.2 | ✅ |
| pdfplumber | 0.11.10（pdfminer.six / pypdfium2 5.14.0） | ✅ |
| python-docx | 1.2.0 | ✅ |
| python-pptx | 1.0.2 | ✅ |
| ebooklib | 0.20 | ✅ |
| beautifulsoup4 | 4.15.0 | ✅ |
| lxml | 6.1.3 | ✅ |
| trafilatura | 2.3.1 | ✅ |
| selectolax | 1.0.1 | ✅ |
| openai | 3.36.1 | ✅ |
| httpx | 0.28.1 | ✅ |
| sse-starlette | 3.5.0 | ✅ |
| numpy | 2.4.6 | ✅ |
| jieba | 0.42.1 | ✅ |
| sqlite-vec | 0.1.9 | ✅ |

冒烟：FastAPI `TestClient /health` 通过；SQLModel 建表/插入/查询正常；`EventSourceResponse` 可导入。

## 2. SQLite 能力

- **FTS5 可用**（`ENABLE_FTS5` 编译选项存在），`bm25()` 排序正常。
- **sqlite-vec 可用**：`enable_load_extension(True)` + `sqlite_vec.load(db)` 后 `vec0` 建表与 `MATCH ... k=` 近邻查询正确（每连接需加载一次）。
- **中文分词坑（必须处理）**：FTS5 `unicode61` 把连续汉字视作单个 token，原文 `"教材解析与混合检索"` 用 `MATCH '检索'` 命中 0 行；`trigram` 要求查询 ≥3 字。→ **jieba 预切词以空格拼接后入索引**，原文另存普通列。
- Linux 发行版 Python 可能未编 FTS5：启动自检 + 降级纯向量。

## 3. 四种格式「带位置文本」最小实现

### 3.1 DOCX（标题栈 + 段落/表格交错）

```python
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

def parse_docx(path):
    doc, heads, out = Document(path), [], []
    for el in doc.element.body.iterchildren():          # 段落/表格保持原顺序
        if el.tag.endswith("}p"):
            p = Paragraph(el, doc); text = p.text.strip()
            if not text: continue
            if (p.style.name or "").lower().startswith("heading"):
                lv = int(p.style.name.split()[-1])
                heads = heads[:lv - 1] + [text]
            out.append({"text": text, "heading_path": list(heads), "page": None})
        elif el.tag.endswith("}tbl"):
            rows = [[c.text.strip() for c in r.cells] for r in Table(el, doc).rows]
            out.append({"type": "table", "heading_path": list(heads), "page": None,
                        "text": " | ".join(" / ".join(r) for r in rows)})
    return out
```

> DOCX 无固定分页，`page` 只能是 `None`；需要页码可先转 PDF（LibreOffice）再按页解析（可选）。

### 3.2 PPTX（含演讲者备注）

```python
from pptx import Presentation

def parse_pptx(path):
    rows = []
    for i, slide in enumerate(Presentation(path).slides, 1):
        texts = [s.text_frame.text.strip() for s in slide.shapes
                 if s.has_text_frame and s.text_frame.text.strip()]
        notes = slide.notes_slide.notes_text_frame.text.strip() if slide.has_notes_slide else ""
        rows.append({"slide": i, "title": texts[0] if texts else "",
                     "text": "\n".join(texts), "notes": notes})
    return rows
```

### 3.3 PDF（pypdf 与 pdfplumber 双路）

```python
from pypdf import PdfReader
import pdfplumber

def parse_pdf_pypdf(path):
    return [{"page": i, "text": (p.extract_text() or "").strip()}
            for i, p in enumerate(PdfReader(path).pages, 1)]

def parse_pdf_plumber(path):
    with pdfplumber.open(path) as pdf:
        return [{"page": i, "text": (p.extract_text() or "").strip()}
                for i, p in enumerate(pdf.pages, 1)]
```

> 含 ToUnicode CMap 的 PDF：两者中文抽取均完整正确；pypdf 行尾多 `\n`，pdfplumber 更干净且有字符坐标（可精确高亮）。无 CMap 的导出件可能乱码 → 三级回退 + OCR 提示。

### 3.4 EPUB（spine 阅读顺序）

```python
from ebooklib import ITEM_DOCUMENT, epub
from bs4 import BeautifulSoup

def parse_epub(path):
    book, out = epub.read_epub(path), []
    for idref, _ in book.spine:
        it = book.get_item_with_id(idref)
        if (it is None or it.get_type() != ITEM_DOCUMENT
                or it.get_name() in ("nav.xhtml", "toc.xhtml")):
            continue
        soup = BeautifulSoup(it.get_content(), "xml")
        h = soup.find(["h1", "h2", "h3"])
        paras = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "li"])]
        out.append({"href": it.get_name(),
                    "chapter": h.get_text(strip=True) if h else it.title,
                    "paras": paras})
    return out
```

> `item.title` 为空串（ebooklib 不解析 `<title>`），章节名必须从 h1/h2 取；必须过滤 `nav.xhtml`。

## 4. OpenAI 兼容客户端

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url="https://llm-gateway.example.com/v1", api_key="sk-xxx")
# 本地 Ollama/vLLM 代理：base_url="http://127.0.0.1:8000/v1", api_key 可填占位符
resp = await client.embeddings.create(model="bge-m3", input=["教材解析"], dimensions=1024)
```

> `openai` 已到 3.x，经典 `OpenAI(...)` / `embeddings.create` 写法仍兼容；`base_url` 必须自带 `/v1` 前缀。

## 5. 混合检索实测（10,000 chunk / Apple M4 / float32）

| 操作 | 耗时 |
|---|---|
| 1024 维余弦点积（10k×1024） | 中位 0.59ms，p95 0.85ms |
| 点积 + top-10（argpartition） | 中位 0.67ms，p95 1.04ms |
| 1536 维点积 + top-10 | 中位 0.96ms |
| FTS5 BM25（jieba 查询） | 中位 1.3–1.7ms |
| **FTS5 + 向量 + RRF 端到端** | **中位 1.93ms，p95 2.43ms** |
| 建 10k chunk + FTS5 索引（含切词） | 1.23s |

内存：10k × 1024 float32 ≈ 39MB。10 万条 ≈ 6–7ms / 400MB 仍可接受；百万级再换 ANN（hnswlib/FAISS）。
瓶颈在 embedding API（50–300ms）与 LLM，不在检索。

**分块参数**：中文 400–600 字/块（≈0.8 token/字），重叠 60–100 字，不跨 H1/H2，标题路径作为上下文头。

**融合**：两路各 top 50，`score(d)=Σ 1/(60+rank_i(d))`，取 top 8–10 送模型。RRF 无需分数量纲对齐，比加权求和稳。
