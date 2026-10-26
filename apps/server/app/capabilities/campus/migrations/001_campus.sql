-- 校园雷达：抓取源、条目、运行记录、全局配置
--
-- 与「每张表都带 user_id」的约定不同：sources / items 是全校共享的公共信息，
-- 不是某个用户的私有数据，因此不带 user_id。用户的私有部分在 user_profiles
-- 与 recommendation 的口味参数里。
--
-- 去重的核心是 campus_items.url 上的 UNIQUE 约束：
-- 同一个通知无论被抓多少次，库里只有一行。

CREATE TABLE IF NOT EXISTS campus_sources (
    id               TEXT PRIMARY KEY,              -- 如 zzu-tzgg
    school_key       TEXT NOT NULL,                 -- 如 zzu
    name             TEXT NOT NULL,
    url              TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'notice',-- notice | news | openinfo | academic
    enabled          INTEGER NOT NULL DEFAULT 1,
    interval_minutes INTEGER NOT NULL DEFAULT 0,    -- 0 = 跟随全局配置
    next_run_at      TEXT,
    last_run_at      TEXT,
    last_status      TEXT,                          -- ok | error | empty
    last_error       TEXT,
    last_created     INTEGER NOT NULL DEFAULT 0,    -- 上次新增条数，用于展示抓取效果
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campus_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     TEXT NOT NULL,
    school_key    TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,             -- 去重键
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT 'other',    -- activity|contest|exam|lecture|policy|other
    published_at  TEXT,                             -- YYYY-MM-DD
    deadline      TEXT,                             -- YYYY-MM-DD，抽不到就是空
    audience      TEXT NOT NULL DEFAULT '',
    tags_json     TEXT NOT NULL DEFAULT '[]',
    is_demo       INTEGER NOT NULL DEFAULT 0,       -- 1 = 内置示例数据，不是真实抓取
    first_seen_at TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_campus_items_school_date
    ON campus_items (school_key, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_campus_items_category
    ON campus_items (category);
CREATE INDEX IF NOT EXISTS idx_campus_items_source
    ON campus_items (source_id);

CREATE TABLE IF NOT EXISTS campus_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    trigger     TEXT NOT NULL DEFAULT 'schedule',   -- schedule | manual | startup
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',    -- running | ok | error
    fetched     INTEGER NOT NULL DEFAULT 0,
    created     INTEGER NOT NULL DEFAULT 0,
    updated     INTEGER NOT NULL DEFAULT 0,
    skipped     INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_campus_runs_source
    ON campus_runs (source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS campus_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
