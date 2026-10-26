"""校园雷达 · 抓取与解析。

设计要点
--------
1. **列表页每次抓、详情页按需抓。** 列表页便宜（一个请求拿到几十条），
   详情页贵。已入库的 URL 直接跳过，这是「避免重复爬取」的第一层；
   入库后正文 hash 不变也跳过，这是第二层。
2. **失败隔离。** 单个源挂了只影响它自己：记录 error、安排下次重试，
   不抛给调用方，也不影响其他源。
3. **不伪造。** 抓不到就是抓不到，`last_status=error` 会显示在界面上。
   内置示例数据单独走 `seed.py`，并且打 `is_demo=1` 标记，不和真实数据混在一起。
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from lxml import html as LH

from . import classify, store

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 TianjianhuBot/0.1"
)
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_LIST_ITEMS = 60

# 抓取串行化：见 crawl_source 里的注释。超时后放弃本次而不是无限等待。
_CRAWL_LOCK = threading.Lock()
_CRAWL_LOCK_TIMEOUT = 180


class CrawlError(RuntimeError):
    pass


@dataclass
class Entry:
    """列表页里的一条候选。此时还没有正文。"""

    title: str
    url: str
    published_at: str | None = None
    snippet: str = ""


@dataclass
class CrawlStats:
    source_id: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    status: str = "ok"
    error: str = ""
    entries: list[Entry] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "status": self.status,
            "error": self.error,
        }


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )


def _same_site(url: str, base: str) -> bool:
    """只收同校域名下的链接，避免抓到站外广告或 CDN 资源。"""
    try:
        host = urlsplit(url).hostname or ""
        base_host = urlsplit(base).hostname or ""
    except ValueError:
        return False
    if not host or not base_host:
        return False
    if host == base_host:
        return True
    # www.zzu.edu.cn 与 jw.zzu.edu.cn 视为同一所学校
    return host.split(".", 1)[-1] == base_host.split(".", 1)[-1]


def _clean_title(raw: str) -> str:
    text = re.sub(r"[\s\u3000]+", " ", raw or "").strip()
    text = text.lstrip("·•　 ")
    # 去掉标题两侧粘连的日期：有的栏目把日期放在标题前面（"2026-10-24 我校…"），
    # 有的放在后面。留着会让标题看起来像"日期 + 半句话"。
    date_pattern = r"(20\d{2}[-/\.]\d{1,2}[-/\.]\d{1,2}|\d{1,2}[-/]\d{1,2})"
    text = re.sub(rf"^\s*{date_pattern}\s*", "", text)
    text = re.sub(rf"\s*{date_pattern}\s*$", "", text)
    return text.strip()


def _document(payload: bytes | str):
    """把页面转成 lxml 文档，并处理中文站点常见的编码问题。

    直接给 lxml 喂 bytes 时，若页面没有 <meta charset>，它会按 latin-1 解析，
    中文标题会变成乱码。这里先按 utf-8 / gb18030 试解码，都失败再交回 lxml
    让它按页面自己声明的编码处理。
    """
    if isinstance(payload, str):
        return LH.fromstring(payload)
    for encoding in ("utf-8", "gb18030"):
        try:
            return LH.fromstring(payload.decode(encoding))
        except (UnicodeDecodeError, ValueError):
            continue
    return LH.fromstring(payload)


def parse_list(html_text: bytes | str, base_url: str, reference: date | None = None) -> list[Entry]:
    """从列表页/首页里挑出「像一条通知」的链接。

    不用固定 CSS 选择器：高校站点模板经常改版，而「文字够长、链接像文章页、
    旁边有日期」这三条对几乎所有栏目都成立。
    """
    try:
        doc = _document(html_text)
    except (ValueError, LH.ParserError) as exc:  # pragma: no cover - 畸形页面
        raise CrawlError(f"列表页无法解析：{exc}") from exc

    for tag in doc.xpath("//script | //style | //nav | //footer"):
        tag.getparent().remove(tag)

    entries: list[Entry] = []
    seen: set[str] = set()

    for anchor in doc.iter("a"):
        raw_text = _clean_title(anchor.text_content() or "")
        href = (anchor.get("href") or "").strip()
        if len(raw_text) < 8 or not href:
            continue
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        try:
            url = urljoin(base_url, href)
        except ValueError:
            continue
        if not url.startswith(("http://", "https://")) or not _same_site(url, base_url):
            continue
        url = url.split("#", 1)[0]
        if url in seen:
            continue

        # 「像文章页」的链接通常带 /info/、/content/、数字 id 或 .htm
        article_like = bool(re.search(r"(/info/|/content/|/article/|/\d{4,}|\.htm|\.html?)", url))
        if not article_like and len(raw_text) < 16:
            continue

        # 日期常常在 <a> 外面的同级 <span> 里，所以总是把父节点文本带上
        parent = anchor.getparent()
        context = raw_text
        if parent is not None:
            context = f"{raw_text} {(parent.text_content() or '')[:200]}"
        published = classify.published_date(context, reference)

        # 首页上「学院设置」「学生工作网站」这类导航链接也满足「文字够长」，
        # 但它们既没有日期，URL 里也没有文章 id。两个条件都不满足就丢掉。
        has_id = bool(re.search(r"/(?:info|content|article)/\d+/\d+|/\d{5,}", url))
        if not (published or has_id):
            continue

        entries.append(Entry(title=raw_text[:200], url=url, published_at=published))
        seen.add(url)
        if len(entries) >= MAX_LIST_ITEMS:
            break

    return entries


def extract_detail(html_bytes: bytes, url: str) -> str:
    """正文抽取。trafilatura 失败时退回 lxml 的纯文本。"""
    try:
        text = trafilatura.extract(
            html_bytes,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
    except Exception as exc:  # noqa: BLE001 - 抽取器内部异常不应打断抓取
        log.debug("trafilatura 抽取失败 %s: %s", url, exc)
        text = None
    if text and len(text.strip()) >= 40:
        return text.strip()
    try:
        doc = _document(html_bytes)
        for tag in doc.xpath("//script | //style | //nav | //footer"):
            tag.getparent().remove(tag)
        fallback = re.sub(r"\s+", " ", doc.text_content() or "").strip()
        return fallback[:20000]
    except Exception:  # noqa: BLE001
        return ""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:32]


def title_key(title: str) -> str:
    """标题归一化后用于判重。

    同一份通知在首页、「通知公告」列表、部门转载页里会以不同 URL 出现，
    只按 URL 去重会让用户看到三条一模一样的通知。这里把标点、空白、
    「关于…的通知」这类模板词去掉后再比。
    """
    text = re.sub(r"[\s\u3000，。？！、；：“”‘’（）()《》〈〉\-—·.,!?;:]+", "", title or "")
    return text.lower()[:80]


def known_titles(school_key: str, limit: int = 800) -> set[str]:
    rows = store.q(
        "SELECT title FROM campus_items WHERE school_key = :k ORDER BY id DESC LIMIT :limit",
        k=school_key,
        limit=limit,
    )
    return {title_key(row["title"]) for row in rows}


def build_item(source: dict[str, Any], entry: Entry, content: str, *, is_demo: bool = False) -> dict:
    category = classify.classify(entry.title, content)
    return {
        "source_id": source["id"],
        "school_key": source["school_key"],
        "url": entry.url,
        "title": entry.title,
        "summary": classify.summarize(entry.title, content),
        "content": content,
        "content_hash": _hash(f"{entry.title}\n{content}"),
        "category": category,
        "published_at": entry.published_at,
        "deadline": classify.extract_deadline(f"{entry.title}\n{content}"),
        "audience": classify.extract_audience(content or entry.title),
        "tags": classify.extract_tags(entry.title, content),
        "is_demo": is_demo,
    }


def crawl_source(
    source: dict[str, Any],
    *,
    trigger: str = "manual",
    max_detail: int | None = None,
    client: httpx.Client | None = None,
) -> CrawlStats:
    """抓一个源。异常被收敛成 CrawlStats.status == 'error'，不向外抛。"""
    stats = CrawlStats(source_id=source["id"])
    # 定时任务与「立即更新」可能同时触发同一个源：两个线程都会「先查不到、再插入」，
    # 撞上 url 的 UNIQUE 约束；而且对方站点会瞬间收到双倍请求。统一串行化。
    if not _CRAWL_LOCK.acquire(timeout=_CRAWL_LOCK_TIMEOUT):
        stats.status = "error"
        stats.error = "已有抓取任务正在运行，请稍后再试"
        log.warning("校园雷达 %s：并发抓取被串行化，本次跳过", source["id"])
        return stats

    own_client = client is None
    run_id = 0
    http = client or _client()
    limit = (
        max_detail
        if max_detail is not None
        else int(store.config().get("max_detail_per_run", "24"))
    )
    try:
        run_id = store.start_run(source["id"], trigger)
        try:
            response = http.get(source["url"])
        except httpx.HTTPError as exc:
            raise CrawlError(f"请求失败：{type(exc).__name__}") from exc
        if response.status_code != 200:
            # 很多高校站点的 404 页面仍返回完整首页，必须先看状态码再看内容
            raise CrawlError(f"HTTP {response.status_code}")

        entries = parse_list(response.content, str(response.url))
        stats.entries = entries
        stats.fetched = len(entries)
        if not entries:
            stats.status = "empty"
            store.mark_source(source["id"], status="empty", error="页面没有解析出任何条目")
            store.finish_run(run_id, status="ok", fetched=0)
            return stats

        # 已入库的标题（含同校其他源），用于跨 URL 判重
        seen_titles = known_titles(source["school_key"])
        detail_budget = max(0, limit)
        for entry in entries:
            key = title_key(entry.title)
            if key in seen_titles:
                stats.skipped += 1
                continue
            if store.find_item_by_url(entry.url) is not None:
                stats.skipped += 1
                seen_titles.add(key)
                continue
            seen_titles.add(key)

            content = ""
            if detail_budget > 0:
                detail_budget -= 1
                try:
                    detail = http.get(entry.url)
                    if detail.status_code == 200:
                        content = extract_detail(detail.content, str(detail.url))
                except httpx.HTTPError as exc:
                    log.info("详情页抓取失败 %s: %s", entry.url, exc)

            outcome = store.upsert_item(build_item(source, entry, content))
            if outcome == "created":
                stats.created += 1
            elif outcome == "updated":
                stats.updated += 1
            else:
                stats.skipped += 1

        stats.status = "ok"
        store.mark_source(source["id"], status="ok", created=stats.created)
        store.finish_run(
            run_id,
            status="ok",
            fetched=stats.fetched,
            created=stats.created,
            updated=stats.updated,
            skipped=stats.skipped,
        )
        log.info(
            "校园雷达 %s：抓 %d 条，新增 %d，更新 %d，跳过 %d",
            source["id"],
            stats.fetched,
            stats.created,
            stats.updated,
            stats.skipped,
        )
    except CrawlError as exc:
        stats.status = "error"
        stats.error = str(exc)
        store.mark_source(source["id"], status="error", error=stats.error)
        store.finish_run(run_id, status="error", error=stats.error)
        log.warning("校园雷达 %s 抓取失败：%s", source["id"], exc)
    except Exception as exc:  # noqa: BLE001 - 任何未预期异常都不能拖垮调度循环
        stats.status = "error"
        stats.error = f"{type(exc).__name__}: {exc}"
        store.mark_source(source["id"], status="error", error=stats.error)
        store.finish_run(run_id, status="error", error=stats.error)
        log.exception("校园雷达 %s 未预期异常", source["id"])
    finally:
        if own_client:
            http.close()
        store.schedule_next(source)
        _CRAWL_LOCK.release()

    return stats


def crawl_all(*, trigger: str = "manual", school_key: str | None = None) -> list[dict[str, Any]]:
    sources = store.list_sources()
    if school_key:
        sources = [item for item in sources if item["school_key"] == school_key]
    results: list[dict[str, Any]] = []
    with _client() as shared:
        for source in sources:
            if not source.get("enabled"):
                continue
            stats = crawl_source(source, trigger=trigger, client=shared)
            results.append(stats.as_dict())
    return results
