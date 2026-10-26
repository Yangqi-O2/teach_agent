-- 情景英语（english）能力的全部表。
-- 从独立子项目 etutor-cn 的 Postgres schema 移植到 SQLite：
--   uuid → TEXT（uuid4 hex）      jsonb / text[] → TEXT 存 JSON
--   timestamptz → TEXT（UTC ISO-8601 字符串，可直接排序比较）
--   user_id 用主站 users.id（INTEGER）
-- 支付 / 会员 / 订单 / 转移码表按产品决定不迁移。

CREATE TABLE IF NOT EXISTS english_scenarios (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    title_zh    TEXT NOT NULL,
    title_en    TEXT NOT NULL,
    domain      TEXT NOT NULL,
    cefr        TEXT NOT NULL DEFAULT 'B1',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_en_scenarios_created ON english_scenarios (created_at DESC);

CREATE TABLE IF NOT EXISTS english_topics (
    id            TEXT PRIMARY KEY,
    scenario_id   TEXT NOT NULL,
    title         TEXT NOT NULL,
    beats         TEXT NOT NULL DEFAULT '[]',
    target_tenses TEXT NOT NULL DEFAULT '[]',
    target_lexis  TEXT NOT NULL DEFAULT '[]',
    difficulty    TEXT NOT NULL DEFAULT 'B1',
    used_count    INTEGER NOT NULL DEFAULT 0,
    last_used_at  TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_en_topic_scenario ON english_topics (scenario_id, used_count);

CREATE TABLE IF NOT EXISTS english_conversations (
    id             TEXT PRIMARY KEY,
    user_id        INTEGER NOT NULL,
    scenario_id    TEXT NOT NULL,
    topic_id       TEXT,
    rolling_summary TEXT,
    summarized_upto INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    last_message_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_en_conv_user ON english_conversations (user_id, last_message_at);

CREATE TABLE IF NOT EXISTS english_messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content_md      TEXT NOT NULL,
    model           TEXT,
    latency_ms      INTEGER,
    ttft_ms         INTEGER,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_micros     INTEGER,
    metrics         TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_en_msg_conv ON english_messages (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS english_error_events (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    message_id  TEXT NOT NULL,
    code        TEXT NOT NULL,
    span        TEXT NOT NULL,
    correction  TEXT NOT NULL,
    explain_zh  TEXT NOT NULL,
    severity    TEXT NOT NULL,
    confidence  REAL NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_en_err_user ON english_error_events (user_id, code, created_at DESC);

CREATE TABLE IF NOT EXISTS english_knowledge_cards (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    code       TEXT NOT NULL,
    title      TEXT NOT NULL,
    rule_md    TEXT NOT NULL,
    examples   TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_en_card ON english_knowledge_cards (user_id, code);

CREATE TABLE IF NOT EXISTS english_analysis_runs (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    message_id  TEXT NOT NULL,
    error_count INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_en_runs_user ON english_analysis_runs (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS english_error_patterns (
    user_id     INTEGER NOT NULL,
    code        TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    resolved_at TEXT,
    PRIMARY KEY (user_id, code)
);

CREATE TABLE IF NOT EXISTS english_vocab_items (
    id               TEXT PRIMARY KEY,
    user_id          INTEGER NOT NULL,
    surface          TEXT NOT NULL,
    lemma            TEXT NOT NULL,
    context_sentence TEXT NOT NULL DEFAULT '',
    message_id       TEXT,
    gloss_zh         TEXT,
    pos              TEXT,
    created_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_en_vocab ON english_vocab_items (user_id, lemma);
CREATE INDEX IF NOT EXISTS idx_en_vocab_user ON english_vocab_items (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS english_vocab_states (
    user_id        INTEGER NOT NULL,
    lemma          TEXT NOT NULL,
    stability      REAL NOT NULL DEFAULT 0,
    difficulty     REAL NOT NULL DEFAULT 5,
    reps           INTEGER NOT NULL DEFAULT 0,
    lapses         INTEGER NOT NULL DEFAULT 0,
    interval_days  INTEGER NOT NULL DEFAULT 0,
    last_review_at TEXT,
    next_review_at TEXT,
    PRIMARY KEY (user_id, lemma)
);
CREATE INDEX IF NOT EXISTS idx_en_vocab_due ON english_vocab_states (user_id, next_review_at);

CREATE TABLE IF NOT EXISTS english_scenario_memory (
    user_id     INTEGER NOT NULL,
    scenario_id TEXT NOT NULL,
    state       TEXT NOT NULL,
    revision    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS english_documents (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    scenario_id TEXT,
    filename    TEXT NOT NULL,
    mime        TEXT NOT NULL DEFAULT 'text/plain',
    chars       INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_en_doc_user ON english_documents (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS english_doc_chunks (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    content     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_en_chunk_doc ON english_doc_chunks (document_id, idx);

CREATE TABLE IF NOT EXISTS english_contracts (
    user_id              INTEGER PRIMARY KEY,
    must_use_words       TEXT NOT NULL DEFAULT '[]',
    grammar_focus        TEXT NOT NULL DEFAULT '[]',
    correction_intensity TEXT NOT NULL DEFAULT 'medium',
    difficulty_delta     INTEGER NOT NULL DEFAULT 0,
    max_reply_words      INTEGER NOT NULL DEFAULT 90,
    updated_at           TEXT NOT NULL
);
