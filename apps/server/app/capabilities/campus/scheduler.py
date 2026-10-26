"""校园雷达 · 定时抓取。

为什么不用 APScheduler / Celery
-------------------------------
单进程部署，需求是「每个源按间隔跑一次」。一个 asyncio 循环 + `next_run_at` 字段就够，
多引入一个调度器只会多一个故障点。抓取本身是同步 httpx，用 `to_thread` 丢到线程池，
不阻塞事件循环（否则会卡住所有 SSE 流）。

进程重启后 `next_run_at` 还在库里，不会因为重启就把所有源立刻重抓一遍。
"""
from __future__ import annotations

import asyncio
import logging

from . import crawler, store

log = logging.getLogger(__name__)

CHECK_SECONDS = 60          # 每分钟检查一次有没有到期的源
STARTUP_DELAY = 8           # 启动后先让迁移、登录等都就绪
_task: asyncio.Task | None = None


def start() -> None:
    global _task
    from ...config import settings

    if not settings.campus_scheduler:
        log.info("校园雷达自动抓取已关闭（TJH_CAMPUS_SCHEDULER=0），只能手动更新")
        return
    if _task is not None and not _task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.debug("没有运行中的事件循环，跳过校园雷达调度器")
        return
    _task = loop.create_task(_loop(), name="campus-scheduler")
    log.info("校园雷达调度器已启动（每 %d 秒检查一次）", CHECK_SECONDS)


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _task = None


async def _loop() -> None:
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 调度器绝不能因为一次异常停摆
            log.exception("校园雷达调度 tick 异常（已忽略，继续下一轮）")
        await asyncio.sleep(CHECK_SECONDS)


async def tick(trigger: str = "schedule") -> list[dict]:
    """检查并执行到期的源。返回本次执行结果（测试直接调用它）。"""
    config = store.config()
    if config.get("enabled", "1") != "1":
        return []
    if store.interval_minutes() <= 0:
        return []

    due = store.due_sources()
    if not due:
        return []

    results: list[dict] = []
    for source in due:
        # 抓取是同步 IO，放线程里跑，避免阻塞事件循环
        stats = await asyncio.to_thread(crawler.crawl_source, source, trigger=trigger)
        results.append(stats.as_dict())
    return results


async def run_source(source_id: str, trigger: str = "manual") -> dict:
    source = store.get_source(source_id)
    if source is None:
        raise ValueError("抓取源不存在")
    stats = await asyncio.to_thread(crawler.crawl_source, source, trigger=trigger)
    return stats.as_dict()


async def run_all(trigger: str = "manual") -> list[dict]:
    sources = [item for item in store.list_sources() if item.get("enabled")]
    results: list[dict] = []
    for source in sources:
        stats = await asyncio.to_thread(crawler.crawl_source, source, trigger=trigger)
        results.append(stats.as_dict())
    return results
