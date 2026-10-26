import { useCallback, useEffect, useMemo, useState } from "react";

import { ProfileForm, draftToInput, emptyDraft, type ProfileDraft } from "../../components/ProfileForm";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { Badge, Button, EmptyState, Field, Input, Progress, Segmented } from "../../components/ui/primitives";
import { Modal } from "../../components/ui/overlay";
import { api, type CampusAsk, type CampusFeed, type CampusItem, type CampusRun } from "../../lib/api";
import { cn, relativeTime } from "../../lib/utils";
import { useApp } from "../../store/app";

const CATEGORY_TONE: Record<string, "brand" | "jade" | "amber" | "danger" | "neutral"> = {
  contest: "brand",
  exam: "amber",
  lecture: "jade",
  activity: "jade",
  policy: "neutral",
  other: "neutral",
};

const CATEGORY_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "contest", label: "竞赛" },
  { value: "exam", label: "考试" },
  { value: "lecture", label: "讲座" },
  { value: "activity", label: "活动" },
  { value: "policy", label: "公示" },
];

const INTERVAL_OPTIONS = [
  { value: "60", label: "每小时" },
  { value: "180", label: "每 3 小时" },
  { value: "360", label: "每 6 小时" },
  { value: "720", label: "每 12 小时" },
  { value: "1440", label: "每天" },
  { value: "0", label: "只手动" },
];

function fmtDay(value?: string | null): string {
  if (!value) return "";
  return value.length >= 10 ? value.slice(5, 10).replace("-", "/") : value;
}

function daysLeft(deadline?: string | null): number | null {
  if (!deadline) return null;
  const target = new Date(`${deadline.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86400000);
}

function DeadlineTag({ deadline }: { deadline?: string | null }) {
  const left = daysLeft(deadline);
  if (left === null) return null;
  const tone =
    left < 0
      ? "border-line text-ink-faint"
      : left <= 7
        ? "border-danger/30 bg-danger/10 text-danger"
        : left <= 21
          ? "border-amber/30 bg-amber/10 text-amber"
          : "border-line text-ink-soft";
  const text = left < 0 ? "已截止" : left === 0 ? "今天截止" : `${left} 天后截止`;
  return (
    <span className={cn("rounded-full border px-2 py-0.5 text-[10.5px]", tone)}>
      {fmtDay(deadline)} · {text}
    </span>
  );
}

function ItemCard({ item }: { item: CampusItem }) {
  return (
    <article className="card p-4 transition-colors hover:border-brand/25">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={CATEGORY_TONE[item.category] ?? "neutral"}>{item.category_label}</Badge>
        {item.published_at ? (
          <span className="text-[11px] text-ink-faint">{fmtDay(item.published_at)} 发布</span>
        ) : null}
        <DeadlineTag deadline={item.deadline} />
        {item.is_demo ? <Badge tone="neutral">示例</Badge> : null}
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer noopener"
          className="ml-auto inline-flex items-center gap-1 text-[11.5px] text-ink-faint transition-colors hover:text-brand-strong"
        >
          原文
          <Icon name="arrow-up-right" className="h-3 w-3" />
        </a>
      </div>

      <h3 className="mt-2 text-[14px] font-medium leading-relaxed text-ink">{item.title}</h3>
      {item.summary ? (
        <p className="mt-1 line-clamp-2 text-[12.5px] leading-relaxed text-ink-soft">{item.summary}</p>
      ) : null}

      {item.reason ? (
        <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-brand-soft/60 px-2.5 py-1.5 text-[11.5px] leading-relaxed text-brand-strong">
          <Icon name="sparkles" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>推荐理由：{item.reason}</span>
        </p>
      ) : null}
    </article>
  );
}

function AskPanel({ school, onNeedProfile }: { school: string; onNeedProfile: () => void }) {
  const toast = useApp((s) => s.toast);
  const [question, setQuestion] = useState("最近有什么值得参加的竞赛和活动？");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<CampusAsk | null>(null);

  const ask = async () => {
    const text = question.trim();
    if (!text) return;
    setAsking(true);
    try {
      setResult(await api.campus.ask(text, 8));
    } catch (error) {
      toast({ title: "提问失败", description: String(error), tone: "error" });
    } finally {
      setAsking(false);
    }
  };

  return (
    <section className="card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-[16px] font-semibold text-ink">问问{ school }最近有什么事</h2>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-faint">
            按你的学校、年级、专业和兴趣筛一遍，只回答已经抓到的通知。
          </p>
        </div>
        <button
          onClick={onNeedProfile}
          className="shrink-0 text-[11.5px] text-brand-strong underline-offset-4 hover:underline"
        >
          改资料
        </button>
      </div>

      <div className="mt-4 flex gap-2">
        <Input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") ask();
          }}
          placeholder="例如：最近有什么比赛可以参加？四六级报名截止了吗？"
        />
        <Button variant="primary" loading={asking} onClick={ask} className="shrink-0">
          提问
        </Button>
      </div>

      {result ? (
        <div className="mt-4 rounded-xl border border-line bg-surface-2/50 p-4">
          <div className="mb-2 flex items-center gap-2">
            <Badge tone={result.mode === "llm" ? "brand" : "neutral"}>
              {result.mode === "llm" ? "模型总结" : result.mode === "empty" ? "暂无数据" : "按画像排序"}
            </Badge>
            {result.note ? <span className="text-[11px] text-ink-faint">{result.note}</span> : null}
          </div>
          <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-relaxed text-ink-soft">
            {result.answer}
          </pre>
          {result.items.length ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {result.items.slice(0, 8).map((item) => (
                <a
                  key={item.id}
                  href={item.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex max-w-full items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] text-ink-soft transition-colors hover:border-brand/40 hover:text-brand-strong"
                >
                  <span className="truncate">{item.title.slice(0, 22)}</span>
                  <Icon name="arrow-up-right" className="h-3 w-3 shrink-0" />
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function SourceRow({ source }: { source: CampusFeed["sources"][number] }) {
  const tone =
    source.last_status === "ok" ? "jade" : source.last_status === "error" ? "danger" : "neutral";
  const label =
    source.last_status === "ok"
      ? "正常"
      : source.last_status === "error"
        ? "抓取失败"
        : source.last_status === "empty"
          ? "无条目"
          : "待抓取";
  return (
    <div className="flex items-start gap-2.5 py-2">
      <span className="mt-1.5">
        <span
          className={cn(
            "inline-block h-1.5 w-1.5 rounded-full",
            tone === "jade" ? "bg-jade" : tone === "danger" ? "bg-danger" : "bg-ink-faint",
          )}
        />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[12.5px] text-ink">{source.name}</p>
        <p className="text-[11px] text-ink-faint">
          {source.kind_label} · {source.item_count} 条 · {label}
          {source.last_run_at ? ` · ${relativeTime(source.last_run_at)}` : ""}
        </p>
        {source.last_error ? (
          <p className="mt-0.5 truncate text-[11px] text-danger/80" title={source.last_error}>
            {source.last_error}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function AdminPanel({
  feed,
  onUpdated,
}: {
  feed: CampusFeed;
  onUpdated: () => Promise<void>;
}) {
  const toast = useApp((s) => s.toast);
  const [interval, setIntervalValue] = useState(String(feed.config.interval_minutes));
  const [maxDetail, setMaxDetail] = useState(String(feed.config.max_detail_per_run));
  const [busy, setBusy] = useState<"crawl" | "save" | "seed" | null>(null);
  const [runs, setRuns] = useState<CampusRun[]>(feed.runs);

  useEffect(() => {
    setIntervalValue(String(feed.config.interval_minutes));
    setMaxDetail(String(feed.config.max_detail_per_run));
    setRuns(feed.runs);
  }, [feed.config.interval_minutes, feed.config.max_detail_per_run, feed.runs]);

  const save = async () => {
    setBusy("save");
    try {
      await api.campus.updateConfig({
        interval_minutes: Number(interval) || 0,
        max_detail_per_run: Number(maxDetail) || 0,
      });
      await onUpdated();
      toast({ title: "抓取设置已保存", tone: "success" });
    } catch (error) {
      toast({ title: "保存失败", description: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  const crawl = async () => {
    setBusy("crawl");
    try {
      const result = await api.campus.crawl();
      toast({
        title: result.message,
        description: result.failed ? "失败的源会在下次自动重试" : undefined,
        tone: result.failed ? "error" : "success",
      });
      await onUpdated();
    } catch (error) {
      toast({ title: "更新失败", description: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  const seedDemo = async () => {
    setBusy("seed");
    try {
      const result = await api.campus.seedDemo();
      toast({ title: result.message, tone: "success" });
      await onUpdated();
    } catch (error) {
      toast({ title: "导入失败", description: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card p-5">
      <div className="flex items-center gap-2">
        <h2 className="font-display text-[15px] font-semibold text-ink">抓取设置</h2>
        <Badge tone="outline">管理员</Badge>
      </div>
      <p className="mt-1 text-[12px] leading-relaxed text-ink-faint">
        抓取结果会持久化保存并去重，同一篇通知只入库一次。
      </p>

      <div className="mt-4 space-y-3">
        <Field label="自动更新间隔">
          <select
            value={interval}
            onChange={(event) => setIntervalValue(event.target.value)}
            className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-[13px] text-ink focus:border-brand/60 focus:outline-none"
          >
            {INTERVAL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
            {INTERVAL_OPTIONS.every((option) => option.value !== interval) ? (
              <option value={interval}>自定义（{interval} 分钟）</option>
            ) : null}
          </select>
        </Field>

        <Field label="每次最多抓多少篇详情" hint="数值越大越全，但对方站点压力也越大">
          <Input
            type="number"
            min={0}
            max={200}
            value={maxDetail}
            onChange={(event) => setMaxDetail(event.target.value)}
          />
        </Field>

        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="primary" loading={busy === "save"} onClick={save}>
            保存设置
          </Button>
          <Button size="sm" variant="secondary" loading={busy === "crawl"} onClick={crawl}>
            <Icon name="refresh-cw" className="h-3.5 w-3.5" />
            立即更新
          </Button>
          <Button size="sm" variant="ghost" loading={busy === "seed"} onClick={seedDemo}>
            导入示例数据
          </Button>
        </div>

        {feed.demo_count > 0 ? (
          <p className="rounded-lg bg-amber/10 px-2.5 py-1.5 text-[11.5px] leading-relaxed text-amber">
            当前有 {feed.demo_count} 条示例数据（带「示例」标记），仅供演示，可随时清除。
          </p>
        ) : null}
      </div>

      {runs.length ? (
        <div className="mt-4 border-t border-line/70 pt-3">
          <p className="mb-1 text-[11px] uppercase tracking-[0.14em] text-ink-faint">最近抓取</p>
          <ul className="space-y-1">
            {runs.slice(0, 4).map((run) => (
              <li key={run.id} className="flex items-center gap-2 text-[11.5px] text-ink-soft">
                <span
                  className={cn(
                    "inline-block h-1.5 w-1.5 rounded-full",
                    run.status === "ok" ? "bg-jade" : run.status === "error" ? "bg-danger" : "bg-ink-faint",
                  )}
                />
                <span className="truncate">{run.source_name ?? run.source_id}</span>
                <span className="ml-auto shrink-0 text-ink-faint">
                  +{run.created} · {relativeTime(run.started_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

export function CampusPage() {
  const toast = useApp((s) => s.toast);
  const profile = useApp((s) => s.profile);
  const saveProfile = useApp((s) => s.saveProfile);

  const [feed, setFeed] = useState<CampusFeed | null>(null);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("all");
  const [sort, setSort] = useState<"match" | "new">("match");
  const [profileOpen, setProfileOpen] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft>(() => emptyDraft(profile));
  const [savingProfile, setSavingProfile] = useState(false);

  const load = useCallback(
    async (next?: { category?: string; sort?: "match" | "new" }) => {
      try {
        const data = await api.campus.feed({
          category: next?.category ?? category,
          sort: next?.sort ?? sort,
          limit: 40,
        });
        setFeed(data);
      } catch (error) {
        toast({ title: "加载失败", description: String(error), tone: "error" });
      } finally {
        setLoading(false);
      }
    },
    [category, sort, toast],
  );

  useEffect(() => {
    load();
    // 只在首次挂载与筛选变化时拉取
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, sort]);

  useEffect(() => {
    setDraft(emptyDraft(profile));
  }, [profile]);

  const openProfile = () => {
    setDraft(emptyDraft(profile));
    setProfileOpen(true);
  };

  const submitProfile = async () => {
    setSavingProfile(true);
    try {
      await saveProfile(draftToInput(draft));
      setProfileOpen(false);
      toast({ title: "资料已保存，推荐已按新资料刷新", tone: "success" });
      await load();
    } catch (error) {
      toast({ title: "保存失败", description: String(error), tone: "error" });
    } finally {
      setSavingProfile(false);
    }
  };

  const school = feed?.school || profile?.school || "郑州大学";
  const completeness = feed?.profile_completeness ?? profile?.completeness ?? 0;
  const items = feed?.items ?? [];

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="校园雷达"
        title={`${school} · 与你有关的通知`}
        description="自动聚合教务处、信息公开与通知公告，按你的年级专业兴趣排序。抓取结果会存库去重，同一篇通知只出现一次。"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={openProfile}>
              <Icon name="user-round" className="h-3.5 w-3.5" />
              我的资料
            </Button>
            <Button variant="secondary" size="sm" loading={loading} onClick={() => load()}>
              <Icon name="refresh-cw" className="h-3.5 w-3.5" />
              刷新
            </Button>
          </div>
        }
      />

      {completeness < 60 || feed?.school_fallback ? (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-2xl border border-amber/30 bg-amber/8 px-4 py-3">
          <Icon name="info" className="h-4 w-4 shrink-0 text-amber" />
          <div className="min-w-0 flex-1">
            <p className="text-[12.5px] font-medium text-ink">
              {feed?.school_fallback ? "还没填学校，先按郑州大学展示" : "资料还没填全，推荐会比较粗"}
            </p>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink-faint">
              补上学校、年级、专业和兴趣，才能判断「这条通知是不是跟你有关」。
            </p>
            <div className="mt-2 max-w-xs">
              <Progress value={completeness} />
            </div>
          </div>
          <Button size="sm" variant="primary" onClick={openProfile}>
            去完善
          </Button>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <AskPanel school={school} onNeedProfile={openProfile} />

          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <Segmented
                value={category}
                onChange={(value) => setCategory(value)}
                options={CATEGORY_OPTIONS}
              />
              <button
                onClick={() => setSort(sort === "match" ? "new" : "match")}
                className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-[11.5px] text-ink-soft transition-colors hover:border-brand/40 hover:text-brand-strong"
              >
                <Icon name={sort === "match" ? "sparkles" : "clock"} className="h-3.5 w-3.5" />
                {sort === "match" ? "按匹配度" : "按时间"}
              </button>
            </div>

            {loading ? (
              <div className="space-y-3">
                {[0, 1, 2].map((index) => (
                  <div key={index} className="card shimmer h-24" />
                ))}
              </div>
            ) : items.length === 0 ? (
              <EmptyState
                icon="radar"
                title="还没有抓到通知"
                description={
                  feed?.config.can_manage
                    ? "在右侧「抓取设置」里点「立即更新」，或者先导入示例数据看看效果。"
                    : "管理员还没有更新过数据，稍后再来看看。"
                }
              />
            ) : (
              <div className="stagger space-y-3">
                {items.map((item) => (
                  <ItemCard key={item.id} item={item} />
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="space-y-5">
          {feed && feed.config.can_manage ? (
            <AdminPanel feed={feed} onUpdated={() => load()} />
          ) : null}

          <section className="card p-5">
            <h2 className="font-display text-[15px] font-semibold text-ink">抓取源</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink-faint">
              失败的源会记录原因并自动重试，不会影响其他源。
            </p>
            <div className="mt-2 divide-y divide-line/60">
              {(feed?.sources ?? []).map((source) => (
                <SourceRow key={source.id} source={source} />
              ))}
              {!feed?.sources.length ? (
                <p className="py-3 text-[12px] text-ink-faint">还没有配置抓取源。</p>
              ) : null}
            </div>
          </section>

          <section className="card p-5">
            <h2 className="font-display text-[15px] font-semibold text-ink">怎么用</h2>
            <ol className="mt-2 space-y-2 text-[12.5px] leading-relaxed text-ink-soft">
              <li className="flex gap-2">
                <span className="text-ink-faint">1</span>
                填好学校与年级，雷达才知道该抓哪所学校、哪些通知与你有关。
              </li>
              <li className="flex gap-2">
                <span className="text-ink-faint">2</span>
                管理员设置抓取间隔，到点自动更新；也可以随时手动更新。
              </li>
              <li className="flex gap-2">
                <span className="text-ink-faint">3</span>
                直接提问，例如「这周有什么比赛」「四六级什么时候截止」。
              </li>
            </ol>
          </section>
        </div>
      </div>

      <Modal
        open={profileOpen}
        onOpenChange={setProfileOpen}
        title="我的资料"
        description="这些信息决定推荐口径，改动后信息流会立即重新排序。"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setProfileOpen(false)}>
              取消
            </Button>
            <Button variant="primary" loading={savingProfile} onClick={submitProfile}>
              保存
            </Button>
          </>
        }
      >
        <ProfileForm draft={draft} onChange={setDraft} compact />
        <p className="text-[11.5px] leading-relaxed text-ink-faint">
          不填班级也不影响使用；「近期目标」会影响哪类通知优先出现。
        </p>
        <div className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-2">
          <span className="text-[12px] text-ink-soft">当前完整度</span>
          <span className="text-[12px] tabular-nums text-ink-faint">{profile?.completeness ?? 0}%</span>
        </div>
      </Modal>
    </div>
  );
}
