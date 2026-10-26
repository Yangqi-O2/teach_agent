import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Icon } from "../components/Icon";
import { StatCard } from "../components/StatCard";
import { Badge, Button, Dot, EmptyState, SectionHeading } from "../components/ui/primitives";
import { api, type EventItem } from "../lib/api";
import { capabilityStatusMeta, cn, maskPath, relativeTime } from "../lib/utils";
import { useApp } from "../store/app";

// 只放「确实还没做」的条目。已上线的能力由服务端 manifest 动态渲染，
// 不要在这里重复——否则上线后会长期挂着「规划中」，与实际状态不符。
const ROADMAP = [
  { icon: "radar", name: "校园雷达", desc: "订阅教务处通知，自动抽取竞赛与截止日期" },
  { icon: "brain", name: "联想记忆", desc: "把知识点长在你的兴趣上，按遗忘曲线复习" },
  { icon: "pencil-line", name: "练习场", desc: "自动出题、批改，错题回流成记忆卡" },
  { icon: "layout-dashboard", name: "学习台", desc: "今日待办、掌握度热力图与学习报告" },
];

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

const STEPS = [
  { title: "配置模型", desc: "填一个 OpenAI 兼容的 Base URL、模型名和 API Key，本机加密保存。", to: "/settings?tab=models", icon: "cpu" },
  { title: "上传一本教材", desc: "PDF / EPUB / Word / TXT 都行，扫描件会自动 OCR 成可检索文本。", to: "/cap/library", icon: "library" },
  { title: "就着教材提问", desc: "选定一本教材，AI 只用它的内容作答，每条结论都带页码出处。", to: "/cap/library", icon: "message-square" },
];

function HeroChip({ icon, label, desc, planned }: { icon: string; label: string; desc: string; planned?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 rounded-2xl border border-line/80 bg-surface/85 px-3 py-2 shadow-soft backdrop-blur">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-soft text-brand-strong">
        <Icon name={icon} className="h-4 w-4" />
      </span>
      <div className="pr-1">
        <p className="text-[12.5px] font-medium leading-tight text-ink">
          {label}
          {planned ? (
            <span className="ml-1.5 rounded-full border border-line px-1 py-px text-[9.5px] font-normal text-ink-faint">
              规划中
            </span>
          ) : null}
        </p>
        <p className="mt-0.5 text-[10.5px] leading-tight text-ink-faint">{desc}</p>
      </div>
    </div>
  );
}

export function Home() {
  const navigate = useNavigate();
  const info = useApp((s) => s.info);
  const user = useApp((s) => s.user);
  const capabilities = useApp((s) => s.capabilities);
  const providers = useApp((s) => s.providers);
  const [events, setEvents] = useState<EventItem[]>([]);

  const enabledCaps = capabilities.filter((c) => c.enabled);
  const defaultProvider = providers.find((p) => p.is_default) ?? providers[0];

  useEffect(() => {
    api
      .events(6)
      .then(setEvents)
      .catch(() => setEvents([]));
  }, []);

  return (
    <div className="page-enter space-y-10">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-[1.6rem] border border-line bg-surface p-6 shadow-soft md:p-10">
        <div className="pointer-events-none absolute inset-0 opacity-80 bg-[radial-gradient(120%_140%_at_0%_0%,var(--color-brand-soft),transparent_52%),radial-gradient(80%_110%_at_100%_100%,color-mix(in_oklab,var(--color-jade)_8%,transparent),transparent_62%)]" />
        <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-[46%] lg:block">
          <svg
            className="absolute right-[-70px] top-1/2 h-[430px] w-[430px] -translate-y-1/2 text-brand/20"
            viewBox="0 0 200 200"
            fill="none"
            stroke="currentColor"
            aria-hidden
          >
            {[40, 64, 88, 112, 136].map((r, i) => (
              <circle key={r} cx="100" cy="100" r={r} strokeWidth={i === 0 ? 1.4 : 1} opacity={0.85 - i * 0.13} />
            ))}
            <circle cx="100" cy="100" r="4" fill="currentColor" stroke="none" opacity="0.5" />
          </svg>

          <div className="absolute right-[20%] top-[22%] animate-float" style={{ animationDelay: "0s" }}>
            <HeroChip icon="library" label="教材库" desc="PDF · EPUB · 扫描件 OCR" />
          </div>
          <div className="absolute right-[6%] top-[44%] animate-float" style={{ animationDelay: "1.2s", animationDuration: "8s" }}>
            <HeroChip icon="radar" label="校园雷达" desc="竞赛 · 通知 · 截止提醒" planned />
          </div>
          <div className="absolute right-[26%] top-[66%] animate-float" style={{ animationDelay: "2.4s", animationDuration: "9s" }}>
            <HeroChip icon="brain" label="联想记忆" desc="长在你的兴趣上" planned />
          </div>
        </div>

        <svg
          className="pointer-events-none absolute inset-x-0 bottom-0 h-16 w-full text-brand/[0.05]"
          viewBox="0 0 1200 80"
          preserveAspectRatio="none"
          fill="currentColor"
          aria-hidden
        >
          <path d="M0 44c150 34 300-22 450 2s300 30 450 2 200-18 300-24v56H0z" />
        </svg>

        <div className="relative z-10 max-w-2xl">
          <span className="inline-flex items-center gap-2 rounded-full border border-brand/15 bg-surface/70 px-3 py-1 text-[11.5px] font-medium text-brand-strong backdrop-blur">
            <Dot />
            本地优先 · API Key 自配
          </span>
          <p className="mt-5 text-[12.5px] font-medium tracking-wide text-brand/90">
            {greeting()}，{user?.display_name ?? "同学"}
          </p>
          <h1 className="mt-1.5 font-display text-[34px] font-semibold leading-[1.18] tracking-tight text-ink md:text-[44px]">
            把知识，收进一片湖里。
          </h1>
          <p className="mt-4 max-w-xl text-[14.5px] leading-relaxed text-ink-soft">
            教材库、情景英语、群聊简报、速记已经上线；把教材传进来，就能就着原文提问，答案带页码出处。
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Button
              size="lg"
              variant="primary"
              onClick={() => navigate(defaultProvider ? "/cap/library" : "/settings?tab=models")}
            >
              {defaultProvider ? "进入教材库" : "配置模型"}
              <Icon name="arrow-up-right" className="h-4 w-4" />
            </Button>
            <Button size="lg" variant="secondary" onClick={() => navigate("/settings?tab=capabilities")}>
              管理能力
            </Button>
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12px] text-ink-faint">
            <span className="inline-flex items-center gap-1.5">
              <Icon name="shield-check" className="h-3.5 w-3.5" /> 数据不出本机
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Icon name="sparkles" className="h-3.5 w-3.5" /> 能力可插拔
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Icon name="server" className="h-3.5 w-3.5" /> OpenAI 兼容
            </span>
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="stagger grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon="cpu"
          label="模型供应商"
          value={providers.length ? `${providers.length} 个` : "未配置"}
          hint={defaultProvider ? `默认：${defaultProvider.name}` : "去设置里添加一个"}
          tone={providers.length ? "brand" : "amber"}
        />
        <StatCard
          icon="sparkles"
          label="已接入能力"
          value={`${enabledCaps.length} 个`}
          hint={`共 ${capabilities.length} 个已注册`}
          tone="jade"
        />
        <StatCard icon="wand-2" label="Agent 工具" value={`${info?.tools ?? 0} 个`} hint="自动进入工具表" tone="neutral" />
        <StatCard
          icon="folder-open"
          label="数据目录"
          value={maskPath(info?.data_dir, 22)}
          hint="单文件 SQLite，可整体备份"
          tone="neutral"
        />
      </section>

      {/* Capabilities */}
      <section id="capabilities">
        <SectionHeading
          title="已接入能力"
          description="每个能力自带导航、路由、设置与 Agent 工具；禁用后从侧栏消失。"
          action={
            <Button variant="ghost" size="sm" onClick={() => navigate("/settings?tab=capabilities")}>
              管理
              <Icon name="chevron-right" className="h-3.5 w-3.5" />
            </Button>
          }
        />
        {capabilities.length === 0 ? (
          <EmptyState
            icon="sparkles"
            title="还没有注册任何能力"
            description="用 python -m app.cli new-capability 生成一个，或检查后端启动日志。"
          />
        ) : (
          <div className="stagger grid gap-3 md:grid-cols-2">
            {capabilities.map((cap) => (
              <Link
                key={cap.id}
                to={cap.nav?.path && cap.enabled ? cap.nav.path : "/settings?tab=capabilities"}
                className={cn(
                  "card card-hover group flex items-start gap-4 p-5",
                  !cap.enabled && "opacity-60",
                )}
              >
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                  <Icon name={cap.icon} className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-display text-[16px] font-semibold text-ink">{cap.name}</h3>
                    <Badge tone={capabilityStatusMeta(cap.status).tone}>
                      {capabilityStatusMeta(cap.status).label}
                    </Badge>
                    <Badge tone={cap.enabled ? "brand" : "neutral"}>
                      {cap.enabled ? "已启用" : "已禁用"}
                    </Badge>
                    {cap.has_tools ? <Badge tone="outline">Agent 可调用</Badge> : null}
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-ink-soft">{cap.description}</p>
                  <p className="mt-2 text-[11.5px] text-ink-faint">v{cap.version}</p>
                </div>
                <Icon
                  name="chevron-right"
                  className="mt-1 h-4 w-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5"
                />
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Roadmap */}
      <section>
        <SectionHeading
          title="接下来会接进来的能力"
          description="框架已经为它们留好了位置：加一个目录、写一份 manifest，导航和工具自动出现。"
        />
        <div className="stagger grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {ROADMAP.map((item) => (
            <div key={item.name} className="card-quiet group flex items-start gap-3.5 p-4 transition-colors hover:border-brand/25">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface text-ink-faint">
                <Icon name={item.icon} className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="text-[13.5px] font-medium text-ink">{item.name}</h3>
                  <span className="rounded-full border border-line px-1.5 py-0.5 text-[10px] text-ink-faint">规划中</span>
                </div>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-faint">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Steps + activity */}
      <section className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div>
          <SectionHeading title="从这里开始" description="三步把框架用起来。" />
          <div className="card divide-y divide-line/70">
            {STEPS.map((step, index) => (
              <button
                key={step.title}
                onClick={() => navigate(step.to)}
                className="group flex w-full items-start gap-4 p-4 text-left transition-colors hover:bg-surface-2/60"
              >
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-surface-2 text-[12px] font-semibold text-ink-soft">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] font-medium text-ink">{step.title}</p>
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-faint">{step.desc}</p>
                </div>
                <Icon name="chevron-right" className="mt-1 h-4 w-4 text-ink-faint transition-transform group-hover:translate-x-0.5" />
              </button>
            ))}
          </div>
        </div>

        <div>
          <SectionHeading title="最近动态" description="来自本机事件日志。" />
          <div className="card min-h-[220px] p-2">
            {events.length === 0 ? (
              <div className="flex h-[200px] flex-col items-center justify-center text-center">
                <Icon name="clock" className="mb-2 h-5 w-5 text-ink-faint" />
                <p className="text-[12.5px] text-ink-faint">还没有记录</p>
                <p className="mt-1 text-[11.5px] text-ink-faint/80">添加模型、保存速记后，这里会有动静。</p>
              </div>
            ) : (
              <ul className="space-y-0.5 p-1">
                {events.map((event) => (
                  <li key={event.id} className="flex items-start gap-3 rounded-lg px-2.5 py-2">
                    <span className="mt-1.5">
                      <Dot tone={event.kind === "provider" ? "brand" : event.kind === "job" ? "amber" : "jade"} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12.5px] text-ink">{event.message}</p>
                      <p className="text-[11px] text-ink-faint">{relativeTime(event.created_at)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
