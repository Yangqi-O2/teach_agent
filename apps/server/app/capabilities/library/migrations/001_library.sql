-- 教材库：课程 / 文档 / 分块 + FTS5 全文索引（jieba 预切词）
-- 双池：visibility = private | shared；user_id = owner

CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL DEFAULT 0,
    visibility  TEXT NOT NULL DEFAULT 'private',
    name        TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '#14687b',
    term        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_courses_user ON courses (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_courses_visibility ON courses (visibility);

CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL DEFAULT 0,
    visibility      TEXT NOT NULL DEFAULT 'private',
    course_id       INTEGER,
    title           TEXT NOT NULL DEFAULT '',
    kind            TEXT NOT NULL DEFAULT '',
    filename        TEXT,
    size            INTEGER NOT NULL DEFAULT 0,
    sha256          TEXT,
    status          TEXT NOT NULL DEFAULT 'queued',
    progress        INTEGER NOT NULL DEFAULT 0,
    message         TEXT,
    error           TEXT,
    page_count      INTEGER NOT NULL DEFAULT 0,
    char_count      INTEGER NOT NULL DEFAULT 0,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    embedding_model TEXT,
    meta_json       TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_user ON documents (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_visibility ON documents (visibility);
CREATE INDEX IF NOT EXISTS idx_documents_course ON documents (course_id);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents (sha256);

CREATE TABLE IF NOT EXISTS chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL DEFAULT 0,
    document_id  INTEGER NOT NULL,
    ord          INTEGER NOT NULL DEFAULT 0,
    text         TEXT NOT NULL DEFAULT '',
    heading_path TEXT NOT NULL DEFAULT '',
    loc_label    TEXT NOT NULL DEFAULT '',
    loc_index    INTEGER NOT NULL DEFAULT 0,
    n_chars      INTEGER NOT NULL DEFAULT 0,
    embedded     INTEGER NOT NULL DEFAULT 0,
    embedding    BLOB
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks (document_id, ord);
CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks (user_id);

-- FTS5：rowid 与 chunks.id 对齐；text_seg / heading_seg 为 jieba 切词结果
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text_seg,
    heading_seg,
    tokenize = 'unicode61 remove_diacritics 2'
);
