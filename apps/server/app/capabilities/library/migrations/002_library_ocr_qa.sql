-- 教材库 v2：OCR 相关的解析元数据 + 问答会话表
--
-- 001 建的是「纯文本教材」的表；这一版补上扫描件需要的字段：
--   ocr_mode / ocr_engine / ocr_pages / ocr_confidence  —— OCR 过程与质量
--   parse_warning                                       —— 解析阶段的非致命告警（给人看的短句）
--   status 增加 partial 取值（文本可用但不完整，例如部分页 OCR 失败）
--
-- 问答会话落库，便于回看历史与复用引用；thread.document_ids 存 JSON 数组。

ALTER TABLE documents ADD COLUMN ocr_mode TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE documents ADD COLUMN ocr_engine TEXT;
ALTER TABLE documents ADD COLUMN ocr_pages INTEGER NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN ocr_confidence REAL;
ALTER TABLE documents ADD COLUMN parse_warning TEXT;

CREATE TABLE IF NOT EXISTS qa_threads (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    title        TEXT NOT NULL DEFAULT '',
    document_ids TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qa_threads_user ON qa_threads (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS qa_messages (
    id             TEXT PRIMARY KEY,
    thread_id      TEXT NOT NULL,
    user_id        INTEGER NOT NULL,
    role           TEXT NOT NULL,
    content_md     TEXT NOT NULL DEFAULT '',
    citations_json TEXT NOT NULL DEFAULT '[]',
    meta_json      TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qa_messages_thread ON qa_messages (thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_qa_messages_user ON qa_messages (user_id);
