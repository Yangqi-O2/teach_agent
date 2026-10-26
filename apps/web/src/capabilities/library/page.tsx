import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { Modal } from "../../components/ui/overlay";
import {
  Badge,
  Button,
  Dot,
  EmptyState,
  Field,
  Input,
  Progress,
  SectionHeading,
  Segmented,
  Switch,
  Textarea,
} from "../../components/ui/primitives";
import {
  ApiError,
  api,
  type LibraryChunk,
  type LibraryCitation,
  type LibraryCourse,
  type LibraryDocument,
  type LibraryHealth,
  type LibraryQaMeta,
} from "../../lib/api";
import { cn } from "../../lib/utils";
import { useApp } from "../../store/app";

const STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  parsing: "解析中",
  indexing: "建索引",
  ready: "可问答",
  partial: "可用·有告警",
  error: "解析失败",
};

const STATUS_TONE: Record<string, "jade" | "amber" | "danger" | "neutral" | "brand"> = {
  queued: "neutral",
  parsing: "brand",
  indexing: "brand",
  ready: "jade",
  partial: "amber",
  error: "danger",
};

const KIND_LABEL: Record<string, string> = {
  pdf: "PDF",
  epub: "EPUB",
  docx: "DOCX",
  pptx: "PPTX",
  txt: "TXT",
  md: "Markdown",
  html: "HTML",
  image: "图片",
};

type QaTurn = {
  id: number;
  question: string;
  answer: string;
  citations: LibraryCitation[];
  unused: LibraryCitation[];
  meta: LibraryQaMeta | null;
  error: string | null;
  pending: boolean;
};

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function LibraryPage() {
  const toast = useApp((s) => s.toast);

  const [health, setHealth] = useState<LibraryHealth | null>(null);
  const [courses, setCourses] = useState<LibraryCourse[]>([]);
  const [documents, setDocuments] = useState<LibraryDocument[]>([]);
  const [loading, setLoading] = useState(true);

  const [courseFilter, setCourseFilter] = useState<number | "all" | "none">("all");
  const [keyword, setKeyword] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<LibraryDocument | null>(null);
  const [tab, setTab] = useState<"qa" | "content">("qa");

  const [uploadOpen, setUploadOpen] = useState(false);
  const [courseOpen, setCourseOpen] = useState(false);

  const [turns, setTurns] = useState<QaTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [stage, setStage] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const turnSeq = useRef(0);

  const [chunks, setChunks] = useState<LibraryChunk[]>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [chunkQuery, setChunkQuery] = useState("");

  const loadBase = useCallback(async () => {
    try {
      const [healthData, courseList] = await Promise.all([
        api.library.health(),
        api.library.courses.list(),
      ]);
      setHealth(healthData);
      setCourses(courseList);
    } catch (error) {
      if (error instanceof ApiError) toast({ title: "教材库加载失败", description: error.message, tone: "error" });
    }
  }, [toast]);

  const loadDocuments = useCallback(async () => {
    try {
      const params: { course?: number | null; q?: string } = {};
      if (typeof courseFilter === "number") params.course = courseFilter;
      if (keyword.trim()) params.q = keyword.trim();
      const list = await api.library.documents.list(params);
      const filtered =
        courseFilter === "none" ? list.filter((item) => item.course_id == null) : list;
      setDocuments(filtered);
      setSelectedId((current) => {
        if (current && filtered.some((item) => item.id === current)) return current;
        return filtered[0]?.id ?? null;
      });
    } catch (error) {
      if (error instanceof ApiError) toast({ title: "教材列表加载失败", description: error.message, tone: "error" });
    }
  }, [courseFilter, keyword, toast]);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      await loadBase();
      setLoading(false);
    })();
  }, [loadBase]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // 有文档在解析时轮询刷新
  const busy = documents.some((doc) => ["queued", "parsing", "indexing"].includes(doc.status));
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      void loadDocuments();
      void loadBase();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [busy, loadDocuments, loadBase]);

  const loadDetail = useCallback(
    async (id: number) => {
      try {
        const doc = await api.library.documents.get(id);
        setDetail(doc);
      } catch (error) {
        if (error instanceof ApiError) toast({ title: "读取教材失败", description: error.message, tone: "error" });
      }
    },
    [toast],
  );

  useEffect(() => {
    setTurns([]);
    setChunks([]);
    setChunkQuery("");
    if (selectedId) void loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (!detail || detail.status === "error") return;
    void api.library.documents
      .chunks(detail.id, { limit: 12 })
      .then((data) => {
        setChunks(data.items);
        setChunkTotal(data.total);
      })
      .catch(() => undefined);
  }, [detail]);

  const selectedDoc = useMemo(
    () => documents.find((doc) => doc.id === selectedId) ?? detail,
    [documents, selectedId, detail],
  );

  const ask = useCallback(
    async (raw: string) => {
      const text = raw.trim();
      if (!text || !selectedId) return;
      if (streaming) return;

      turnSeq.current += 1;
      const id = turnSeq.current;
      setTurns((prev) => [
        ...prev,
        { id, question: text, answer: "", citations: [], unused: [], meta: null, error: null, pending: true },
      ]);
      setQuestion("");
      setStreaming(true);
      setStage("正在教材里查找相关段落");

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await api.library.qa.stream(
          { question: text, document_ids: [selectedId] },
          {
            onStatus: (payload) => setStage(payload.message),
            onDelta: (delta) =>
              setTurns((prev) =>
                prev.map((turn) => (turn.id === id ? { ...turn, answer: turn.answer + delta } : turn)),
              ),
            onCitations: (payload) =>
              setTurns((prev) =>
                prev.map((turn) =>
                  turn.id === id
                    ? { ...turn, citations: payload.citations, unused: payload.unused }
                    : turn,
                ),
              ),
            onDone: (payload) =>
              setTurns((prev) =>
                prev.map((turn) =>
                  turn.id === id
                    ? {
                        ...turn,
                        answer: payload.answer || turn.answer,
                        citations: payload.citations,
                        unused: payload.unused,
                        meta: payload.meta,
                        pending: false,
                      }
                    : turn,
                ),
              ),
            onError: (payload) =>
              setTurns((prev) =>
                prev.map((turn) =>
                  turn.id === id
                    ? { ...turn, error: payload.message ?? "生成失败", pending: false }
                    : turn,
                ),
              ),
          },
          controller.signal,
        );
      } catch (error) {
        const message =
          error instanceof Error && error.name === "AbortError"
            ? "已停止"
            : error instanceof ApiError
              ? error.message
              : String(error);
        setTurns((prev) =>
          prev.map((turn) => (turn.id === id ? { ...turn, error: message, pending: false } : turn)),
        );
      } finally {
        setStreaming(false);
        setStage("");
        abortRef.current = null;
      }
    },
    [selectedId, streaming],
  );

  const searchChunks = useCallback(async () => {
    if (!detail) return;
    const query = chunkQuery.trim();
    try {
      const data = await api.library.documents.chunks(detail.id, { limit: 12, q: query });
      setChunks(data.items);
      setChunkTotal(data.total);
    } catch (error) {
      if (error instanceof ApiError) toast({ title: "检索失败", description: error.message, tone: "error" });
    }
  }, [detail, chunkQuery, toast]);

  const removeDocument = useCallback(
    async (doc: LibraryDocument) => {
      if (!window.confirm(`删除《${doc.title}》？原文与索引都会移除。`)) return;
      try {
        await api.library.documents.remove(doc.id);
        toast({ title: "已删除", description: doc.title });
        await loadDocuments();
        await loadBase();
      } catch (error) {
        if (error instanceof ApiError) toast({ title: "删除失败", description: error.message, tone: "error" });
      }
    },
    [toast, loadDocuments, loadBase],
  );

  const reparse = useCallback(
    async (doc: LibraryDocument, ocrMode: string) => {
      try {
        await api.library.documents.reparse(doc.id, ocrMode);
        toast({ title: "已提交重新解析", description: `OCR 策略：${ocrMode}` });
        await loadDocuments();
      } catch (error) {
        if (error instanceof ApiError) toast({ title: "重新解析失败", description: error.message, tone: "error" });
      }
    },
    [toast, loadDocuments],
  );

  const ocrBlocked = health ? !health.ocr.available : false;

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="教材库"
        title="把教材变成可以提问的东西"
        description="上传后自动解析与索引；扫描版 PDF 会先 OCR 成可检索文本。提问时只会用到你选中的这本书，并逐条标出页码或章节。"
        actions={
          <>
            <Button variant="secondary" onClick={() => setCourseOpen(true)}>
              <Icon name="folder-open" className="h-4 w-4" />
              新建分类
            </Button>
            <Button variant="primary" onClick={() => setUploadOpen(true)}>
              <Icon name="upload" className="h-4 w-4" />
              上传教材
            </Button>
          </>
        }
      />

      {health && !health.ocr.available ? (
        <div className="mb-6 flex items-start gap-3 rounded-card border border-amber/30 bg-amber/8 px-4 py-3 text-[13px] leading-relaxed text-ink-soft">
          <Icon name="alert-circle" className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
          <div>
            <p className="font-medium text-ink">当前没有可用的 OCR 引擎</p>
            <p className="mt-0.5 text-ink-faint">{health.ocr.hint}</p>
            <p className="mt-1 text-ink-faint">有文本层的 PDF / EPUB / DOCX / TXT 不受影响，仍可正常解析与问答。</p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <div className="rounded-card border border-line bg-surface p-2">
            <CourseFilter
              courses={courses}
              value={courseFilter}
              onChange={setCourseFilter}
              total={documents.length}
            />
          </div>

          <Input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="按标题筛选…"
            className="bg-surface"
          />

          <div className="space-y-2">
            {loading ? (
              <p className="px-1 text-[13px] text-ink-faint">加载中…</p>
            ) : documents.length === 0 ? (
              <EmptyState
                icon="library"
                title="还没有教材"
                description="支持 PDF / EPUB / DOCX / PPTX / TXT / Markdown / 图片"
                action={
                  <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
                    上传第一本
                  </Button>
                }
              />
            ) : (
              documents.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => setSelectedId(doc.id)}
                  className={cn(
                    "w-full rounded-xl border px-3 py-2.5 text-left transition-colors",
                    doc.id === selectedId
                      ? "border-brand/40 bg-brand-soft/50"
                      : "border-line bg-surface hover:bg-surface-2",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="line-clamp-2 text-[13.5px] font-medium leading-snug text-ink">
                      {doc.title}
                    </span>
                    <Dot tone={STATUS_TONE[doc.status] ?? "neutral"} className="mt-1.5 shrink-0" />
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-faint">
                    <span>{KIND_LABEL[doc.kind] ?? doc.kind}</span>
                    <span>·</span>
                    <span>{doc.chunk_count} 段</span>
                    {doc.ocr_pages > 0 ? (
                      <>
                        <span>·</span>
                        <span>OCR {doc.ocr_pages} 页</span>
                      </>
                    ) : null}
                    {doc.visibility === "shared" ? (
                      <Badge tone="brand" className="ml-auto">
                        共享
                      </Badge>
                    ) : null}
                  </div>
                  {["queued", "parsing", "indexing"].includes(doc.status) ? (
                    <Progress value={doc.progress} className="mt-2" />
                  ) : null}
                </button>
              ))
            )}
          </div>
        </aside>

        <section className="min-w-0">
          {!selectedDoc ? (
            <EmptyState
              icon="book-open"
              title="选一本教材开始"
              description="左边点选教材后，这里会出现解析详情与问答框。"
            />
          ) : (
            <div className="space-y-4">
              <DocumentHeader
                doc={selectedDoc}
                onDelete={() => void removeDocument(selectedDoc)}
                onReparse={(mode) => void reparse(selectedDoc, mode)}
              />

              <Segmented
                value={tab}
                onChange={(next) => setTab(next)}
                options={[
                  { value: "qa", label: "教材问答" },
                  { value: "content", label: "解析内容" },
                ]}
              />

              {tab === "qa" ? (
                <div className="rounded-card border border-line bg-surface">
                  <div className="max-h-[52vh] space-y-4 overflow-y-auto px-5 py-4">
                    {turns.length === 0 ? (
                      <div className="py-6 text-center">
                        <Icon name="message-square" className="mx-auto h-6 w-6 text-ink-faint" />
                        <p className="mt-2 text-[13.5px] font-medium text-ink">
                          只基于《{selectedDoc.title}》回答
                        </p>
                        <p className="mx-auto mt-1 max-w-md text-[12.5px] leading-relaxed text-ink-faint">
                          教材里没写的内容会直接告诉你「没有提到」，不会用别处的知识补全。
                        </p>
                        <div className="mt-4 flex flex-wrap justify-center gap-2">
                          {suggestions(selectedDoc).map((item) => (
                            <button
                              key={item}
                              onClick={() => void ask(item)}
                              className="rounded-full border border-line px-3 py-1.5 text-[12.5px] text-ink-soft transition-colors hover:border-brand/40 hover:text-ink"
                            >
                              {item}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : (
                      turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
                    )}
                  </div>

                  <div className="border-t border-line px-4 py-3">
                    <div className="flex items-end gap-2">
                      <Textarea
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && !event.shiftKey) {
                            event.preventDefault();
                            void ask(question);
                          }
                        }}
                        placeholder={`就《${selectedDoc.title}》提问，Enter 发送、Shift+Enter 换行`}
                        className="min-h-11 py-2.5"
                        disabled={selectedDoc.status === "error"}
                      />
                      {streaming ? (
                        <Button variant="secondary" onClick={() => abortRef.current?.abort()}>
                          <Icon name="square" className="h-3.5 w-3.5" />
                          停止
                        </Button>
                      ) : (
                        <Button
                          variant="primary"
                          onClick={() => void ask(question)}
                          disabled={!question.trim() || selectedDoc.status === "error"}
                        >
                          <Icon name="send" className="h-4 w-4" />
                          提问
                        </Button>
                      )}
                    </div>
                    {streaming && stage ? (
                      <p className="mt-2 flex items-center gap-1.5 text-[12px] text-ink-faint">
                        <Icon name="loader-2" className="h-3.5 w-3.5 animate-spin" />
                        {stage}
                      </p>
                    ) : null}
                    {selectedDoc.status === "error" ? (
                      <p className="mt-2 text-[12px] text-danger">
                        这本教材解析失败，暂时无法提问：{selectedDoc.error}
                      </p>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="rounded-card border border-line bg-surface">
                  <div className="flex items-center gap-2 border-b border-line px-4 py-3">
                    <Input
                      value={chunkQuery}
                      onChange={(event) => setChunkQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void searchChunks();
                      }}
                      placeholder="在这本教材里检索段落…"
                      className="h-9"
                    />
                    <Button variant="secondary" size="sm" onClick={() => void searchChunks()}>
                      检索
                    </Button>
                    <span className="shrink-0 text-[12px] text-ink-faint">共 {chunkTotal} 段</span>
                  </div>
                  <div className="divide-y divide-line">
                    {chunks.length === 0 ? (
                      <p className="px-4 py-8 text-center text-[13px] text-ink-faint">
                        没有可展示的段落
                      </p>
                    ) : (
                      chunks.map((chunk) => <ChunkRow key={`${chunk.chunk_id}-${chunk.ord}`} chunk={chunk} />)
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      <UploadModal
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        courses={courses}
        defaultCourse={typeof courseFilter === "number" ? courseFilter : null}
        ocrAvailable={!ocrBlocked}
        onUploaded={async () => {
          setUploadOpen(false);
          await loadDocuments();
          await loadBase();
        }}
      />

      <CourseModal
        open={courseOpen}
        onOpenChange={setCourseOpen}
        onCreated={async () => {
          setCourseOpen(false);
          await loadBase();
        }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ 子组件 */

function suggestions(doc: LibraryDocument): string[] {
  if (doc.kind === "pdf" && doc.ocr_engine) {
    return ["这本书的核心概念是什么？", "帮我梳理一下主要章节结构", "第 1 页讲了什么？"];
  }
  return ["这本书的核心概念是什么？", "帮我梳理一下主要章节结构", "有哪些容易混淆的地方？"];
}

function CourseFilter({
  courses,
  value,
  onChange,
  total,
}: {
  courses: LibraryCourse[];
  value: number | "all" | "none";
  onChange: (next: number | "all" | "none") => void;
  total: number;
}) {
  const item = (key: number | "all" | "none", label: string, count?: number, color?: string) => (
    <button
      key={String(key)}
      onClick={() => onChange(key)}
      className={cn(
        "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors",
        value === key ? "bg-surface-2 font-medium text-ink" : "text-ink-soft hover:bg-surface-2",
      )}
    >
      {color ? (
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      ) : (
        <Icon name={key === "all" ? "library" : "folder-open"} className="h-3.5 w-3.5 shrink-0" />
      )}
      <span className="truncate">{label}</span>
      {count != null ? <span className="ml-auto text-[11px] text-ink-faint">{count}</span> : null}
    </button>
  );

  return (
    <div className="space-y-0.5">
      {item("all", "全部教材", total)}
      {courses.map((course) =>
        item(course.id, course.name, course.document_count, course.color),
      )}
      {item("none", "未分类")}
    </div>
  );
}

function DocumentHeader({
  doc,
  onDelete,
  onReparse,
}: {
  doc: LibraryDocument;
  onDelete: () => void;
  onReparse: (mode: string) => void;
}) {
  const warnings = doc.warnings.filter((item) => item.level !== "info");
  const infos = doc.warnings.filter((item) => item.level === "info");
  return (
    <div className="rounded-card border border-line bg-surface px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-display text-[19px] font-semibold text-ink">{doc.title}</h2>
            <Badge tone="neutral">{KIND_LABEL[doc.kind] ?? doc.kind}</Badge>
            <Badge tone={STATUS_TONE[doc.status] ?? "neutral"}>
              {STATUS_LABEL[doc.status] ?? doc.status}
            </Badge>
            {doc.visibility === "shared" ? <Badge tone="brand">全站可见</Badge> : null}
          </div>
          <p className="mt-1.5 text-[12.5px] text-ink-faint">
            {formatSize(doc.size)} · {doc.page_count || "—"} 页/章 · {doc.char_count} 字 ·{" "}
            {doc.chunk_count} 段
            {doc.ocr_engine ? ` · OCR: ${doc.ocr_engine}` : ""}
            {doc.ocr_confidence != null ? `（置信度 ${(doc.ocr_confidence * 100).toFixed(0)}%）` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => onReparse(doc.ocr_mode || "auto")}>
            <Icon name="refresh-cw" className="h-3.5 w-3.5" />
            重新解析
          </Button>
          {doc.ocr_mode !== "force" ? (
            <Button variant="ghost" size="sm" onClick={() => onReparse("force")}>
              强制 OCR
            </Button>
          ) : null}
          {doc.is_owner ? (
            <Button variant="ghost" size="sm" onClick={onDelete}>
              <Icon name="trash-2" className="h-3.5 w-3.5" />
            </Button>
          ) : null}
        </div>
      </div>

      {["queued", "parsing", "indexing"].includes(doc.status) ? (
        <div className="mt-3">
          <Progress value={doc.progress} />
          <p className="mt-1.5 text-[12px] text-ink-faint">{doc.message ?? "处理中…"}</p>
        </div>
      ) : null}

      {warnings.length > 0 ? (
        <div className="mt-3 space-y-1.5 rounded-xl border border-amber/25 bg-amber/8 px-3 py-2.5">
          {warnings.map((item) => (
            <p key={item.code} className="flex items-start gap-2 text-[12.5px] leading-relaxed text-ink-soft">
              <Icon name="alert-circle" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" />
              <span>
                {item.message}
                {item.detail ? <span className="text-ink-faint">（{item.detail}）</span> : null}
              </span>
            </p>
          ))}
        </div>
      ) : null}

      {infos.length > 0 ? (
        <p className="mt-2 text-[12px] text-ink-faint">
          {infos.map((item) => item.message).join(" · ")}
        </p>
      ) : null}

      {doc.status === "error" && doc.error ? (
        <p className="mt-3 rounded-xl border border-danger/25 bg-danger/8 px-3 py-2 text-[12.5px] leading-relaxed text-danger">
          {doc.error}
        </p>
      ) : null}
    </div>
  );
}

function TurnView({ turn }: { turn: QaTurn }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  return (
    <div className="space-y-2">
      <p className="w-fit max-w-full rounded-2xl rounded-br-sm bg-brand-soft px-3.5 py-2 text-[13.5px] leading-relaxed text-ink">
        {turn.question}
      </p>
      <div className="rounded-2xl rounded-bl-sm bg-surface-2 px-3.5 py-3">
        {turn.answer ? (
          <div className="whitespace-pre-wrap text-[13.5px] leading-[1.75] text-ink">{turn.answer}</div>
        ) : turn.pending ? (
          <p className="flex items-center gap-2 text-[12.5px] text-ink-faint">
            <Icon name="loader-2" className="h-3.5 w-3.5 animate-spin" />
            正在生成…
          </p>
        ) : null}

        {turn.error ? <p className="mt-2 text-[12.5px] text-danger">{turn.error}</p> : null}

        {turn.citations.length > 0 ? (
          <div className="mt-3 space-y-1.5 border-t border-line pt-2.5">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ink-faint">出处</p>
            {turn.citations.map((cite) => (
              <button
                key={`${cite.index}-${cite.chunk_id}`}
                onClick={() => setOpenIndex(openIndex === cite.index ? null : cite.index)}
                className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface"
              >
                <span className="mt-0.5 flex h-4 min-w-4 items-center justify-center rounded bg-brand/12 px-1 text-[10.5px] font-medium text-brand-strong">
                  {cite.index}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12.5px] text-ink-soft">
                    《{cite.document_title}》{cite.loc_label}
                    {cite.heading_path ? ` · ${cite.heading_path}` : ""}
                  </span>
                  {openIndex === cite.index ? (
                    <span className="mt-1.5 block whitespace-pre-wrap rounded-lg border border-line bg-surface px-2.5 py-2 text-[12.5px] leading-relaxed text-ink">
                      {cite.text}
                    </span>
                  ) : (
                    <span className="mt-0.5 line-clamp-1 block text-[11.5px] text-ink-faint">
                      {cite.snippet}
                    </span>
                  )}
                </span>
              </button>
            ))}
          </div>
        ) : null}

        {turn.meta && !turn.meta.citation_ok && turn.answer ? (
          <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-amber">
            <Icon name="alert-circle" className="mt-0.5 h-3 w-3 shrink-0" />
            这条回答没有标注出处，建议对照原文核对
          </p>
        ) : null}

        {turn.meta?.notes?.length ? (
          <p className="mt-1.5 text-[11.5px] text-ink-faint">{turn.meta.notes.join("；")}</p>
        ) : null}
      </div>
    </div>
  );
}

function ChunkRow({ chunk }: { chunk: LibraryChunk }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium text-ink-soft">
          #{chunk.ord + 1}
          {chunk.loc_label ? ` · ${chunk.loc_label}` : ""}
          {chunk.heading_path ? ` · ${chunk.heading_path}` : ""}
        </span>
        <button
          onClick={() => setOpen((prev) => !prev)}
          className="text-[11.5px] text-ink-faint transition-colors hover:text-ink"
        >
          {open ? "收起" : `${chunk.n_chars} 字`}
        </button>
      </div>
      <p
        className={cn(
          "mt-1 whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink-soft",
          open ? "" : "line-clamp-2",
        )}
      >
        {chunk.text}
      </p>
    </div>
  );
}

function UploadModal({
  open,
  onOpenChange,
  courses,
  defaultCourse,
  ocrAvailable,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  courses: LibraryCourse[];
  defaultCourse: number | null;
  ocrAvailable: boolean;
  onUploaded: () => void | Promise<void>;
}) {
  const toast = useApp((s) => s.toast);
  const [file, setFile] = useState<File | null>(null);
  const [courseId, setCourseId] = useState<number | null>(defaultCourse);
  const [shared, setShared] = useState(false);
  const [ocrMode, setOcrMode] = useState(ocrAvailable ? "auto" : "off");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setCourseId(defaultCourse);
      setOcrMode(ocrAvailable ? "auto" : "off");
    }
  }, [open, defaultCourse, ocrAvailable]);

  const submit = async () => {
    if (!file) {
      toast({ title: "先选一个文件", tone: "error" });
      return;
    }
    setBusy(true);
    try {
      await api.library.documents.upload(file, {
        course_id: courseId,
        visibility: shared ? "shared" : "private",
        ocr_mode: ocrMode,
      });
      toast({ title: "已开始解析", description: file.name });
      setFile(null);
      await onUploaded();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      toast({ title: "上传失败", description: message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="上传教材"
      description="PDF / EPUB / DOCX / PPTX / TXT / Markdown / HTML / 图片，单文件上限 60MB。"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            开始解析
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="文件" hint="扫描版 PDF 会自动走 OCR；纯图片也可以直接上传">
          <label
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-7 text-center transition-colors",
              file ? "border-brand/40 bg-brand-soft/40" : "border-line hover:border-brand/30",
            )}
          >
            <input
              type="file"
              className="hidden"
              accept=".pdf,.epub,.docx,.pptx,.txt,.md,.markdown,.html,.htm,.png,.jpg,.jpeg,.webp,.bmp"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <Icon name={file ? "file-text" : "upload"} className="h-5 w-5 text-brand" />
            <span className="text-[13px] font-medium text-ink">
              {file ? file.name : "点击选择文件"}
            </span>
            {file ? (
              <span className="text-[12px] text-ink-faint">{formatSize(file.size)}</span>
            ) : null}
          </label>
        </Field>

        <Field label="归入分类" hint="分类只是方便查找，不影响问答范围">
          <select
            value={courseId ?? ""}
            onChange={(event) =>
              setCourseId(event.target.value ? Number(event.target.value) : null)
            }
            className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-ink focus:border-brand/60 focus:outline-none"
          >
            <option value="">未分类</option>
            {courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="OCR 策略"
          hint={
            ocrAvailable
              ? "auto：只对没有文本层的页做 OCR；force：整本重跑（更慢但更保险）"
              : "当前没有可用 OCR 引擎，只能解析有文本层的文件"
          }
        >
          <Segmented
            value={ocrMode}
            onChange={setOcrMode}
            options={[
              { value: "auto", label: "自动" },
              { value: "force", label: "强制 OCR" },
              { value: "off", label: "关闭" },
            ]}
          />
        </Field>

        <label className="flex items-start justify-between gap-4 rounded-xl border border-line px-3.5 py-3">
          <span>
            <span className="block text-[13px] font-medium text-ink">公开给所有成员</span>
            <span className="mt-0.5 block text-[12px] leading-relaxed text-ink-faint">
              开启后其他成员可以阅读并基于它提问，但只有你能修改或删除。
            </span>
          </span>
          <Switch checked={shared} onCheckedChange={setShared} />
        </label>
      </div>
    </Modal>
  );
}

function CourseModal({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void | Promise<void>;
}) {
  const toast = useApp((s) => s.toast);
  const [name, setName] = useState("");
  const [term, setTerm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.library.courses.create({ name: name.trim(), term: term.trim() });
      setName("");
      setTerm("");
      await onCreated();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : String(error);
      toast({ title: "创建分类失败", description: message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="新建分类"
      description="按课程或学期归档教材，例如「弹性力学 · 2026 秋」。"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            创建
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="分类名称">
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：高等数学（上）" />
        </Field>
        <Field label="学期" hint="可留空">
          <Input value={term} onChange={(event) => setTerm(event.target.value)} placeholder="例如：2026 秋" />
        </Field>
      </div>
    </Modal>
  );
}
