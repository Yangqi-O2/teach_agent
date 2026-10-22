import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";

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
  Segmented,
  Textarea,
} from "../../components/ui/primitives";
import {
  api,
  type DigestDetail,
  type DigestExportFormat,
  type DigestGroup,
  type DigestOptions,
  type DigestPreview,
  type DigestSource,
  type DigestSummary,
  type Job,
} from "../../lib/api";
import { cn, relativeTime } from "../../lib/utils";
import { useApp } from "../../store/app";

const HISTORY_LIMIT = 20;

const STATUS_META: Record<string, { label: string; tone: "neutral" | "jade" | "amber" | "danger" }> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "生成中", tone: "amber" },
  done: { label: "已完成", tone: "jade" },
  error: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "neutral" },
};

const EXPORTS: { format: DigestExportFormat; label: string; icon: string }[] = [
  { format: "txt", label: "TXT", icon: "file-text" },
  { format: "md", label: "待办 MD", icon: "list-checks" },
  { format: "ics", label: "日程 ICS", icon: "calendar" },
  { format: "json", label: "JSON", icon: "database" },
];

type ResultTab = "summary" | "todos" | "schedule";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function statusMeta(status: string): { label: string; tone: "neutral" | "jade" | "amber" | "danger" } {
  return STATUS_META[status] ?? { label: status || "未知", tone: "neutral" };
}

function formatDigestTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/* ---------------- 局部表单控件 ---------------- */

function Select({
  id,
  value,
  onChange,
  disabled,
  children,
  ariaLabel,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  children: ReactNode;
  ariaLabel: string;
}) {
  return (
    <div className="relative">
      <select
        id={id}
        aria-label={ariaLabel}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="w-full appearance-none rounded-xl border border-line bg-surface px-3.5 py-2.5 pr-9 text-sm text-ink transition-colors focus:border-brand/60 focus:outline-none focus:ring-4 focus:ring-brand/10 disabled:opacity-50"
      >
        {children}
      </select>
      <Icon
        name="chevron-down"
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
      />
    </div>
  );
}

function CheckBox({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-[5px] border transition-colors",
        checked ? "border-jade/40 bg-jade/15 text-jade" : "border-line bg-surface text-transparent",
      )}
    >
      <Icon name="check" className="h-3 w-3" strokeWidth={2.4} />
    </span>
  );
}

/* ---------------- 结果区局部组件 ---------------- */

function SummarySection({ groups }: { groups: DigestGroup[] }) {
  if (groups.length === 0) {
    return <EmptyState icon="file-text" className="border-0" title="没有可展示的总结" description="模型没有返回结构化内容，可以重新生成一次。" />;
  }
  return (
    <div className="stagger space-y-5">
      {groups.map((group) => (
        <section key={group.name || "default"}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="font-display text-[15px] font-semibold text-ink">{group.name || "未命名会话"}</h3>
            <Badge tone="neutral">{group.message_count} 条</Badge>
          </div>
          {group.structured_text ? (
            <pre className="whitespace-pre-wrap break-words rounded-xl bg-surface-2 px-4 py-3.5 font-sans text-[13px] leading-[1.95] text-ink-soft">
              {group.structured_text}
            </pre>
          ) : (
            <p className="rounded-xl bg-surface-2 px-4 py-3.5 text-[13px] leading-relaxed text-ink-soft">
              {group.one_line || "这条群没有可总结的内容。"}
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

function TodoSection({ groups }: { groups: DigestGroup[] }) {
  const hasTodos = groups.some((group) => group.items.length > 0 || group.schedules.length > 0);
  if (!hasTodos) {
    return (
      <EmptyState
        icon="list-checks"
        className="border-0"
        title="没有提取到待办"
        description="这段聊天记录里没有明确的行动项，或者模型判断暂时不需要跟进。"
      />
    );
  }
  return (
    <div className="stagger space-y-5">
      {groups
        .filter((group) => group.items.length > 0 || group.schedules.length > 0)
        .map((group) => (
          <section key={group.name || "default"}>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h3 className="font-display text-[15px] font-semibold text-ink">{group.name || "未命名会话"}</h3>
              <Badge tone="neutral">{group.items.length} 项待办</Badge>
              {group.schedules.length ? <Badge tone="amber">{group.schedules.length} 个日程</Badge> : null}
            </div>
            <ul className="space-y-1.5">
              {group.items.map((item, index) => (
                <li key={`item-${index}`} className="flex items-start gap-2.5 rounded-lg bg-surface-2 px-3 py-2">
                  <CheckBox checked={false} />
                  <span className="min-w-0 flex-1 break-words text-[13px] leading-relaxed text-ink-soft">{item}</span>
                </li>
              ))}
              {group.schedules.map((schedule, index) => (
                <li key={`schedule-${index}`} className="flex items-start gap-2.5 rounded-lg bg-surface-2 px-3 py-2">
                  <CheckBox checked={schedule.done} />
                  <div className="min-w-0 flex-1">
                    <p className={cn("text-[13px] leading-relaxed text-ink", schedule.done && "text-ink-faint line-through")}>
                      {schedule.title}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      {schedule.datetime ? (
                        <Badge tone="amber">
                          <Icon name="clock" className="h-3 w-3" />
                          {formatDigestTime(schedule.datetime)}
                        </Badge>
                      ) : (
                        <Badge tone="outline">未注明时间</Badge>
                      )}
                      {schedule.note ? <span className="text-[11.5px] text-ink-faint">{schedule.note}</span> : null}
                      {schedule.source_sender ? (
                        <span className="text-[11px] text-ink-faint">@{schedule.source_sender}</span>
                      ) : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))}
    </div>
  );
}

function ScheduleSection({ groups }: { groups: DigestGroup[] }) {
  const schedules = useMemo(
    () =>
      groups
        .flatMap((group) =>
          group.schedules.map((schedule) => ({ ...schedule, group: group.name || "未命名会话" })),
        )
        .sort((a, b) => (a.datetime || "9999").localeCompare(b.datetime || "9999")),
    [groups],
  );
  if (schedules.length === 0) {
    return (
      <EmptyState
        icon="calendar"
        className="border-0"
        title="没有提取到日程"
        description="聊天里没有出现明确的时间安排；如果确实有，可以换一个总结风格再生成一次。"
      />
    );
  }
  return (
    <div className="stagger space-y-2">
      {schedules.map((schedule, index) => (
        <article key={`${schedule.group}-${index}`} className="flex items-start gap-3 rounded-xl bg-surface-2 px-3.5 py-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface text-amber">
            <Icon name="calendar" className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[13px] font-medium text-ink">{schedule.title || "未命名日程"}</p>
              {schedule.datetime ? (
                <Badge tone="amber">{formatDigestTime(schedule.datetime)}</Badge>
              ) : (
                <Badge tone="outline">未注明时间</Badge>
              )}
              {schedule.done ? <Badge tone="jade">已完成</Badge> : null}
            </div>
            {schedule.note ? <p className="mt-1 text-[12px] leading-relaxed text-ink-faint">{schedule.note}</p> : null}
            <p className="mt-1 text-[11px] text-ink-faint">
              {schedule.group}
              {schedule.source_sender ? ` · @${schedule.source_sender}` : ""}
            </p>
          </div>
        </article>
      ))}
    </div>
  );
}

function ResultCard({
  detail,
  styleLabel,
  tab,
  onTabChange,
}: {
  detail: DigestDetail;
  styleLabel: (style: string) => string;
  tab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
}) {
  const meta = statusMeta(detail.status);
  const groups = detail.result?.groups ?? [];
  const stats = detail.result?.stats;
  return (
    <section className="card overflow-hidden">
      <div className="border-b border-line/70 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-display text-[20px] font-semibold leading-snug tracking-tight text-ink">
              {detail.title || "群聊简报"}
            </h2>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge tone={meta.tone}>{meta.label}</Badge>
              <Badge tone="neutral">保留 {detail.kept_count} 条</Badge>
              {detail.provider || detail.model ? (
                <Badge tone="outline">
                  {[detail.provider, detail.model].filter(Boolean).join(" · ")}
                </Badge>
              ) : null}
              <Badge tone="brand">{styleLabel(detail.style)}</Badge>
              <span className="text-[11.5px] text-ink-faint">{relativeTime(detail.created_at)}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {detail.status === "done" && detail.result
              ? EXPORTS.map((item) => (
                  <a
                    key={item.format}
                    href={api.digest.exportUrl(detail.id, item.format)}
                    download
                    aria-label={`导出 ${item.label}`}
                    className="inline-flex"
                  >
                    <Button variant="ghost" size="sm">
                      <Icon name={item.icon} className="h-3.5 w-3.5" />
                      {item.label}
                    </Button>
                  </a>
                ))
              : null}
          </div>
        </div>
        {detail.one_line ? (
          <blockquote className="mt-4 border-l-2 border-brand pl-3.5 text-[14px] leading-relaxed text-ink">
            {detail.one_line}
          </blockquote>
        ) : null}
      </div>

      {detail.result ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
            <Segmented<ResultTab>
              value={tab}
              onChange={onTabChange}
              options={[
                { value: "summary", label: "总结" },
                { value: "todos", label: "待办" },
                { value: "schedule", label: "日程" },
              ]}
            />
            {stats ? (
              <span className="text-[11.5px] text-ink-faint">
                清洗 {stats.before} → {stats.after} 条
                {stats.chunks > 1 ? ` · 分 ${stats.chunks} 块总结` : ""}
              </span>
            ) : null}
          </div>
          <div className="px-5 pb-5 pt-4">
            {tab === "summary" ? <SummarySection groups={groups} /> : null}
            {tab === "todos" ? <TodoSection groups={groups} /> : null}
            {tab === "schedule" ? <ScheduleSection groups={groups} /> : null}
          </div>
        </>
      ) : (
        <div className="px-5 pb-5 pt-4">
          {detail.status === "error" ? (
            <div className="rounded-xl bg-danger/10 px-3.5 py-3 text-[12.5px] leading-relaxed text-danger">
              {detail.error || "生成失败，请检查模型供应商后重试。"}
            </div>
          ) : (
            <div className="rounded-xl bg-surface-2 px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-soft">
              {detail.status === "queued" || detail.status === "running"
                ? "这份简报还在生成中，稍等片刻刷新看看。"
                : "这份简报没有可展示的内容。"}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function RecentCard({
  list,
  loading,
  currentId,
  onOpen,
  onDelete,
  onRefresh,
}: {
  list: DigestSummary[];
  loading: boolean;
  currentId: number | null;
  onOpen: (item: DigestSummary) => void;
  onDelete: (item: DigestSummary) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="card overflow-hidden">
      <div className="flex items-center gap-2 border-b border-line/70 px-5 py-3.5">
        <Icon name="history" className="h-4 w-4 text-ink-faint" />
        <h2 className="text-[13.5px] font-medium text-ink">最近简报</h2>
        <Badge tone="neutral">{list.length}</Badge>
        <Button variant="ghost" size="icon-sm" className="ml-auto" onClick={onRefresh} aria-label="刷新最近简报">
          <Icon name="refresh-cw" className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </Button>
      </div>

      {loading && list.length === 0 ? (
        <div className="space-y-2 p-3">
          {[0, 1, 2].map((index) => (
            <div key={index} className="shimmer h-14 rounded-xl" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <EmptyState
          icon="message-square"
          className="border-0 px-5 py-9"
          title="还没有简报"
          description="在左边粘贴一段群聊记录，生成第一份简报后会出现在这里。"
        />
      ) : (
        <div className="stagger divide-y divide-line/60">
          {list.map((item) => {
            const meta = statusMeta(item.status);
            const active = currentId === item.id;
            return (
              <div
                key={item.id}
                className={cn(
                  "group flex items-start gap-2 px-5 py-3 transition-colors",
                  active ? "bg-brand-soft/50" : "hover:bg-surface-2/60",
                )}
              >
                <button
                  type="button"
                  onClick={() => onOpen(item)}
                  aria-current={active ? "true" : undefined}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="flex items-center gap-2">
                    <p className="truncate text-[13px] font-medium text-ink">{item.title || "群聊简报"}</p>
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                    <span className="ml-auto shrink-0 text-[11px] text-ink-faint">{relativeTime(item.created_at)}</span>
                  </div>
                  <p className="mt-0.5 truncate text-[12px] text-ink-faint">
                    {item.one_line ||
                      (item.status === "done"
                        ? "（没有一句话总结）"
                        : item.status === "error"
                          ? "生成失败，点开查看原因"
                          : item.status === "cancelled"
                            ? "已取消"
                            : "生成中…")}
                  </p>
                </button>
                <div className="flex shrink-0 items-center gap-1.5 pt-0.5">
                  <Badge tone="neutral">保留 {item.kept_count} 条</Badge>
                  <button
                    type="button"
                    onClick={() => onDelete(item)}
                    aria-label={`删除 ${item.title || "群聊简报"}`}
                    className="rounded-md p-1 text-ink-faint opacity-100 transition-all hover:bg-danger/10 hover:text-danger focus-visible:opacity-100 sm:opacity-0 sm:group-hover:opacity-100"
                  >
                    <Icon name="trash-2" className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ---------------- 页面 ---------------- */

export function WechatDigestPage() {
  const toast = useApp((s) => s.toast);
  const providers = useApp((s) => s.providers);
  const defaultProvider = providers.find((provider) => provider.is_default) ?? providers[0];

  const [options, setOptions] = useState<DigestOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  const [sourceId, setSourceId] = useState("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [style, setStyle] = useState("general");
  const [providerId, setProviderId] = useState("");

  const [preview, setPreview] = useState<DigestPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(true);

  const [list, setList] = useState<DigestSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [current, setCurrent] = useState<DigestDetail | null>(null);
  const [currentLoading, setCurrentLoading] = useState(false);
  const [tab, setTab] = useState<ResultTab>("summary");

  const [pending, setPending] = useState<DigestSummary | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DigestSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  const generatingRef = useRef(false);
  const pendingIdRef = useRef<number | null>(null);
  const autoSelectedRef = useRef(false);

  const selectedSource: DigestSource | null = options?.sources.find((source) => source.id === sourceId) ?? null;
  const paramProperties = selectedSource?.params_schema?.properties ?? {};
  const textKey =
    Object.entries(paramProperties).find(([, property]) => property.format === "textarea")?.[0] ??
    (Object.prototype.hasOwnProperty.call(paramProperties, "text") ? "text" : "");
  const textLength = textKey ? (params[textKey] ?? "").length : 0;
  const maxChars = options?.settings?.max_chars ?? 0;
  const styleLabel = useCallback(
    (id: string) => options?.styles.find((item) => item.id === id)?.label ?? id,
    [options],
  );
  const missingRequired = Object.entries(paramProperties).find(
    ([key, property]) => property.required && !(params[key] ?? "").trim(),
  );

  const loadOptions = useCallback(async () => {
    setOptionsLoading(true);
    setOptionsError(null);
    try {
      const data = await api.digest.options();
      setOptions(data);
      setStyle((previous) => previous || data.settings?.default_style || "general");
      const firstSource = data.sources.find((source) => source.available) ?? data.sources[0];
      if (firstSource) setSourceId((previous) => previous || firstSource.id);
    } catch (loadError) {
      const message = errorMessage(loadError);
      setOptionsError(message);
      toast({ title: "加载群聊简报配置失败", description: message, tone: "error" });
    } finally {
      setOptionsLoading(false);
    }
  }, [toast]);

  const reloadList = useCallback(async () => {
    setListLoading(true);
    try {
      setList(await api.digest.list(HISTORY_LIMIT));
    } catch (loadError) {
      toast({ title: "加载最近简报失败", description: errorMessage(loadError), tone: "error" });
    } finally {
      setListLoading(false);
    }
  }, [toast]);

  const openDigest = useCallback(
    async (item: DigestSummary) => {
      setCurrentLoading(true);
      try {
        const detail = await api.digest.get(item.id);
        setCurrent(detail);
        setTab("summary");
      } catch (loadError) {
        const message = errorMessage(loadError);
        toast({ title: "读取简报失败", description: message, tone: "error" });
      } finally {
        setCurrentLoading(false);
      }
    },
    [toast],
  );

  useEffect(() => {
    void loadOptions();
  }, [loadOptions]);

  useEffect(() => {
    void reloadList();
  }, [reloadList]);

  // 数据源切换（或默认值就绪）时，按 params_schema 初始化参数表单
  useEffect(() => {
    const source = options?.sources.find((item) => item.id === sourceId);
    if (!source) return;
    const defaults: Record<string, string> = {};
    for (const [key, property] of Object.entries(source.params_schema?.properties ?? {})) {
      defaults[key] = property.default == null ? "" : String(property.default);
    }
    setParams(defaults);
    setPreview(null);
  }, [options, sourceId]);

  // 首次拿到历史列表时，自动打开最近一条，避免右栏一直空着
  useEffect(() => {
    if (autoSelectedRef.current || current || list.length === 0) return;
    autoSelectedRef.current = true;
    void openDigest(list[0]);
  }, [list, current, openDigest]);

  const fillSample = () => {
    if (!selectedSource?.sample_params) {
      toast({ title: "这个数据源没有示例", tone: "default" });
      return;
    }
    const next: Record<string, string> = { ...params };
    for (const [key, value] of Object.entries(selectedSource.sample_params)) {
      next[key] = value == null ? "" : String(value);
    }
    setParams(next);
    setPreview(null);
    toast({ title: "已填入示例", description: "可以直接点「预览清洗」看看效果。", tone: "default" });
  };

  const readClipboard = async () => {
    try {
      if (!navigator.clipboard?.readText) {
        throw new Error("当前浏览器不支持读取剪贴板");
      }
      const text = await navigator.clipboard.readText();
      if (!text.trim()) {
        toast({ title: "剪贴板是空的", tone: "default" });
        return;
      }
      const key = textKey || Object.keys(paramProperties)[0] || "text";
      setParams((previous) => ({ ...previous, [key]: text }));
      setPreview(null);
      toast({ title: "已从剪贴板填入", description: `共 ${text.length} 个字符`, tone: "success" });
    } catch {
      toast({ title: "读取剪贴板失败", description: "可以复制聊天记录后手动粘贴（⌘V）。", tone: "error" });
    }
  };

  const runPreview = async () => {
    if (!selectedSource) return;
    if (missingRequired) {
      toast({ title: `「${missingRequired[1].title ?? missingRequired[0]}」不能为空`, tone: "error" });
      return;
    }
    setPreviewLoading(true);
    setError(null);
    try {
      const data = await api.digest.preview({ source: selectedSource.id, params });
      setPreview(data);
      setPreviewOpen(true);
      if (data.total_after === 0) {
        toast({
          title: "清洗后没有剩下消息",
          description: "检查一下格式：通常需要「昵称: 内容」这样的行。",
          tone: "default",
        });
      }
    } catch (previewError) {
      const message = errorMessage(previewError);
      setError(message);
      toast({ title: "预览失败", description: message, tone: "error" });
    } finally {
      setPreviewLoading(false);
    }
  };

  const generate = useCallback(async () => {
    if (generatingRef.current) return;
    if (!selectedSource) return;
    if (missingRequired) {
      toast({ title: `「${missingRequired[1].title ?? missingRequired[0]}」不能为空`, tone: "error" });
      return;
    }
    if (maxChars && textLength > maxChars) {
      toast({ title: "内容太长了", description: `单次最多 ${maxChars} 个字符，请分几次粘贴。`, tone: "error" });
      return;
    }
    if (providers.length === 0) {
      toast({
        title: "还没有可用的模型",
        description: "请先去「设置 → 模型接入」添加一个 OpenAI 兼容供应商。",
        tone: "error",
      });
      return;
    }
    generatingRef.current = true;
    setCreating(true);
    setError(null);
    try {
      const response = await api.digest.create({
        source: selectedSource.id,
        params,
        style,
        provider_id: providerId ? Number(providerId) : null,
      });
      pendingIdRef.current = response.digest.id;
      setPending(response.digest);
      setJob({
        id: response.job_id,
        type: "wechat_digest",
        title: response.digest.title,
        status: "queued",
        progress: 5,
        message: "解析聊天记录",
        error: null,
        result: null,
        created_at: null,
        updated_at: null,
        finished_at: null,
      });
      setActiveJobId(response.job_id);
      toast({ title: "开始生成简报", description: "可以切到别的页面，任务会在后台继续。", tone: "default" });
    } catch (createError) {
      generatingRef.current = false;
      setCreating(false);
      const message = errorMessage(createError);
      setError(message);
      toast({ title: "生成失败", description: message, tone: "error" });
    }
  }, [selectedSource, missingRequired, maxChars, textLength, providers.length, params, style, providerId, toast]);

  // 轮询任务进度：done / error / cancelled 后收尾；卸载时清理定时器
  useEffect(() => {
    if (!activeJobId) return;
    let stopped = false;
    let timer = 0;

    const finish = async (kind: "done" | "error" | "cancelled", state: Job) => {
      stopped = true;
      window.clearInterval(timer);
      setActiveJobId(null);
      setJob(null);
      generatingRef.current = false;

      if (kind === "done") {
        const digestId = pendingIdRef.current;
        pendingIdRef.current = null;
        try {
          if (digestId != null) {
            const detail = await api.digest.get(digestId);
            setCurrent(detail);
            setTab("summary");
          }
          await reloadList();
          toast({ title: "简报已生成", description: "一句话、待办与日程都整理好了。", tone: "success" });
        } catch (finishError) {
          const message = errorMessage(finishError);
          setError(message);
          toast({ title: "简报已生成，但读取详情失败", description: message, tone: "error" });
          void reloadList();
        } finally {
          setCreating(false);
          setPending(null);
        }
        return;
      }

      pendingIdRef.current = null;
      setCreating(false);
      setPending(null);

      if (kind === "error") {
        const message = state.error || "生成失败，请检查模型供应商配置后重试。";
        setError(message);
        void reloadList();
        toast({ title: "生成失败", description: message, tone: "error" });
        return;
      }

      void reloadList();
      toast({ title: "已取消生成", tone: "default" });
    };

    const poll = async () => {
      try {
        const state = await api.jobs.get(activeJobId);
        if (stopped) return;
        setJob(state);
        if (state.status === "done") void finish("done", state);
        else if (state.status === "error") void finish("error", state);
        else if (state.status === "cancelled") void finish("cancelled", state);
      } catch {
        /* 单次轮询失败不打断，下一个 tick 继续 */
      }
    };

    timer = window.setInterval(() => void poll(), 1000);
    void poll();
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [activeJobId, reloadList, toast]);

  const cancel = async () => {
    if (!activeJobId) return;
    try {
      await api.jobs.cancel(activeJobId);
      toast({ title: "已请求取消", description: "任务会尽快停下。", tone: "default" });
    } catch (cancelError) {
      toast({ title: "取消失败", description: errorMessage(cancelError), tone: "error" });
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const removedId = deleteTarget.id;
      await api.digest.remove(removedId);
      setDeleteTarget(null);
      const items = await api.digest.list(HISTORY_LIMIT);
      setList(items);
      if (current?.id === removedId) {
        if (items.length > 0) {
          const detail = await api.digest.get(items[0].id);
          setCurrent(detail);
          setTab("summary");
        } else {
          setCurrent(null);
        }
      }
      toast({ title: "已删除", tone: "success" });
    } catch (removeError) {
      toast({ title: "删除失败", description: errorMessage(removeError), tone: "error" });
    } finally {
      setDeleting(false);
    }
  };

  const onFormKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void generate();
    }
  };

  const generating = creating;
  const canGenerate = Boolean(selectedSource) && !generating && providers.length > 0;
  const styleHint = options?.styles.find((item) => item.id === style)?.description;

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="能力 · 群聊"
        title="群聊简报"
        description="粘贴微信群 / QQ 群聊天记录，先清洗降噪，再交给模型整理成「一句话 + 重要事项 + 待办 + 日程」。数据只留在本机。"
        actions={
          <Link to="/settings?tab=models" aria-label="前往设置配置模型接入">
            <Button variant={providers.length > 0 ? "secondary" : "subtle"} size="sm">
              <Dot tone={providers.length > 0 ? "jade" : "amber"} />
              <Icon name="cpu" className="h-3.5 w-3.5" />
              {providers.length > 0 ? `模型 · ${defaultProvider?.name ?? "已接入"}` : "先接入模型"}
              <Icon name="chevron-right" className="h-3.5 w-3.5 opacity-60" />
            </Button>
          </Link>
        }
      />

      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        {/* 左：新建简报 */}
        <div className="card p-5">
          <div className="mb-4 flex items-center gap-2 text-[13px] font-medium text-ink">
            <Icon name="clipboard-paste" className="h-4 w-4 text-brand" />
            新建简报
            <span className="ml-auto text-[11px] font-normal text-ink-faint">数据只留在本机</span>
          </div>

          {optionsLoading ? (
            <div className="space-y-3" aria-label="正在加载能力配置">
              <div className="shimmer h-16 rounded-xl" />
              <div className="shimmer h-44 rounded-xl" />
              <div className="shimmer h-9 rounded-xl" />
              <div className="shimmer h-9 rounded-xl" />
              <div className="shimmer h-10 rounded-xl" />
            </div>
          ) : !options ? (
            <div className="rounded-xl bg-danger/10 p-3.5 text-[12.5px] leading-relaxed text-danger">
              <p>无法读取能力配置：{optionsError ?? "未知错误"}</p>
              <Button variant="ghost" size="sm" className="mt-2" onClick={() => void loadOptions()}>
                <Icon name="refresh-cw" className="h-3.5 w-3.5" />
                重试
              </Button>
            </div>
          ) : (
            <div className="space-y-4" onKeyDown={onFormKeyDown}>
              {/* 数据源 */}
              <div>
                <p className="mb-1.5 text-[13px] font-medium text-ink">数据源</p>
                <div className="space-y-2">
                  {options.sources.map((source) => {
                    const active = source.id === sourceId;
                    return (
                      <button
                        key={source.id}
                        type="button"
                        disabled={!source.available}
                        onClick={() => setSourceId(source.id)}
                        aria-pressed={active}
                        className={cn(
                          "w-full rounded-xl border p-3 text-left transition-colors",
                          active
                            ? "border-brand/30 bg-brand-soft/60"
                            : "border-line bg-surface hover:border-brand/20 hover:bg-surface-2/60",
                          !source.available && "cursor-not-allowed opacity-55",
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <Icon
                            name={active ? "clipboard-paste" : "message-square"}
                            className={cn("h-4 w-4", active ? "text-brand" : "text-ink-faint")}
                          />
                          <span className="text-[13px] font-medium text-ink">{source.name}</span>
                          {source.badge ? <Badge tone="brand">{source.badge}</Badge> : null}
                          {active ? <Icon name="check" className="ml-auto h-4 w-4 text-brand" /> : null}
                        </div>
                        <p className="mt-1 text-[11.5px] leading-relaxed text-ink-faint">{source.description}</p>
                        {!source.available && source.hint ? (
                          <p className="mt-1 text-[11.5px] leading-relaxed text-amber">{source.hint}</p>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* 按 params_schema 渲染的参数 */}
              {Object.entries(paramProperties).map(([key, property]) => {
                const label = property.title ?? key;
                const isTextarea = property.format === "textarea";
                return (
                  <Field
                    key={key}
                    label={property.required ? `${label} *` : label}
                    htmlFor={`digest-param-${key}`}
                    hint={property.description}
                  >
                    {isTextarea ? (
                      <Textarea
                        id={`digest-param-${key}`}
                        aria-label={label}
                        value={params[key] ?? ""}
                        onChange={(event) => setParams((previous) => ({ ...previous, [key]: event.target.value }))}
                        placeholder="把聊天记录粘贴到这里…"
                        className="min-h-44 font-mono text-[12.5px]"
                      />
                    ) : (
                      <Input
                        id={`digest-param-${key}`}
                        aria-label={label}
                        value={params[key] ?? ""}
                        onChange={(event) => setParams((previous) => ({ ...previous, [key]: event.target.value }))}
                        placeholder={`请输入${label}`}
                      />
                    )}
                  </Field>
                );
              })}

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={fillSample}
                  disabled={!selectedSource?.sample_params}
                >
                  <Icon name="sparkles" className="h-3.5 w-3.5" />
                  填入示例
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void readClipboard()}>
                  <Icon name="clipboard-paste" className="h-3.5 w-3.5" />
                  从剪贴板读取
                </Button>
              </div>

              {maxChars > 0 && textKey ? (
                <p
                  className={cn(
                    "text-right text-[11px]",
                    textLength > maxChars ? "font-medium text-amber" : "text-ink-faint",
                  )}
                >
                  已输入 {textLength} 字符 · 上限 {maxChars}
                </p>
              ) : null}

              {/* 风格 + 模型 */}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="总结风格" htmlFor="digest-style" hint={styleHint}>
                  <Select
                    id="digest-style"
                    ariaLabel="总结风格"
                    value={style}
                    onChange={setStyle}
                  >
                    {options.styles.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field
                  label="使用模型"
                  htmlFor="digest-provider"
                  hint={
                    providers.length === 0 ? (
                      <span>
                        还没有模型，去{" "}
                        <Link to="/settings?tab=models" className="text-brand hover:underline">
                          设置 → 模型接入
                        </Link>
                      </span>
                    ) : undefined
                  }
                >
                  <Select
                    id="digest-provider"
                    ariaLabel="使用模型"
                    value={providerId}
                    onChange={setProviderId}
                    disabled={providers.length === 0}
                  >
                    <option value="">默认供应商</option>
                    {providers.map((provider) => (
                      <option key={provider.id} value={String(provider.id)}>
                        {provider.name} · {provider.chat_model}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>

              {providers.length === 0 ? (
                <div className="flex items-start gap-2 rounded-xl border border-amber/30 bg-amber/10 px-3 py-2.5 text-[12px] leading-relaxed text-amber">
                  <Icon name="alert-circle" className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    还没有可用的模型供应商，生成前请先到{" "}
                    <Link to="/settings?tab=models" className="font-medium underline">
                      设置 → 模型接入
                    </Link>{" "}
                    添加一个。
                  </span>
                </div>
              ) : null}

              {/* 操作区 */}
              <div className="space-y-3 border-t border-line/70 pt-4">
                {error ? (
                  <div className="flex items-start gap-2 rounded-xl bg-danger/10 px-3 py-2.5 text-[12px] leading-relaxed text-danger">
                    <Icon name="alert-circle" className="mt-0.5 h-4 w-4 shrink-0" />
                    <span className="min-w-0 break-words">{error}</span>
                  </div>
                ) : null}

                {preview ? (
                  <div className="rounded-xl border border-line bg-surface-2/70 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="neutral">原始 {preview.total_before} 条</Badge>
                      <Icon name="chevron-right" className="h-3 w-3 text-ink-faint" />
                      <Badge tone="jade">保留 {preview.total_after} 条</Badge>
                      {preview.total_before > preview.total_after ? (
                        <span className="text-[11px] text-ink-faint">
                          降噪 {preview.total_before - preview.total_after} 条
                        </span>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => setPreviewOpen((open) => !open)}
                        aria-expanded={previewOpen}
                        aria-label={previewOpen ? "收起清洗样例" : "展开清洗样例"}
                        className="ml-auto rounded-md p-1 text-ink-faint transition-colors hover:bg-surface hover:text-ink"
                      >
                        <Icon
                          name="chevron-down"
                          className={cn("h-4 w-4 transition-transform", previewOpen && "rotate-180")}
                        />
                      </button>
                    </div>
                    {preview.groups.length > 1 ? (
                      <p className="mt-1.5 text-[11px] text-ink-faint">
                        会话：
                        {preview.groups
                          .map((group) => `${group.name} ${group.before}→${group.after}`)
                          .join(" · ")}
                      </p>
                    ) : null}
                    {previewOpen ? (
                      <div className="mt-2.5">
                        <p className="mb-1.5 text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">
                          清洗后前 {preview.sample.length} 条
                        </p>
                        {preview.sample.length === 0 ? (
                          <p className="text-[11.5px] leading-relaxed text-ink-faint">
                            没有可保留的消息，检查一下粘贴内容的格式。
                          </p>
                        ) : (
                          <div className="max-h-44 overflow-y-auto rounded-lg bg-surface p-2.5">
                            {preview.sample.map((message, index) => (
                              <p
                                key={index}
                                className="truncate font-mono text-[11.5px] leading-relaxed text-ink-soft"
                              >
                                {message.time ? <span className="text-ink-faint">[{message.time}] </span> : null}
                                {message.sender ? <span className="text-brand-strong">{message.sender}: </span> : null}
                                {message.text}
                              </p>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="md"
                    className="flex-1"
                    loading={previewLoading}
                    onClick={() => void runPreview()}
                    disabled={!selectedSource}
                  >
                    <Icon name="search" className="h-3.5 w-3.5" />
                    预览清洗
                  </Button>
                  <Button
                    variant="primary"
                    size="md"
                    className="flex-[1.3]"
                    disabled={!canGenerate}
                    onClick={() => void generate()}
                  >
                    <Icon
                      name={generating ? "loader-2" : "wand-2"}
                      className={cn("h-3.5 w-3.5", generating && "animate-spin")}
                    />
                    {generating ? "生成中…" : "生成简报"}
                  </Button>
                </div>
                <p className="text-[11px] leading-relaxed text-ink-faint">
                  快捷键 ⌘ / Ctrl + Enter 生成。简报保存在本机 SQLite；生成时内容会发送给你配置的模型服务。
                </p>

                {generating ? (
                  <div className="rounded-xl border border-line bg-surface-2 p-3" aria-live="polite">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-[12px] text-ink-soft">{job?.message ?? "解析聊天记录"}</p>
                      <span className="font-mono text-[11px] text-ink-faint">
                        {Math.round(job?.progress ?? 5)}%
                      </span>
                    </div>
                    <Progress value={job?.progress ?? 5} className="mt-2" />
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="text-[11px] text-ink-faint">可以切走，任务在后台继续</span>
                      <Button variant="ghost" size="sm" onClick={() => void cancel()}>
                        <Icon name="square" className="h-3 w-3" />
                        取消
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </div>

        {/* 右：结果 + 最近简报 */}
        <div className="space-y-5">
          {generating ? (
            <section className="card p-5" aria-live="polite">
              <div className="flex items-center gap-2 text-[13px] font-medium text-ink">
                <Icon name="loader-2" className="h-4 w-4 animate-spin text-brand" />
                {pending?.title || "正在生成简报"}
              </div>
              <p className="mt-1 text-[12px] text-ink-faint">
                当前阶段：{job?.message ?? "解析聊天记录"} · 完成后会自动出现在这里
              </p>
              <div className="mt-5 space-y-2.5">
                <div className="shimmer h-3 w-2/3 rounded-full" />
                <div className="shimmer h-3 w-1/2 rounded-full" />
                <div className="shimmer h-24 rounded-xl" />
                <div className="shimmer h-3 w-3/4 rounded-full" />
              </div>
            </section>
          ) : currentLoading || (listLoading && !current) ? (
            <div className="card shimmer h-64" aria-label="正在读取简报" />
          ) : current ? (
            <ResultCard detail={current} styleLabel={styleLabel} tab={tab} onTabChange={setTab} />
          ) : (
            <EmptyState
              icon="message-square"
              title={list.length === 0 ? "还没有简报" : "选一份简报查看"}
              description={
                list.length === 0
                  ? "在左边粘贴一段微信群 / QQ 群聊天记录，预览清洗效果后点「生成简报」，这里会显示一句话总结、待办与日程。"
                  : "从下面的「最近简报」里点一份，或者用左边的「新建简报」生成一份新的。"
              }
              action={
                list.length === 0 ? (
                  <Button variant="secondary" size="sm" onClick={fillSample}>
                    <Icon name="sparkles" className="h-3.5 w-3.5" />
                    填入示例试试
                  </Button>
                ) : undefined
              }
            />
          )}

          {list.length > 0 || listLoading ? (
            <RecentCard
              list={list}
              loading={listLoading}
              currentId={current?.id ?? null}
              onOpen={(item) => void openDigest(item)}
              onDelete={setDeleteTarget}
              onRefresh={() => void reloadList()}
            />
          ) : null}
        </div>
      </div>

      <Modal
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="删除这份简报？"
        description={`「${deleteTarget?.title || "群聊简报"}」会从本机数据库移除，已导出的文件不受影响。`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button variant="danger" loading={deleting} onClick={() => void remove()}>
              删除
            </Button>
          </>
        }
      >
        <p className="text-[13px] leading-relaxed text-ink-soft">
          删除后无法恢复。如果只想重新整理，可以用同样的聊天记录再生成一份。
        </p>
      </Modal>
    </div>
  );
}
