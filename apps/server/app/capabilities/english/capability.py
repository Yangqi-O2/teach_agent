"""情景英语能力：把独立子项目「情景式英语对话」并入主站。

能力自带：路由（/api/c/english）、SQLite 迁移、按用户设置、以及 3 个 Agent 工具。
内核不需要为它改任何东西——这正是主站能力协议的用途。
"""
from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ...core.capability import Capability, CapabilityManifest, NavItem
from ...core.tools import Tool, ToolContext
from .settings import DEFAULTS

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- Agent 工具


def _normalize_lemma(surface: str) -> str:
    return "".join(ch for ch in (surface or "").lower() if ch.isalpha() or ch in "'-")


async def _save_vocab(ctx: ToolContext, surface: str = "", context: str = "") -> dict[str, Any]:
    """把用户遇到的生词存进生词本（含中文释义与首次复习排程）。"""
    from .agents import gloss, schedule
    from .llm import get_llm
    from .store import execute, json_dump, new_id, now_iso

    if not ctx.user_id:
        raise ValueError("缺少用户上下文")
    lemma = _normalize_lemma(surface)
    if len(lemma) < 2:
        raise ValueError("单词不合法")
    context = (context or "").strip()[:300]
    now = now_iso()
    execute(
        """INSERT INTO english_vocab_items
               (id, user_id, surface, lemma, context_sentence, created_at)
           VALUES (:id, :user_id, :surface, :lemma, :context, :now)
           ON CONFLICT (user_id, lemma) DO NOTHING""",
        id=new_id(), user_id=ctx.user_id, surface=surface.strip()[:40], lemma=lemma, context=context, now=now,
    )
    card = schedule.schedule(schedule.EMPTY, 3)
    execute(
        """INSERT INTO english_vocab_states
               (user_id, lemma, stability, difficulty, reps, lapses, interval_days, last_review_at, next_review_at)
           VALUES (:user_id, :lemma, :stability, :difficulty, :reps, :lapses, :interval_days, :last, :next)
           ON CONFLICT (user_id, lemma) DO NOTHING""",
        user_id=ctx.user_id, lemma=lemma, stability=card.stability, difficulty=card.difficulty,
        reps=card.reps, lapses=card.lapses, interval_days=card.interval_days,
        last=card.last_review_at, next=card.next_review_at,
    )
    gloss_zh = None
    pos = None
    try:
        result = await gloss.gloss_word(lemma, context or lemma, get_llm(ctx.user_id, "planner"))
        if result:
            gloss_zh = result.get("glossZh")
            pos = result.get("pos")
            execute(
                "UPDATE english_vocab_items SET gloss_zh = :gloss, pos = :pos WHERE user_id = :user_id AND lemma = :lemma",
                gloss=gloss_zh, pos=pos, user_id=ctx.user_id, lemma=lemma,
            )
    except Exception as exc:  # noqa: BLE001 - 释义失败不影响存词
        log.warning("english_save_vocab 释义失败: %s", exc)
    return {"lemma": lemma, "gloss_zh": gloss_zh, "pos": pos, "next_review_at": card.next_review_at,
            "interval_days": card.interval_days}


async def _learning_progress(ctx: ToolContext) -> dict[str, Any]:
    """汇总用户当前的英语学习状态：待复习词、高频错误、今日轮数。"""
    from .agents import errors
    from .settings import get_settings
    from .store import day_start_iso, now_iso, one

    if not ctx.user_id:
        raise ValueError("缺少用户上下文")
    patterns = errors.list_patterns(ctx.user_id)
    due = one(
        """SELECT count(*) AS n FROM english_vocab_states
           WHERE user_id = :user_id AND (next_review_at IS NULL OR next_review_at <= :now)""",
        user_id=ctx.user_id, now=now_iso(),
    )
    turns = one(
        """SELECT count(*) AS n FROM english_messages m
           JOIN english_conversations c ON c.id = m.conversation_id
           WHERE c.user_id = :user_id AND m.role = 'assistant' AND m.created_at >= :start""",
        user_id=ctx.user_id, start=day_start_iso(),
    )
    settings = get_settings(ctx.user_id)
    return {
        "due_words": int((due or {}).get("n") or 0),
        "turns_today": int((turns or {}).get("n") or 0),
        "daily_quota": settings["daily_quota"],
        "weak_codes": errors.weak_codes(ctx.user_id, 3),
        "active_patterns": sum(1 for item in patterns if not item.get("improved")),
    }


async def _start_scenario(ctx: ToolContext, domain: str = "", cefr: str = "B1") -> dict[str, Any]:
    """按领域生成一个新的英语情景（会调用一次模型，耗时数秒）。"""
    from .agents import planner
    from .llm import get_llm

    domain = (domain or "").strip()
    if len(domain) < 2:
        raise ValueError("领域太短")
    cefr = cefr if cefr in {"A2", "B1", "B2", "C1"} else "B1"
    plan = planner.plan_scenario(domain[:60], cefr, get_llm(ctx.user_id, "planner"))
    if inspect.isawaitable(plan):  # plan_scenario 允许同步或 async 实现
        plan = await plan
    return {"scenario_id": plan.get("id"), "title_zh": plan.get("title_zh"),
            "title_en": plan.get("title_en"), "topics": len(plan.get("topics") or [])}


# ---------------------------------------------------------------- 能力定义


class EnglishCapability(Capability):
    manifest = CapabilityManifest(
        id="english",
        name="情景英语",
        description=(
            "输入一个领域生成情景卡与话题，AI 以角色身份用英文推进对话；"
            "每轮自动纠错、生词入库、间隔重复、跨会话记忆，把「输出练习」接进学习闭环。"
        ),
        icon="message-square",
        nav=NavItem(label="情景英语", path="/cap/english", order=20),
        version="0.1.0",
        status="stable",
        settings_schema={
            "type": "object",
            "properties": {
                "daily_quota": {
                    "type": "integer", "title": "每日对话轮数上限",
                    "description": "每天最多生成多少条 AI 回复，超出会提示明天再来", "default": DEFAULTS["daily_quota"],
                },
                "partner_model": {
                    "type": "string", "title": "角色扮演模型",
                    "description": "留空则跟随「设置 → 模型接入」里的默认模型", "default": "",
                },
                "planner_model": {
                    "type": "string", "title": "规划 / 纠错模型",
                    "description": "生成情景、纠错、记忆、摘要用；留空则跟随默认模型", "default": "",
                },
                "fallback_model": {
                    "type": "string", "title": "预算降级模型",
                    "description": "月度预算用超 90% 后自动切到更便宜的模型；留空则不降级", "default": "",
                },
                "monthly_token_budget": {
                    "type": "integer", "title": "月度 token 预算",
                    "description": "超过 90% 触发降级", "default": DEFAULTS["monthly_token_budget"],
                },
                "price_in_per_m": {
                    "type": "number", "title": "输入价格（元/百万 token）",
                    "description": "仅用于成本看板估算", "default": DEFAULTS["price_in_per_m"],
                },
                "price_out_per_m": {
                    "type": "number", "title": "输出价格（元/百万 token）",
                    "description": "仅用于成本看板估算", "default": DEFAULTS["price_out_per_m"],
                },
                "repair_enabled": {
                    "type": "boolean", "title": "自动重写不达标回复",
                    "description": "回复缺少问句、过长或含禁用套话时，静默重写一次", "default": True,
                },
                "mock_mode": {
                    "type": "boolean", "title": "离线演示模式",
                    "description": "打开后不调用真实模型，用假数据跑通整条链路（内容为假，仅用于演示）", "default": False,
                },
            },
        },
    )

    def router(self) -> APIRouter | None:
        """router.py 由路由移植任务提供；缺失时只告警，不阻塞主站启动。"""
        try:
            from .router import router
        except Exception:  # noqa: BLE001
            log.exception("english 路由加载失败（能力暂时不可用）")
            return None
        return router

    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parent / "migrations"

    def tools(self) -> list[Tool]:
        return [
            Tool(
                name="english_save_vocab",
                description="把用户在英语对话里遇到的生词存入生词本，自动生成中文释义与首次复习时间。",
                parameters={
                    "type": "object",
                    "properties": {
                        "surface": {"type": "string", "description": "单词原形，例如 demurrage"},
                        "context": {"type": "string", "description": "出现该词的句子，帮助生成准确释义"},
                    },
                    "required": ["surface"],
                },
                handler=_save_vocab,
            ),
            Tool(
                name="english_learning_progress",
                description="查询用户当前的英语学习状态：待复习生词、高频错误类型、今日对话轮数。",
                parameters={"type": "object", "properties": {}},
                handler=_learning_progress,
            ),
            Tool(
                name="english_start_scenario",
                description="按一个领域（如「一带一路」「求职面试」）生成新的英语情景与话题，供角色扮演对话使用。",
                parameters={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "领域或主题"},
                        "cefr": {"type": "string", "enum": ["A2", "B1", "B2", "C1"], "description": "目标水平，默认 B1"},
                    },
                    "required": ["domain"],
                },
                handler=_start_scenario,
            ),
        ]


CAPABILITY = EnglishCapability()
