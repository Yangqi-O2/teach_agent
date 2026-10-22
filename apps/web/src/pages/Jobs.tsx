import { useCallback, useEffect, useMemo, useState } from "react";

import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Badge, Button, EmptyState, Progress, Segmented } from "../components/ui/primitives";
import { api, type Job } from "../lib/api";
import { relativeTime } from "../lib/utils";
import { useApp } from "../store/app";

const STATUS_META: Record<string, { label: string; tone: "neutral" | "brand" | "jade" | "danger" | "amber" }> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "进行中", tone: "brand" },
  done: { label: "已完成", tone: "jade" },
  error: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "neutral" },
};

const TYPE_ICON: Record<string, string> = {
  ingest: "library",
  parse: "library",
  embed: "database",
  crawl: "radar",
  mnemonic: "brain",
  quiz: "pencil-line",
};

type Filter = "all" | "active" | "done" | "error";

export function Jobs() {
  const toast = useApp((s) => s.toast);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    try {
      setJobs(await api.jobs.list());
    } catch {
      /* SSE / 轮询失败时保持旧数据 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    let source: EventSource | null = null;
    try {
      source = new EventSource(api.jobs.streamUrl);
      source.addEventListener("jobs", () => load());
    } catch {
      source = null;
    }
    const timer = window.setInterval(load, 10_000);
    return () => {
      source?.close();
      window.clearInterval(timer);
    };
  }, [load]);

  const filtered = useMemo(() => {
    if (filter === "active") return jobs.filter((job) => job.status === "queued" || job.status === "running");
    if (filter === "done") return jobs.filter((job) => job.status === "done");
    if (filter === "error") return jobs.filter((job) => job.status === "error");
    return jobs;
  }, [jobs, filter]);

  const cancel = async (job: Job) => {
    try {
      await api.jobs.cancel(job.id);
      await load();
      toast({ title: "已请求取消", tone: "success" });
    } catch (error) {
      toast({ title: "取消失败", description: String(error), tone: "error" });
    }
  };

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="任务中心"
        title="后台任务"
        description="解析教材、抓取通知、批量生成记忆卡等耗时工作都会变成任务，进度实时更新，可以随时取消。"
        actions={
          <Button variant="ghost" size="sm" onClick={load}>
            <Icon name="refresh-cw" className="h-3.5 w-3.5" />
            刷新
          </Button>
        }
      />

      <div className="mb-5">
        <Segmented<Filter>
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "全部" },
            { value: "active", label: "进行中" },
            { value: "done", label: "已完成" },
            { value: "error", label: "失败" },
          ]}
        />
      </div>

      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card shimmer h-24" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="list-checks"
          title="还没有任务"
          description="等教材库、校园雷达这些能力接进来以后，解析与抓取任务会出现在这里；现在它是空的也很正常。"
        />
      ) : (
        <div className="stagger space-y-3">
          {filtered.map((job) => {
            const meta = STATUS_META[job.status] ?? STATUS_META.queued;
            const active = job.status === "running" || job.status === "queued";
            return (
              <article key={job.id} className="card p-5">
                <div className="flex items-start gap-4">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-ink-soft">
                    <Icon name={TYPE_ICON[job.type] ?? "list-checks"} className="h-[18px] w-[18px]" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-[14px] font-medium text-ink">{job.title}</h3>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                      <span className="font-mono text-[11px] text-ink-faint">{job.type}</span>
                      <span className="ml-auto text-[11.5px] text-ink-faint">{relativeTime(job.created_at)}</span>
                    </div>
                    {job.message ? <p className="mt-1 text-[12.5px] text-ink-soft">{job.message}</p> : null}
                    {active ? <Progress value={job.progress} className="mt-3" /> : null}
                    {job.error ? (
                      <p className="mt-2 rounded-lg bg-danger/10 px-2.5 py-1.5 font-mono text-[11.5px] text-danger">
                        {job.error}
                      </p>
                    ) : null}
                  </div>
                  {active ? (
                    <Button variant="ghost" size="sm" onClick={() => cancel(job)}>
                      <Icon name="square" className="h-3 w-3" />
                      取消
                    </Button>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
