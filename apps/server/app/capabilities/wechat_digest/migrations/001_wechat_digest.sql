-- 群聊简报：一次生成任务 = 一条记录（按用户隔离）。
-- 时间字段统一存 ISO 字符串（TEXT），避免与核心表的 Python datetime 时区格式纠缠。
-- 幂等：能力迁移可能因手工重跑而重复执行。

CREATE TABLE IF NOT EXISTS wechat_digests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL DEFAULT 0,
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
    result_json    TEXT NOT NULL DEFAULT '{}',       -- DigestPayload（见 docs/WECHAT-DIGEST.md §4.2）
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wechat_digests_created ON wechat_digests (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wechat_digests_user ON wechat_digests (user_id, created_at DESC);
