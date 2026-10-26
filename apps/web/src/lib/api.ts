export type SettingProp = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
};

export type CapabilityInfo = {
  id: string;
  name: string;
  description: string;
  icon: string;
  nav: { label: string; path: string; order: number } | null;
  version: string;
  status: "stable" | "beta" | "planned" | string;
  settings_schema: { type?: string; properties?: Record<string, SettingProp> };
  enabled: boolean;
  settings: Record<string, unknown>;
  has_tools: boolean;
};

export type Provider = {
  id: number;
  name: string;
  base_url: string;
  chat_model: string;
  embed_model: string | null;
  is_default: boolean;
  has_key: boolean;
  key_hint: string | null;
  created_at: string | null;
};

export type ProviderInput = {
  name: string;
  base_url: string;
  api_key?: string;
  chat_model: string;
  embed_model?: string | null;
};

export type TestResult = {
  ok: boolean;
  latency_ms: number;
  models: string[];
  models_error?: string | null;
  chat_ok?: boolean | null;
  chat_error?: string | null;
  error?: string | null;
};

export type Job = {
  id: string;
  type: string;
  title: string;
  status: "queued" | "running" | "done" | "error" | "cancelled" | string;
  progress: number;
  message: string | null;
  error: string | null;
  result: unknown;
  created_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
};

export type User = {
  id: number;
  username: string;
  display_name: string;
  role: "admin" | "user" | string;
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
};

export type AdminUser = User & { providers: number; jobs: number };

export type AuthConfig = {
  app: { name: string; version: string };
  allow_registration: boolean;
  has_users: boolean;
};

export type AppInfo = {
  app: { name: string; slug: string; version: string };
  user: { id: number; username: string; display_name: string; role: string };
  data_dir: string | null;
  web_dist_exists: boolean;
  providers: { total: number; with_key: number; default: string | null };
  capabilities: number;
  enabled_capabilities: number;
  tools: number;
  time: string;
};

export type EventItem = {
  id: number;
  kind: string;
  message: string;
  payload: string | null;
  created_at: string | null;
};

export type ToolInfo = {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  capability: string;
  scopes: string[];
  needs_confirm: boolean;
  capability_enabled: boolean;
};

export type Note = {
  id: number;
  title: string;
  content: string;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
};

/* ---------------- 群聊简报（wechat_digest） ---------------- */

export type DigestParamProperty = {
  type?: string;
  format?: string;
  title?: string;
  description?: string;
  default?: string | number | boolean | null;
  required?: boolean;
  enum?: string[];
};

export type DigestSource = {
  id: string;
  name: string;
  description: string;
  badge: string | null;
  available: boolean;
  hint: string | null;
  sample_params: Record<string, unknown> | null;
  params_schema: {
    type?: string;
    properties?: Record<string, DigestParamProperty>;
  };
};

export type DigestStyle = {
  id: string;
  label: string;
  description: string;
};

export type DigestOptions = {
  sources: DigestSource[];
  styles: DigestStyle[];
  settings: {
    default_style?: string;
    max_chars?: number;
    history_limit?: number;
  };
};

export type DigestCreateInput = {
  source: string;
  params: Record<string, string>;
  style?: string;
  provider_id?: number | null;
};

export type DigestPreviewGroup = {
  name: string;
  before: number;
  after: number;
  dropped: number;
  drop_reasons?: Record<string, number>;
};

export type DigestSampleMessage = {
  time: string;
  sender: string;
  text: string;
};

export type DigestPreview = {
  ok: boolean;
  source: string;
  total_before: number;
  total_after: number;
  groups: DigestPreviewGroup[];
  sample: DigestSampleMessage[];
};

export type DigestSchedule = {
  title: string;
  datetime: string;
  note: string;
  done: boolean;
  source_sender: string;
};

export type DigestGroup = {
  name: string;
  message_count: number;
  one_line: string;
  items: string[];
  schedules: DigestSchedule[];
  structured_text: string;
};

export type DigestPayload = {
  version: number;
  source: string;
  group_name: string;
  style: string;
  provider: string;
  model: string;
  created_at: string;
  stats: { before: number; after: number; dropped: number; chunks: number };
  groups: DigestGroup[];
};

export type DigestStatus = "queued" | "running" | "done" | "error" | "cancelled";

export type DigestSummary = {
  id: number;
  title: string;
  group_name: string;
  source: string;
  style: string;
  status: DigestStatus | string;
  provider: string;
  model: string;
  message_count: number;
  kept_count: number;
  one_line: string;
  created_at: string;
};

export type DigestDetail = DigestSummary & {
  job_id: string | null;
  error: string | null;
  updated_at: string;
  result: DigestPayload | null;
};

export type DigestCreateResponse = {
  ok: boolean;
  job_id: string;
  digest: DigestSummary;
};

export type DigestExportFormat = "txt" | "json" | "md" | "ics";

/* ---------------- 情景英语（english） ---------------- */

export type EnglishScenario = {
  id: string;
  slug: string;
  title_zh: string;
  title_en: string;
  domain: string;
  cefr: string;
  topic_count?: number;
};

export type EnglishTopic = {
  id: string;
  title: string;
  beats: string[];
  target_tenses: string[];
  target_lexis: string[];
  difficulty: string;
  used_count: number;
};

export type EnglishPlan = {
  id: string;
  slug: string;
  title_zh: string;
  title_en: string;
  provider?: string;
  topics: EnglishTopic[];
};

export type EnglishScenarioDetail = EnglishScenario & {
  topics: EnglishTopic[];
};

export type EnglishConversationSummary = {
  id: string;
  created_at?: string | null;
  last_message_at?: string | null;
  topic_title?: string | null;
  turns?: number;
};

export type EnglishMessageRow = {
  id: string;
  role: "user" | "assistant" | string;
  content_md: string;
  created_at?: string | null;
  /** 后端补的纠错标注（刷新后仍能显示下划线） */
  errors?: EnglishGrammarError[] | null;
};

export type EnglishConversation = {
  id: string;
  scenario_id?: string;
  topic_id?: string | null;
  rolling_summary?: string | null;
  created_at?: string | null;
  last_message_at?: string | null;
  messages: EnglishMessageRow[];
};

export type EnglishGrammarError = {
  code: string;
  /** 出错的原文片段；后端没给 start/end 时前端按它在原文里定位 */
  span: string;
  correction: string;
  explain_zh: string;
  severity: "low" | "medium" | "high" | string;
  confidence?: number;
  start?: number;
  end?: number;
};

export type EnglishAnnotations = {
  messageId: string;
  errors: EnglishGrammarError[];
  provider?: string;
};

export type EnglishSource = { title: string; part: number; score: number };

export type EnglishChatMeta = {
  conversationId: string;
  topicId?: string;
  topicTitle: string;
  provider: string;
  ttftMs: number | null;
  latencyMs?: number;
  cefr?: string;
  vocabTargets?: string[];
  vocabHits?: string[];
  candidates?: string[];
  memoryRevision?: number;
  memoryFacts?: string[];
  sources?: EnglishSource[];
};

export type EnglishChatInput = {
  scenarioId: string;
  conversationId?: string;
  topicId?: string;
  message: string;
};

export type EnglishStreamError = { code?: string; message: string; retryable?: boolean };

export type EnglishStreamHandlers = {
  onDelta: (text: string) => void;
  onReplace?: (text: string) => void;
  onAnnotations?: (annotations: EnglishAnnotations) => void;
  onMeta?: (meta: EnglishChatMeta) => void;
  onDone?: (meta: EnglishChatMeta) => void;
  onError?: (error: EnglishStreamError) => void;
};

export type EnglishContract = {
  must_use_words: string[];
  grammar_focus: string[];
  correction_intensity: "light" | "medium" | "strict";
  difficulty_delta: number;
  max_reply_words: number;
};

export type EnglishContractSaveResult = {
  contract: EnglishContract;
  warnings: string[];
};

export type EnglishDocItem = {
  id: string;
  filename: string;
  chunk_count: number;
  created_at?: string | null;
  scenario?: string | null;
};

export type EnglishDocImportResult = { id: string; filename?: string; chunks: number };
export type EnglishDocUploadResult = { id?: string; filename?: string; chunks: number; chars: number; kind: string };

export type EnglishMemoryView = {
  setting?: string;
  established_facts?: string[];
  open_threads?: string[];
  beats_done?: string[];
  revision?: number;
  counts: { facts: number; threads: number; beats: number };
};

export type EnglishErrorPattern = {
  code: string;
  label: string;
  occurrences: number;
  recent7: number;
  prev7: number;
  trend: "up" | "down" | "flat" | "new";
  improved: boolean;
};

export type EnglishErrorProfile = {
  items: EnglishErrorPattern[];
  active: number;
  improved: number;
};

export type EnglishVocabItem = {
  lemma: string;
  surface: string;
  context: string;
  glossZh: string | null;
  pos: string | null;
  reps: number;
  intervalDays: number;
  nextReviewAt: string | null;
  mastery: number;
  due: boolean;
};

export type EnglishVocabList = { items: EnglishVocabItem[]; dueCount: number };

export type EnglishVocabSaveResult = {
  lemma: string;
  glossZh?: string | null;
  pos?: string | null;
  nextReviewAt?: string | null;
  intervalDays: number;
};

export type EnglishVocabReviewResult = {
  lemma: string;
  intervalDays: number;
  nextReviewAt?: string | null;
  mastery?: number;
};

export type EnglishKnowledgeCard = {
  code: string;
  label?: string;
  title: string;
  rule_md: string;
  examples: { wrong: string; right: string; note: string }[];
};

export type EnglishHealth = {
  ok: boolean;
  scenarios: number;
  provider: string;
  degraded: boolean;
  okCount: number;
  failCount: number;
  rates: Record<string, number>;
};

export type EnglishChainHealth = {
  name: string;
  ok: number;
  fail: number;
  rate: number;
  degraded: boolean;
};

export type EnglishStatsHealth = {
  degraded?: boolean;
  ok?: number;
  fail?: number;
  okCount?: number;
  failCount?: number;
  rates?: Record<string, number>;
  counters?: Record<string, number>;
  /** /stats 的 health 是 metrics.snapshot()，链路口径在 chains 里 */
  chains?: EnglishChainHealth[];
};

export type EnglishStats = {
  turns24h: number;
  ttftAvg: number;
  latencyP95: number;
  tokens24h: number;
  costYuan24h: number;
  quality: {
    measured: number;
    avgWords: number;
    pctEndsWithQuestion: number;
    flagged: number;
    topFlags: { flag: string; n: number }[];
  };
  budget: { used: number; limit: number; ratio: number; degrade: boolean };
  health?: EnglishStatsHealth;
};

export class ApiError extends Error {
  code: string;
  status: number;
  detail?: unknown;

  constructor(message: string, code = "error", status = 0, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    throw new ApiError(
      "无法连接到后端服务，请确认它正在运行（./scripts/start.sh）",
      "network_error",
      0,
      error,
    );
  }

  if (!response.ok) {
    let payload: { code?: string; message?: string; detail?: unknown } | null = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (response.status === 401 && !path.startsWith("/api/auth/login")) {
      window.dispatchEvent(new Event("tjh:unauthorized"));
    }
    throw new ApiError(
      payload?.message ?? `请求失败（HTTP ${response.status}）`,
      payload?.code ?? "http_error",
      response.status,
      payload?.detail,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/* ---------------- english：multipart 与 SSE 帮助函数 ---------------- */

async function requestMultipart<T>(path: string, form: FormData): Promise<T> {
  let response: Response;
  try {
    // 不要手动设置 Content-Type，交给浏览器带 boundary
    response = await fetch(path, { method: "POST", credentials: "same-origin", body: form });
  } catch (error) {
    throw new ApiError(
      "无法连接到后端服务，请确认它正在运行（./scripts/start.sh）",
      "network_error",
      0,
      error,
    );
  }
  if (!response.ok) {
    let payload: { code?: string; message?: string; detail?: unknown } | null = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (response.status === 401) window.dispatchEvent(new Event("tjh:unauthorized"));
    throw new ApiError(
      payload?.message ?? `请求失败（HTTP ${response.status}）`,
      payload?.code ?? "http_error",
      response.status,
      payload?.detail,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * 流式对话：fetch + ReadableStream，按 `\n\n` 切事件帧。
 * 不能对每个 chunk 直接 JSON.parse——弱网下一帧可能跨两个 chunk。
 */
export async function streamEnglishChat(
  input: EnglishChatInput,
  handlers: EnglishStreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/c/english/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(
      "无法连接到后端服务，请确认它正在运行（./scripts/start.sh）",
      "network_error",
      0,
      error,
    );
  }

  if (!response.ok || !response.body) {
    let payload: { code?: string; message?: string; detail?: unknown } | null = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (response.status === 401) window.dispatchEvent(new Event("tjh:unauthorized"));
    throw new ApiError(
      payload?.message ?? `请求失败（HTTP ${response.status}）`,
      payload?.code ?? "http_error",
      response.status,
      payload?.detail,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const dispatch = (raw: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of raw.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") dataLines.push(value);
    }
    if (!dataLines.length) return;

    let payload: unknown;
    try {
      payload = JSON.parse(dataLines.join("\n"));
    } catch {
      handlers.onError?.({ code: "BAD_FRAME", message: "流式响应解析失败" });
      return;
    }

    try {
      if (event === "delta") handlers.onDelta(String((payload as { text?: unknown }).text ?? ""));
      else if (event === "replace") handlers.onReplace?.(String((payload as { text?: unknown }).text ?? ""));
      else if (event === "annotations") handlers.onAnnotations?.(payload as EnglishAnnotations);
      else if (event === "meta") handlers.onMeta?.(payload as EnglishChatMeta);
      else if (event === "done") handlers.onDone?.(payload as EnglishChatMeta);
      else if (event === "error") handlers.onError?.(payload as EnglishStreamError);
    } catch (error) {
      handlers.onError?.({
        code: "HANDLER_ERROR",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // 兼容 \n\n 与 \r\n\r\n 两种分帧（sse-starlette 可能用 CRLF）
    for (;;) {
      const lf = buffer.indexOf("\n\n");
      const crlf = buffer.indexOf("\r\n\r\n");
      let index = -1;
      let length = 2;
      if (lf !== -1 && (crlf === -1 || lf < crlf)) {
        index = lf;
        length = 2;
      } else if (crlf !== -1) {
        index = crlf;
        length = 4;
      }
      if (index === -1) break;
      const raw = buffer.slice(0, index);
      buffer = buffer.slice(index + length);
      dispatch(raw);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) dispatch(buffer);
}

/* ---------------- 教材库（library） ---------------- */

export type LibraryWarning = {
  code: string;
  level: "info" | "warn" | "error";
  message: string;
  detail?: string;
};

export type LibraryCourse = {
  id: number;
  name: string;
  color: string;
  term: string;
  visibility: "private" | "shared" | string;
  document_count: number;
  is_owner: boolean;
  created_at: string | null;
};

export type LibraryDocument = {
  id: number;
  title: string;
  kind: string;
  filename: string | null;
  size: number;
  status: "queued" | "parsing" | "indexing" | "ready" | "partial" | "error" | string;
  progress: number;
  message: string | null;
  error: string | null;
  visibility: "private" | "shared" | string;
  course_id: number | null;
  page_count: number;
  char_count: number;
  chunk_count: number;
  ocr_mode: "off" | "auto" | "force" | string;
  ocr_engine: string | null;
  ocr_pages: number;
  ocr_confidence: number | null;
  parse_warning: string | null;
  warnings: LibraryWarning[];
  parse: { kind?: string; blocks?: number; pages?: number; chars?: number; chunks?: number };
  ocr: {
    engine?: string | null;
    used?: boolean;
    requested_pages?: number;
    returned_pages?: number;
    avg_confidence?: number | null;
    low_confidence_pages?: number[];
    failed_pages?: number[];
  };
  is_owner: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type LibraryChunk = {
  chunk_id: number;
  ord: number;
  text: string;
  heading_path: string;
  loc_label: string;
  loc_index: number;
  n_chars: number;
};

export type LibraryCitation = {
  index: number;
  chunk_id: number;
  document_id: number;
  document_title: string;
  loc_label: string;
  loc_index: number;
  heading_path: string;
  snippet: string;
  text: string;
  score: number;
  retriever: string;
};

export type LibraryQaMeta = {
  citation_ok: boolean;
  bad_markers: number[];
  retriever: string;
  degraded: boolean;
  notes: string[];
  cited: number;
  retrieved: number;
  empty?: boolean;
};

export type LibraryHealth = {
  ok: boolean;
  ocr: {
    available: boolean;
    preferred: string | null;
    vision: { supported: boolean; compiled: boolean };
    tesseract: { installed: boolean; languages: string[] };
    hint: string;
  };
  formats: string[];
  documents: { total: number; ready: number; partial: number; error: number };
  chunks: number;
  max_upload_mb: number;
};

export type LibraryQaHandlers = {
  onStatus?: (payload: { stage: string; message: string; retriever?: string }) => void;
  onDelta: (text: string) => void;
  onCitations?: (payload: { citations: LibraryCitation[]; unused: LibraryCitation[] }) => void;
  onDone?: (payload: {
    answer: string;
    citations: LibraryCitation[];
    unused: LibraryCitation[];
    meta: LibraryQaMeta;
  }) => void;
  onError?: (payload: { code?: string; message?: string }) => void;
};

export async function streamLibraryQa(
  input: { question: string; document_ids: number[]; thread_id?: string | null; limit?: number },
  handlers: LibraryQaHandlers,
  signal: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/c/library/qa", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError(
      "无法连接到后端服务，请确认它正在运行（./scripts/start.sh）",
      "network_error",
      0,
      error,
    );
  }

  if (!response.ok || !response.body) {
    let payload: { code?: string; message?: string; detail?: unknown } | null = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (response.status === 401) window.dispatchEvent(new Event("tjh:unauthorized"));
    throw new ApiError(
      payload?.message ?? `请求失败（HTTP ${response.status}）`,
      payload?.code ?? "http_error",
      response.status,
      payload?.detail,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const dispatch = (raw: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of raw.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") dataLines.push(value);
    }
    if (!dataLines.length) return;

    let payload: unknown;
    try {
      payload = JSON.parse(dataLines.join("\n"));
    } catch {
      handlers.onError?.({ code: "BAD_FRAME", message: "流式响应解析失败" });
      return;
    }

    try {
      if (event === "status") handlers.onStatus?.(payload as { stage: string; message: string });
      else if (event === "delta") handlers.onDelta(String((payload as { text?: unknown }).text ?? ""));
      else if (event === "citations")
        handlers.onCitations?.(payload as { citations: LibraryCitation[]; unused: LibraryCitation[] });
      else if (event === "done")
        handlers.onDone?.(
          payload as {
            answer: string;
            citations: LibraryCitation[];
            unused: LibraryCitation[];
            meta: LibraryQaMeta;
          },
        );
      else if (event === "error") handlers.onError?.(payload as { code?: string; message?: string });
    } catch (error) {
      handlers.onError?.({
        code: "HANDLER_ERROR",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index = buffer.indexOf("\n\n");
    while (index >= 0) {
      dispatch(buffer.slice(0, index));
      buffer = buffer.slice(index + 2);
      index = buffer.indexOf("\n\n");
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) dispatch(buffer);
}

/* ---------------- 用户画像 ---------------- */

export type UserProfile = {
  school: string;
  school_key: string;
  grade: string;
  department: string;
  major: string;
  class_name: string;
  interests: string[];
  goals: string[];
  onboarded: boolean;
  completeness: number;
  updated_at: string | null;
};

export type ProfileInput = {
  school?: string;
  grade?: string;
  department?: string;
  major?: string;
  class_name?: string;
  interests?: string[] | string;
  goals?: string[] | string;
  onboarded?: boolean;
};

/* ---------------- 校园雷达 ---------------- */

export type CampusItem = {
  id: number;
  title: string;
  url: string;
  category: string;
  category_label: string;
  published_at: string | null;
  deadline: string | null;
  audience: string;
  summary: string;
  reason: string;
  is_demo: boolean;
  source_id: string;
};

export type CampusSource = {
  id: string;
  name: string;
  url: string;
  kind: string;
  kind_label: string;
  enabled: boolean;
  last_status: string;
  last_error: string;
  last_run_at: string | null;
  next_run_at: string | null;
  item_count: number;
};

export type CampusRun = {
  id: number;
  source_id: string;
  source_name?: string | null;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  fetched: number;
  created: number;
  updated: number;
  skipped: number;
  error: string | null;
};

export type CampusConfig = {
  interval_minutes: number;
  max_detail_per_run: number;
  enabled: boolean;
  can_manage: boolean;
};

export type CampusFeed = {
  school: string;
  school_fallback: boolean;
  profile_completeness: number;
  total: number;
  demo_count: number;
  items: CampusItem[];
  sources: CampusSource[];
  runs: CampusRun[];
  config: CampusConfig;
};

export type CampusDigest = {
  total: number;
  counts: { value: string; label: string; count: number }[];
  upcoming: CampusItem[];
  profile_completeness: number;
  last_run: CampusRun | null;
};

export type CampusAsk = {
  answer: string;
  mode: "llm" | "rule" | "empty" | string;
  items: CampusItem[];
  note: string;
  school: string;
  profile_completeness: number;
};

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),

  auth: {
    config: () => request<AuthConfig>("/api/auth/config"),
    me: () => request<User>("/api/auth/me"),
    login: (username: string, password: string) =>
      request<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }),
    register: (username: string, password: string, display_name = "", profile?: ProfileInput) =>
      request<User>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password, display_name, ...(profile ?? {}) }),
      }),
    logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    changePassword: (current_password: string, new_password: string) =>
      request<{ ok: boolean }>("/api/auth/password", {
        method: "PUT",
        body: JSON.stringify({ current_password, new_password }),
      }),
  },

  admin: {
    users: () => request<AdminUser[]>("/api/admin/users"),
    createUser: (input: {
      username: string;
      password: string;
      display_name?: string;
      role?: string;
    }) => request<User>("/api/admin/users", { method: "POST", body: JSON.stringify(input) }),
    updateUser: (
      id: number,
      patch: { display_name?: string; role?: string; is_active?: boolean },
    ) => request<User>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    resetPassword: (id: number, password: string) =>
      request<{ ok: boolean }>(`/api/admin/users/${id}/password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      }),
    removeUser: (id: number) =>
      request<{ ok: boolean }>(`/api/admin/users/${id}`, { method: "DELETE" }),
    setRegistration: (allow: boolean) =>
      request<{ ok: boolean; allow_registration: boolean }>("/api/admin/registration", {
        method: "PUT",
        body: JSON.stringify({ allow }),
      }),
  },
  info: () => request<AppInfo>("/api/info"),
  events: (limit = 12) => request<EventItem[]>(`/api/events?limit=${limit}`),
  tools: () => request<ToolInfo[]>("/api/tools"),

  capabilities: {
    list: () => request<CapabilityInfo[]>("/api/capabilities"),
    update: (id: string, body: { enabled?: boolean; settings?: Record<string, unknown> }) =>
      request<{ ok: boolean }>(`/api/capabilities/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  },

  providers: {
    list: () => request<Provider[]>("/api/providers"),
    create: (input: ProviderInput) =>
      request<Provider>("/api/providers", { method: "POST", body: JSON.stringify(input) }),
    update: (id: number, input: Partial<ProviderInput>) =>
      request<Provider>(`/api/providers/${id}`, { method: "PUT", body: JSON.stringify(input) }),
    remove: (id: number) => request<{ ok: boolean }>(`/api/providers/${id}`, { method: "DELETE" }),
    setDefault: (id: number) =>
      request<{ ok: boolean }>(`/api/providers/${id}/default`, { method: "POST" }),
    test: (id: number) => request<TestResult>(`/api/providers/${id}/test`, { method: "POST" }),
    models: (id: number) => request<{ models: string[] }>(`/api/providers/${id}/models`),
  },

  jobs: {
    list: () => request<Job[]>("/api/jobs"),
    get: (id: string) => request<Job>(`/api/jobs/${id}`),
    cancel: (id: string) => request<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
    streamUrl: "/api/jobs/stream/events",
  },

  settings: {
    get: () => request<Record<string, unknown>>("/api/settings"),
    update: (patch: Record<string, unknown>) =>
      request<{ ok: boolean }>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),
  },

  notes: {
    list: (q = "") =>
      request<Note[]>(`/api/c/notes/items${q ? `?q=${encodeURIComponent(q)}` : ""}`),
    create: (input: { title?: string; content: string; tags?: string }) =>
      request<Note>("/api/c/notes/items", { method: "POST", body: JSON.stringify(input) }),
    remove: (id: number) =>
      request<{ ok: boolean }>(`/api/c/notes/items/${id}`, { method: "DELETE" }),
  },

  digest: {
    options: () => request<DigestOptions>("/api/c/wechat_digest/options"),
    preview: (input: DigestCreateInput) =>
      request<DigestPreview>("/api/c/wechat_digest/preview", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    create: (input: DigestCreateInput) =>
      request<DigestCreateResponse>("/api/c/wechat_digest/digests", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    list: (limit = 20, q = "") =>
      request<DigestSummary[]>(
        `/api/c/wechat_digest/digests?limit=${limit}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
      ),
    get: (id: number) => request<DigestDetail>(`/api/c/wechat_digest/digests/${id}`),
    remove: (id: number) =>
      request<{ ok: boolean }>(`/api/c/wechat_digest/digests/${id}`, { method: "DELETE" }),
    exportUrl: (id: number, format: DigestExportFormat) =>
      `/api/c/wechat_digest/digests/${id}/export?format=${format}`,
  },

  english: {
    health: () => request<EnglishHealth>("/api/c/english/health"),

    scenarios: {
      list: () =>
        request<{ items: EnglishScenario[] }>("/api/c/english/scenarios").then((data) => data.items),
      create: (input: { domain: string; cefr: string }) =>
        request<EnglishPlan>("/api/c/english/scenarios", {
          method: "POST",
          body: JSON.stringify(input),
        }),
      get: (id: string) =>
        request<EnglishScenarioDetail>(`/api/c/english/scenarios/${encodeURIComponent(id)}`),
      conversations: (id: string) =>
        request<{ items: EnglishConversationSummary[] }>(
          `/api/c/english/scenarios/${encodeURIComponent(id)}/conversations`,
        ).then((data) => data.items),
    },

    conversation: {
      get: (id: string) =>
        request<EnglishConversation>(`/api/c/english/conversations/${encodeURIComponent(id)}`),
    },

    knowledge: (code: string) =>
      request<EnglishKnowledgeCard>(`/api/c/english/knowledge/${encodeURIComponent(code)}`),

    errors: () => request<EnglishErrorProfile>("/api/c/english/errors"),

    memory: (scenarioId: string) =>
      request<EnglishMemoryView>(`/api/c/english/memory/${encodeURIComponent(scenarioId)}`),

    vocab: {
      list: () => request<EnglishVocabList>("/api/c/english/vocab"),
      save: (input: { surface: string; context?: string; messageId?: string }) =>
        request<EnglishVocabSaveResult>("/api/c/english/vocab", {
          method: "POST",
          body: JSON.stringify(input),
        }),
      review: (input: { lemma: string; rating: number }) =>
        request<EnglishVocabReviewResult>("/api/c/english/vocab/review", {
          method: "POST",
          body: JSON.stringify(input),
        }),
    },

    documents: {
      list: () =>
        request<{ items: EnglishDocItem[] }>("/api/c/english/documents").then((data) => data.items),
      importText: (input: { filename: string; content: string; scenarioId?: string }) =>
        request<EnglishDocImportResult>("/api/c/english/documents", {
          method: "POST",
          body: JSON.stringify(input),
        }),
      upload: (file: File, scenarioId?: string) => {
        const form = new FormData();
        form.append("file", file);
        const query = scenarioId ? `?scenarioId=${encodeURIComponent(scenarioId)}` : "";
        return requestMultipart<EnglishDocUploadResult>(
          `/api/c/english/documents/upload${query}`,
          form,
        );
      },
      remove: (id: string) =>
        request<{ ok: boolean }>(`/api/c/english/documents/${encodeURIComponent(id)}`, {
          method: "DELETE",
        }),
    },

    contract: {
      /** 后端 GET 可能直接返 contract，也可能包一层 {contract}，页面里做归一化 */
      get: () =>
        request<EnglishContract | { contract: EnglishContract }>("/api/c/english/contract"),
      save: (contract: Partial<EnglishContract>) =>
        request<EnglishContractSaveResult>("/api/c/english/contract", {
          method: "PUT",
          body: JSON.stringify(contract),
        }),
    },

    stats: () => request<EnglishStats>("/api/c/english/stats"),

    chatStream: (input: EnglishChatInput, handlers: EnglishStreamHandlers, signal: AbortSignal) =>
      streamEnglishChat(input, handlers, signal),
  },

  library: {
    health: () => request<LibraryHealth>("/api/c/library/health"),

    courses: {
      list: () => request<LibraryCourse[]>("/api/c/library/courses"),
      create: (input: { name: string; color?: string; term?: string; visibility?: string }) =>
        request<LibraryCourse>("/api/c/library/courses", {
          method: "POST",
          body: JSON.stringify(input),
        }),
      update: (
        id: number,
        input: { name?: string; color?: string; term?: string; visibility?: string },
      ) =>
        request<LibraryCourse>(`/api/c/library/courses/${id}`, {
          method: "PATCH",
          body: JSON.stringify(input),
        }),
      remove: (id: number) =>
        request<{ ok: boolean }>(`/api/c/library/courses/${id}`, { method: "DELETE" }),
    },

    documents: {
      list: (params?: { course?: number | null; status?: string; q?: string }) => {
        const search = new URLSearchParams();
        if (params?.course != null) search.set("course", String(params.course));
        if (params?.status) search.set("status", params.status);
        if (params?.q) search.set("q", params.q);
        const query = search.toString();
        return request<LibraryDocument[]>(
          `/api/c/library/documents${query ? `?${query}` : ""}`,
        );
      },
      get: (id: number) => request<LibraryDocument>(`/api/c/library/documents/${id}`),
      chunks: (id: number, params?: { offset?: number; limit?: number; q?: string }) => {
        const search = new URLSearchParams();
        if (params?.offset) search.set("offset", String(params.offset));
        if (params?.limit) search.set("limit", String(params.limit));
        if (params?.q) search.set("q", params.q);
        const query = search.toString();
        return request<{ total: number; items: LibraryChunk[]; mode: string; note?: string }>(
          `/api/c/library/documents/${id}/chunks${query ? `?${query}` : ""}`,
        );
      },
      upload: (
        file: File,
        options: { course_id?: number | null; visibility?: string; ocr_mode?: string; title?: string },
      ) => {
        const form = new FormData();
        form.append("file", file);
        if (options.course_id != null) form.append("course_id", String(options.course_id));
        form.append("visibility", options.visibility ?? "private");
        form.append("ocr_mode", options.ocr_mode ?? "auto");
        if (options.title) form.append("title", options.title);
        return requestMultipart<{ document: LibraryDocument; job_id: string }>(
          "/api/c/library/documents/upload",
          form,
        );
      },
      update: (
        id: number,
        input: { title?: string; course_id?: number; visibility?: string; ocr_mode?: string },
      ) =>
        request<LibraryDocument>(`/api/c/library/documents/${id}`, {
          method: "PATCH",
          body: JSON.stringify(input),
        }),
      reparse: (id: number, ocr_mode?: string) => {
        const form = new FormData();
        if (ocr_mode) form.append("ocr_mode", ocr_mode);
        return requestMultipart<{ ok: boolean; job_id: string; ocr_mode: string }>(
          `/api/c/library/documents/${id}/reparse`,
          form,
        );
      },
      remove: (id: number) =>
        request<{ ok: boolean }>(`/api/c/library/documents/${id}`, { method: "DELETE" }),
    },

    qa: {
      stream: (
        input: { question: string; document_ids: number[]; thread_id?: string | null; limit?: number },
        handlers: LibraryQaHandlers,
        signal: AbortSignal,
      ) => streamLibraryQa(input, handlers, signal),
      threads: () =>
        request<{ id: string; title: string; document_ids: number[]; updated_at: string }[]>(
          "/api/c/library/qa/threads",
        ),
    },

    search: (q: string, documentIds: number[], limit = 8) => {
      const search = new URLSearchParams({ q, limit: String(limit) });
      if (documentIds.length) search.set("document_ids", documentIds.join(","));
      return request<{
        mode: string;
        terms: string[];
        degraded: boolean;
        note: string;
        hits: LibraryCitation[];
      }>(`/api/c/library/search?${search.toString()}`);
    },
  },

  profile: {
    get: () => request<UserProfile>("/api/profile"),
    update: (input: ProfileInput) =>
      request<UserProfile>("/api/profile", { method: "PUT", body: JSON.stringify(input) }),
  },

  campus: {
    health: () =>
      request<{
        school: string;
        school_key: string;
        items: number;
        sources: CampusSource[];
        config: CampusConfig;
        categories: { value: string; label: string }[];
      }>("/api/c/campus/health"),

    feed: (params: { category?: string; days?: number; limit?: number; sort?: "match" | "new" } = {}) => {
      const search = new URLSearchParams({
        category: params.category ?? "all",
        days: String(params.days ?? 90),
        limit: String(params.limit ?? 40),
        sort: params.sort ?? "match",
      });
      return request<CampusFeed>(`/api/c/campus/feed?${search.toString()}`);
    },

    digest: (days = 90) => request<CampusDigest>(`/api/c/campus/digest?days=${days}`),

    ask: (question: string, limit = 10) =>
      request<CampusAsk>("/api/c/campus/ask", {
        method: "POST",
        body: JSON.stringify({ question, limit }),
      }),

    crawl: (sourceId?: string) =>
      request<{ results: CampusRun[]; created: number; failed: number; message: string }>(
        "/api/c/campus/crawl",
        { method: "POST", body: JSON.stringify(sourceId ? { source_id: sourceId } : {}) },
      ),

    updateConfig: (patch: {
      interval_minutes?: number;
      max_detail_per_run?: number;
      enabled?: boolean;
    }) =>
      request<CampusConfig>("/api/c/campus/config", {
        method: "PUT",
        body: JSON.stringify(patch),
      }),

    toggleSource: (id: string, enabled: boolean) =>
      request<CampusSource>(`/api/c/campus/sources/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),

    seedDemo: () =>
      request<{ created: number; skipped: number; total: number; message: string }>(
        "/api/c/campus/seed-demo",
        { method: "POST" },
      ),

    clearDemo: () =>
      request<{ removed: number; message: string }>("/api/c/campus/seed-demo", {
        method: "DELETE",
      }),
  },
};
