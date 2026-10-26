import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { Badge, Button } from "../../components/ui/primitives";
import {
  ApiError,
  api,
  type EnglishChatMeta,
  type EnglishContract,
  type EnglishDocItem,
  type EnglishErrorProfile,
  type EnglishGrammarError,
  type EnglishHealth,
  type EnglishKnowledgeCard,
  type EnglishMemoryView,
  type EnglishScenario,
  type EnglishStats,
  type EnglishTopic,
  type EnglishVocabItem,
} from "../../lib/api";
import { useApp } from "../../store/app";

import { ChatComposer } from "./components/ChatComposer";
import { ChatThread } from "./components/ChatThread";
import { ContextRail } from "./components/ContextRail";
import { ContractDrawer } from "./components/ContractDrawer";
import { DocumentsDrawer } from "./components/DocumentsDrawer";
import { Drawer } from "./components/Drawer";
import { ErrorProfileDrawer } from "./components/ErrorProfileDrawer";
import { MemoryDrawer } from "./components/MemoryDrawer";
import { MemoryPanel } from "./components/MemoryPanel";
import type { ChatMessage } from "./components/MessageBubble";
import { ScenarioSidebar } from "./components/ScenarioSidebar";
import { StatsDrawer } from "./components/StatsDrawer";
import { VocabDrawer } from "./components/VocabDrawer";

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function localId(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

/** 顶栏上的纯图标操作按钮（移动端也放得下） */
function IconAction({
  icon,
  label,
  onClick,
  badge,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  badge?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="relative rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
    >
      <Icon name={icon} className="h-4 w-4" />
      {badge ? (
        <span className="absolute -right-1 -top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-danger px-1 text-[9px] font-medium text-canvas">
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </button>
  );
}

function isWrappedContract(value: EnglishContract | { contract: EnglishContract }): value is { contract: EnglishContract } {
  return Boolean((value as { contract?: EnglishContract }).contract);
}

export function EnglishPage() {
  const toast = useApp((s) => s.toast);

  /* 情景与对话 */
  const [scenarios, setScenarios] = useState<EnglishScenario[]>([]);
  const [scenariosLoading, setScenariosLoading] = useState(true);
  const [current, setCurrent] = useState<EnglishScenario | null>(null);
  const [topics, setTopics] = useState<EnglishTopic[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [topicTitle, setTopicTitle] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [ttft, setTtft] = useState<number | null>(null);
  const [provider, setProvider] = useState("");
  const [health, setHealth] = useState<EnglishHealth | null>(null);

  /* 新建情景 */
  const [domain, setDomain] = useState("一带一路");
  const [level, setLevel] = useState("B1");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  /* 纠错知识卡 */
  const [activeError, setActiveError] = useState<EnglishGrammarError | null>(null);
  const [knowledgeCard, setKnowledgeCard] = useState<EnglishKnowledgeCard | null>(null);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const knowledgeRequestRef = useRef(0);

  /* 生词本 */
  const [vocabOpen, setVocabOpen] = useState(false);
  const [vocabItems, setVocabItems] = useState<EnglishVocabItem[]>([]);
  const [dueCount, setDueCount] = useState(0);
  const [vocabLoading, setVocabLoading] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [savingWord, setSavingWord] = useState<string | null>(null);

  /* 情景记忆 */
  const [memory, setMemory] = useState<EnglishMemoryView | null>(null);
  const [memoryExpanded, setMemoryExpanded] = useState(false);
  const [memoryDrawerOpen, setMemoryDrawerOpen] = useState(false);

  /* 错误档案 */
  const [errorsOpen, setErrorsOpen] = useState(false);
  const [errorProfile, setErrorProfile] = useState<EnglishErrorProfile | null>(null);
  const [errorsLoading, setErrorsLoading] = useState(false);

  /* 资料库 */
  const [documentsOpen, setDocumentsOpen] = useState(false);
  const [documents, setDocuments] = useState<EnglishDocItem[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsImporting, setDocumentsImporting] = useState(false);

  /* 偏好契约 */
  const [contractOpen, setContractOpen] = useState(false);
  const [contract, setContract] = useState<EnglishContract | null>(null);
  const [contractLoading, setContractLoading] = useState(false);
  const [contractSaving, setContractSaving] = useState(false);
  const [contractWarnings, setContractWarnings] = useState<string[]>([]);

  /* 成本看板 */
  const [statsOpen, setStatsOpen] = useState(false);
  const [stats, setStats] = useState<EnglishStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  /* 移动端情景抽屉 */
  const [scenarioDrawerOpen, setScenarioDrawerOpen] = useState(false);

  const controllerRef = useRef<AbortController | null>(null);
  const streamBufferRef = useRef("");
  const streamTimerRef = useRef<number | null>(null);
  /** 当前情景 id：防止切情景后旧请求 / 旧流把状态写回来 */
  const currentScenarioIdRef = useRef<string | null>(null);
  const scenarioRequestRef = useRef(0);

  /* ---------------- 数据加载 ---------------- */

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.english.health());
    } catch {
      /* 健康接口失败不影响对话 */
    }
  }, []);

  const refreshVocab = useCallback(async () => {
    try {
      const data = await api.english.vocab.list();
      setVocabItems(data.items ?? []);
      setDueCount(data.dueCount ?? 0);
    } catch {
      /* 词库接口失败不影响对话 */
    }
  }, []);

  const refreshMemory = useCallback(async (scenarioId: string) => {
    try {
      setMemory(await api.english.memory(scenarioId));
    } catch {
      setMemory(null);
    }
  }, []);

  const restoreConversation = useCallback(async (scenarioId: string, requestId: number) => {
    setMessages([]);
    setConversationId(undefined);
    setTopicTitle("");
    try {
      const conversations = await api.english.scenarios.conversations(scenarioId);
      if (scenarioRequestRef.current !== requestId) return;
      if (!conversations.length) return;
      const latest = conversations[0];
      const conversation = await api.english.conversation.get(latest.id);
      if (scenarioRequestRef.current !== requestId) return;
      setConversationId(conversation.id);
      setTopicTitle(latest.topic_title ?? "");
      setMessages(
        (conversation.messages ?? []).map((row) => ({
          id: row.id,
          role: row.role === "user" ? "user" : "assistant",
          content: row.content_md ?? "",
          createdAt: row.created_at,
          errors: (row.errors ?? []) as EnglishGrammarError[],
        })),
      );
    } catch {
      /* 历史拉不到就从空白开始，不影响新对话 */
    }
  }, []);

  const openScenario = useCallback(
    async (scenario: EnglishScenario) => {
      const requestId = ++scenarioRequestRef.current;
      currentScenarioIdRef.current = scenario.id;
      setCurrent(scenario);
      setTopics([]);
      setMessages([]);
      setConversationId(undefined);
      setTopicTitle("");
      setTtft(null);
      setMemory(null);
      setActiveError(null);
      setKnowledgeCard(null);
      setScenarioDrawerOpen(false);
      setRestoring(true);
      try {
        const detail = await api.english.scenarios.get(scenario.id);
        if (scenarioRequestRef.current !== requestId) return;
        setTopics(detail.topics ?? []);
        await restoreConversation(scenario.id, requestId);
        if (scenarioRequestRef.current !== requestId) return;
        await refreshMemory(scenario.id);
      } catch (error) {
        if (scenarioRequestRef.current === requestId) {
          toast({ title: "读取情景失败", description: errorMessage(error), tone: "error" });
        }
      } finally {
        if (scenarioRequestRef.current === requestId) setRestoring(false);
      }
    },
    [restoreConversation, refreshMemory, toast],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setScenariosLoading(true);
      try {
        const list = await api.english.scenarios.list();
        if (cancelled) return;
        setScenarios(list);
        if (list[0]) await openScenario(list[0]);
        void refreshHealth();
        void refreshVocab();
      } catch (error) {
        if (!cancelled) {
          toast({ title: "读取情景列表失败", description: errorMessage(error), tone: "error" });
        }
      } finally {
        if (!cancelled) setScenariosLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [openScenario, refreshHealth, refreshVocab, toast]);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      if (streamTimerRef.current) window.clearInterval(streamTimerRef.current);
    };
  }, []);

  /* ---------------- 情景 ---------------- */

  const selectScenario = (scenario: EnglishScenario) => {
    if (busy) controllerRef.current?.abort();
    void openScenario(scenario);
  };

  const createScenario = async () => {
    const value = domain.trim();
    if (!value || creating) return;
    if (value.length < 2) {
      setCreateError("领域至少 2 个字符");
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const plan = await api.english.scenarios.create({ domain: value, cefr: level });
      const list = await api.english.scenarios.list();
      setScenarios(list);
      const target =
        list.find((item) => item.id === plan.id) ?? {
          id: plan.id,
          slug: plan.slug,
          title_zh: plan.title_zh,
          title_en: plan.title_en,
          domain: value,
          cefr: level,
        };
      toast({ title: "情景已生成", description: plan.title_zh, tone: "success" });
      await openScenario(target);
    } catch (error) {
      const message = errorMessage(error);
      setCreateError(message);
      toast({ title: "生成情景失败", description: message, tone: "error" });
    } finally {
      setCreating(false);
    }
  };

  const newChat = () => {
    controllerRef.current?.abort();
    setMessages([]);
    setConversationId(undefined);
    setTopicTitle("");
    setTtft(null);
    setActiveError(null);
    setKnowledgeCard(null);
  };

  /* ---------------- 纠错知识卡 ---------------- */

  const openError = async (error: EnglishGrammarError) => {
    setActiveError(error);
    setKnowledgeCard(null);
    setKnowledgeLoading(true);
    const requestId = ++knowledgeRequestRef.current;
    try {
      const card = await api.english.knowledge(error.code);
      if (knowledgeRequestRef.current === requestId) setKnowledgeCard(card);
    } catch {
      if (knowledgeRequestRef.current === requestId) setKnowledgeCard(null);
    } finally {
      if (knowledgeRequestRef.current === requestId) setKnowledgeLoading(false);
    }
  };

  /* ---------------- 生词 ---------------- */

  const saveWord = async (word: string, context: string) => {
    if (savingWord) return;
    setSavingWord(word);
    try {
      const result = await api.english.vocab.save({ surface: word, context });
      toast({
        title: `已存入生词本 · ${result.lemma}`,
        description: `${result.glossZh ?? "已记录释义"} · ${result.intervalDays} 天后复习`,
        tone: "success",
      });
      await refreshVocab();
    } catch (error) {
      toast({ title: "保存生词失败", description: errorMessage(error), tone: "error" });
    } finally {
      setSavingWord(null);
    }
  };

  const openVocab = async () => {
    setVocabOpen(true);
    setVocabLoading(true);
    try {
      await refreshVocab();
    } finally {
      setVocabLoading(false);
    }
  };

  const reviewWord = async (lemma: string, rating: number) => {
    if (reviewing) return;
    setReviewing(lemma);
    try {
      const result = await api.english.vocab.review({ lemma, rating });
      toast({ title: `${lemma} · ${result.intervalDays} 天后再见`, tone: "success" });
      await refreshVocab();
    } catch (error) {
      toast({ title: "复习失败", description: errorMessage(error), tone: "error" });
    } finally {
      setReviewing(null);
    }
  };

  /* ---------------- 错误档案 ---------------- */

  const refreshErrors = useCallback(async () => {
    setErrorsLoading(true);
    try {
      setErrorProfile(await api.english.errors());
    } catch (error) {
      toast({ title: "读取错误档案失败", description: errorMessage(error), tone: "error" });
    } finally {
      setErrorsLoading(false);
    }
  }, [toast]);

  const openErrors = () => {
    setErrorsOpen(true);
    void refreshErrors();
  };

  /* ---------------- 资料库 ---------------- */

  const refreshDocuments = useCallback(async () => {
    setDocumentsLoading(true);
    try {
      setDocuments(await api.english.documents.list());
    } catch (error) {
      toast({ title: "读取资料库失败", description: errorMessage(error), tone: "error" });
    } finally {
      setDocumentsLoading(false);
    }
  }, [toast]);

  const openDocuments = () => {
    setDocumentsOpen(true);
    void refreshDocuments();
  };

  const importDocumentText = async (filename: string, content: string): Promise<boolean> => {
    setDocumentsImporting(true);
    try {
      const result = await api.english.documents.importText({
        filename,
        content,
        scenarioId: current?.id,
      });
      toast({ title: `已导入 ${result.chunks} 段`, description: filename, tone: "success" });
      await refreshDocuments();
      return true;
    } catch (error) {
      toast({ title: "导入失败", description: errorMessage(error), tone: "error" });
      return false;
    } finally {
      setDocumentsImporting(false);
    }
  };

  const uploadDocument = async (file: File): Promise<boolean> => {
    setDocumentsImporting(true);
    try {
      const result = await api.english.documents.upload(file, current?.id);
      toast({
        title: `已解析 ${String(result.kind ?? "文件").toUpperCase()} · ${result.chunks} 段`,
        description: file.name,
        tone: "success",
      });
      await refreshDocuments();
      return true;
    } catch (error) {
      toast({ title: "文件解析失败", description: errorMessage(error), tone: "error" });
      return false;
    } finally {
      setDocumentsImporting(false);
    }
  };

  const deleteDocument = async (id: string) => {
    try {
      await api.english.documents.remove(id);
      toast({ title: "已删除资料", tone: "success" });
      await refreshDocuments();
    } catch (error) {
      toast({ title: "删除失败", description: errorMessage(error), tone: "error" });
    }
  };

  /* ---------------- 偏好契约 ---------------- */

  const refreshContract = useCallback(async () => {
    setContractLoading(true);
    try {
      const raw = await api.english.contract.get();
      setContract(isWrappedContract(raw) ? raw.contract : raw);
    } catch (error) {
      toast({ title: "读取偏好失败", description: errorMessage(error), tone: "error" });
    } finally {
      setContractLoading(false);
    }
  }, [toast]);

  const openContract = () => {
    setContractOpen(true);
    setContractWarnings([]);
    void refreshContract();
  };

  const saveContract = async (next: EnglishContract) => {
    setContractSaving(true);
    try {
      const result = await api.english.contract.save(next);
      setContract(result.contract ?? next);
      setContractWarnings(result.warnings ?? []);
      toast({
        title: result.warnings?.length ? result.warnings[0] : "偏好已保存，下一轮生效",
        tone: result.warnings?.length ? "default" : "success",
      });
    } catch (error) {
      toast({ title: "保存偏好失败", description: errorMessage(error), tone: "error" });
    } finally {
      setContractSaving(false);
    }
  };

  /* ---------------- 成本看板 ---------------- */

  const refreshStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      setStats(await api.english.stats());
    } catch (error) {
      toast({ title: "读取成本看板失败", description: errorMessage(error), tone: "error" });
    } finally {
      setStatsLoading(false);
    }
  }, [toast]);

  const openStats = () => {
    setStatsOpen(true);
    void refreshStats();
  };

  /* ---------------- 发送消息（SSE） ---------------- */

  const send = async () => {
    const text = draft.trim();
    if (!text || busy || !current) return;
    const scenarioId = current.id;
    setDraft("");
    setBusy(true);
    setActiveError(null);
    setKnowledgeCard(null);

    const userMessageId = localId("u");
    const botMessageId = localId("a");
    setMessages((previous) => [
      ...previous,
      { id: userMessageId, role: "user", content: text },
      { id: botMessageId, role: "assistant", content: "", streaming: true },
    ]);

    streamBufferRef.current = "";
    const updateBot = (patch: Partial<ChatMessage>) => {
      setMessages((previous) =>
        previous.map((message) => (message.id === botMessageId ? { ...message, ...patch } : message)),
      );
    };
    const flush = () => {
      const content = streamBufferRef.current;
      setMessages((previous) =>
        previous.map((message) =>
          message.id === botMessageId && message.content !== content ? { ...message, content } : message,
        ),
      );
    };

    const timer = window.setInterval(flush, 50);
    streamTimerRef.current = timer;
    const controller = new AbortController();
    controllerRef.current = controller;

    const applyMeta = (meta: EnglishChatMeta) => {
      setConversationId(meta.conversationId);
      setTopicTitle(meta.topicTitle ?? "");
      setTtft(typeof meta.ttftMs === "number" ? meta.ttftMs : null);
      if (meta.provider) setProvider(meta.provider);
      updateBot({ candidates: meta.candidates, sources: meta.sources });
    };

    try {
      await api.english.chatStream(
        { scenarioId, conversationId, message: text },
        {
          onDelta: (chunk) => {
            streamBufferRef.current += chunk;
          },
          onReplace: (replaced) => {
            // 质量门禁重写：整体覆盖已发正文
            streamBufferRef.current = replaced;
            updateBot({ content: replaced });
          },
          onAnnotations: (annotations) => {
            setMessages((previous) =>
              previous.map((message) =>
                message.id === userMessageId
                  ? { ...message, errors: annotations.errors ?? [] }
                  : message,
              ),
            );
          },
          onMeta: applyMeta,
          onDone: applyMeta,
          onError: (streamError) => {
            updateBot({ error: streamError.message || "生成中断" });
            if (streamError.code !== "ABORTED") {
              // 无供应商时后端的 ApiError 在 SSE 里会落成 UPSTREAM_ERROR，这里补一句可操作的提示
              const noModel = Boolean(health && health.provider === "unavailable");
              toast({
                title: streamError.code === "STALLED" ? "生成超时，已中断" : "生成出错",
                description:
                  streamError.code === "UPSTREAM_ERROR" && noModel
                    ? "还没配置可用的模型：请到「设置 → 模型接入」添加 OpenAI 兼容供应商后重试。"
                    : streamError.message || "稍后重试一次",
                tone: "error",
              });
            }
          },
        },
        controller.signal,
      );
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        updateBot({ error: "已停止生成" });
      } else {
        updateBot({ error: errorMessage(error) });
        if (error instanceof ApiError && (error.code === "QUOTA_EXCEEDED" || error.status === 429)) {
          toast({
            title: "今日对话配额已用完",
            description: `${error.message}（可在能力设置里调整每日上限）`,
            tone: "error",
          });
        } else if (error instanceof ApiError && (error.code === "no_provider" || error.code === "no_api_key")) {
          toast({
            title: "还没有可用的模型",
            description: "请先到「设置 → 模型接入」添加一个 OpenAI 兼容供应商。",
            tone: "error",
          });
        } else {
          toast({ title: "发送失败", description: errorMessage(error), tone: "error" });
        }
      }
    } finally {
      window.clearInterval(timer);
      if (streamTimerRef.current === timer) streamTimerRef.current = null;
      flush();
      setMessages((previous) =>
        previous.map((message) => (message.id === botMessageId ? { ...message, streaming: false } : message)),
      );
      setBusy(false);
      if (controllerRef.current === controller) controllerRef.current = null;
      if (currentScenarioIdRef.current === scenarioId) {
        void refreshMemory(scenarioId);
        void refreshVocab();
        void refreshHealth();
      }
    }
  };

  const stop = () => {
    controllerRef.current?.abort();
  };

  const canSend = draft.trim().length > 0 && !busy && Boolean(current) && !restoring;
  const dueWords = vocabItems.filter((item) => item.due).slice(0, 3);

  const sidebar = (
    <ScenarioSidebar
      scenarios={scenarios}
      currentId={current?.id ?? null}
      domain={domain}
      level={level}
      creating={creating}
      loading={scenariosLoading}
      error={createError}
      onDomainChange={setDomain}
      onLevelChange={setLevel}
      onCreate={() => void createScenario()}
      onSelect={selectScenario}
    />
  );

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="能力 · 情景英语"
        title="情景英语"
        description="选一个情景，用英文聊下去；AI 扮演另一方，并实时纠错、沉淀生词与情景记忆。"
        actions={
          <>
            <Badge tone={health?.degraded ? "amber" : health ? "jade" : "neutral"}>
              <Icon name="cpu" className="h-3 w-3" />
              {provider || health?.provider || "模型读取中"}
            </Badge>
            {ttft != null ? <span className="text-[12px] text-ink-faint">首字 {ttft}ms</span> : null}
            <Button variant="secondary" size="sm" disabled={!current} onClick={newChat}>
              <Icon name="plus" className="h-3.5 w-3.5" />
              新对话
            </Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[250px_minmax(0,1fr)] xl:grid-cols-[260px_minmax(0,1fr)_290px]">
        {/* 左：情景列表 */}
        <aside className="card hidden h-[calc(100dvh-14rem)] min-h-[520px] overflow-hidden lg:block">
          {sidebar}
        </aside>

        {/* 中：对话 */}
        <section className="card flex h-[calc(100dvh-14rem)] min-h-[560px] min-w-0 flex-col overflow-hidden">
          <header className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5 md:px-4">
            <Button
              variant="secondary"
              size="icon-sm"
              className="lg:hidden"
              aria-label="打开情景列表"
              onClick={() => setScenarioDrawerOpen(true)}
            >
              <Icon name="languages" className="h-4 w-4" />
            </Button>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13.5px] font-medium text-ink">
                {current?.title_zh ?? "未选择情景"}
              </p>
              <p className="truncate text-[11px] text-ink-faint">
                {topicTitle || (topics.length ? `话题池 ${topics.length} 个，当前未开始` : "选择一个情景开始")}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-0.5">
              {ttft != null ? (
                <span className="mr-1 hidden text-[11px] text-ink-faint sm:inline">首字 {ttft}ms</span>
              ) : null}
              {provider || health?.provider ? (
                <Badge tone="outline" className="mr-1 hidden sm:inline-flex">
                  {provider || health?.provider}
                </Badge>
              ) : null}
              <IconAction
                icon="brain"
                label="情景记忆"
                onClick={() => setMemoryDrawerOpen(true)}
              />
              <IconAction
                icon="book-open"
                label="生词本"
                badge={dueCount || undefined}
                onClick={() => void openVocab()}
              />
              <IconAction icon="list-checks" label="错误档案" onClick={() => void openErrors()} />
              <IconAction icon="file-text" label="资料库" onClick={openDocuments} />
              <IconAction icon="chart-column" label="成本看板" onClick={openStats} />
              <IconAction icon="type" label="偏好契约" onClick={openContract} />
            </div>
          </header>

          {health?.degraded ? (
            <div className="flex items-center gap-1.5 border-b border-amber/30 bg-amber/10 px-4 py-1.5 text-[11px] text-amber">
              <Icon name="alert-circle" className="h-3.5 w-3.5 shrink-0" />
              辅助链路降级中：对话可用，但纠错 / 记忆可能不完整。
            </div>
          ) : null}

          <MemoryPanel
            memory={memory}
            expanded={memoryExpanded}
            onToggle={() => setMemoryExpanded((value) => !value)}
          />

          <ChatThread
            messages={messages}
            loadingHistory={restoring}
            topics={topics}
            activeError={activeError}
            knowledgeCard={knowledgeCard}
            knowledgeLoading={knowledgeLoading}
            onOpenError={(error) => void openError(error)}
            onCloseError={() => setActiveError(null)}
            onSaveWord={(word, context) => void saveWord(word, context)}
            savingWord={savingWord}
            topicTitle={topicTitle}
          />

          <ChatComposer
            draft={draft}
            busy={busy}
            canSend={canSend}
            disabled={!current}
            onChange={setDraft}
            onSend={() => void send()}
            onStop={stop}
          />
        </section>

        {/* 右：学习台（桌面三栏） */}
        <aside className="hidden h-[calc(100dvh-14rem)] min-h-[520px] overflow-y-auto xl:block">
          <ContextRail
            topics={topics}
            topicTitle={topicTitle}
            dueCount={dueCount}
            dueWords={dueWords}
            health={health}
            onOpenVocab={() => void openVocab()}
            onOpenErrors={() => void openErrors()}
            onOpenDocuments={openDocuments}
            onOpenStats={openStats}
            onOpenContract={openContract}
          />
        </aside>
      </div>

      {/* 移动端情景抽屉 */}
      {scenarioDrawerOpen ? (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <button
            type="button"
            className="overlay-mask absolute inset-0 bg-ink/25 backdrop-blur-[2px]"
            aria-label="关闭情景列表"
            onClick={() => setScenarioDrawerOpen(false)}
          />
          <aside className="drawer-in relative flex h-full w-[min(100vw-3rem,300px)] flex-col border-r border-line bg-surface shadow-lift">
            <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
              <p className="text-[14px] font-semibold text-ink">情景</p>
              <button
                type="button"
                onClick={() => setScenarioDrawerOpen(false)}
                className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
                aria-label="关闭"
              >
                <Icon name="x" className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <ScenarioSidebar
                scenarios={scenarios}
                currentId={current?.id ?? null}
                domain={domain}
                level={level}
                creating={creating}
                loading={scenariosLoading}
                error={createError}
                onDomainChange={setDomain}
                onLevelChange={setLevel}
                onCreate={() => void createScenario()}
                onSelect={selectScenario}
                hideHeader
              />
            </div>
          </aside>
        </div>
      ) : null}

      <MemoryDrawer
        open={memoryDrawerOpen}
        onOpenChange={setMemoryDrawerOpen}
        memory={memory}
        scenarioTitle={current?.title_zh ?? null}
      />

      <VocabDrawer
        open={vocabOpen}
        onOpenChange={setVocabOpen}
        items={vocabItems}
        dueCount={dueCount}
        loading={vocabLoading}
        reviewing={reviewing}
        onReview={(lemma, rating) => void reviewWord(lemma, rating)}
        onRefresh={() => {
          setVocabLoading(true);
          void refreshVocab().finally(() => setVocabLoading(false));
        }}
      />

      <ErrorProfileDrawer
        open={errorsOpen}
        onOpenChange={setErrorsOpen}
        profile={errorProfile}
        loading={errorsLoading}
        onRefresh={() => void refreshErrors()}
      />

      <DocumentsDrawer
        open={documentsOpen}
        onOpenChange={setDocumentsOpen}
        items={documents}
        loading={documentsLoading}
        importing={documentsImporting}
        scenarioTitle={current?.title_zh ?? null}
        onImportText={importDocumentText}
        onUpload={uploadDocument}
        onDelete={(id) => void deleteDocument(id)}
        onRefresh={() => void refreshDocuments()}
      />

      <ContractDrawer
        open={contractOpen}
        onOpenChange={setContractOpen}
        contract={contract}
        loading={contractLoading}
        saving={contractSaving}
        warnings={contractWarnings}
        onSave={(next) => void saveContract(next)}
        onRefresh={() => void refreshContract()}
      />

      <StatsDrawer
        open={statsOpen}
        onOpenChange={setStatsOpen}
        stats={stats}
        loading={statsLoading}
        onRefresh={() => void refreshStats()}
      />
    </div>
  );
}
