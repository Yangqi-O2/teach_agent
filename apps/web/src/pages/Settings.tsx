import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { CapabilityPanel } from "../components/CapabilityPanel";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { ProviderPanel } from "../components/ProviderPanel";
import { Badge, Button } from "../components/ui/primitives";
import { cn, shortenPath } from "../lib/utils";
import { useApp, type Theme } from "../store/app";

const TABS = [
  { id: "models", label: "模型接入", icon: "cpu" },
  { id: "capabilities", label: "能力", icon: "sparkles" },
  { id: "appearance", label: "外观", icon: "palette" },
  { id: "about", label: "关于", icon: "info" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const THEME_OPTIONS: { value: Theme; label: string; desc: string; preview: "light" | "dark" | "system" }[] = [
  { value: "light", label: "浅色", desc: "米白纸感，适合白天与打印", preview: "light" },
  { value: "dark", label: "深色", desc: "墨色湖面，夜里不刺眼", preview: "dark" },
  { value: "system", label: "跟随系统", desc: "随系统外观自动切换", preview: "system" },
];

function ThemePreview({ mode }: { mode: "light" | "dark" | "system" }) {
  const light = (
    <div className="flex h-full gap-1.5 rounded-lg bg-[#f4f1e8] p-1.5">
      <div className="w-1/4 rounded bg-[#fffdf7] shadow-sm" />
      <div className="flex-1 space-y-1">
        <div className="h-2 w-2/3 rounded-full bg-[#e4ddce]" />
        <div className="h-2 w-1/2 rounded-full bg-[#14687b]/40" />
        <div className="h-6 rounded bg-[#fffdf7] shadow-sm" />
      </div>
    </div>
  );
  const dark = (
    <div className="flex h-full gap-1.5 rounded-lg bg-[#0a1316] p-1.5">
      <div className="w-1/4 rounded bg-[#101d21]" />
      <div className="flex-1 space-y-1">
        <div className="h-2 w-2/3 rounded-full bg-[#223438]" />
        <div className="h-2 w-1/2 rounded-full bg-[#5cb9ca]/50" />
        <div className="h-6 rounded bg-[#15252b]" />
      </div>
    </div>
  );
  if (mode === "system") {
    return (
      <div className="relative h-full overflow-hidden rounded-lg">
        <div className="absolute inset-0">{light}</div>
        <div className="absolute inset-y-0 right-0 w-1/2 overflow-hidden border-l border-line/60">{dark}</div>
      </div>
    );
  }
  return <div className="h-full overflow-hidden rounded-lg">{mode === "dark" ? dark : light}</div>;
}

function AppearanceTab() {
  const theme = useApp((s) => s.theme);
  const setTheme = useApp((s) => s.setTheme);
  const info = useApp((s) => s.info);
  return (
    <div className="space-y-8">
      <div>
        <h2 className="font-display text-[17px] font-semibold text-ink">主题</h2>
        <p className="mt-1 text-[12.5px] text-ink-faint">选择你喜欢的湖面颜色，随时可以换。</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {THEME_OPTIONS.map((option) => (
            <button
              key={option.value}
              onClick={() => setTheme(option.value)}
              className={cn(
                "card p-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lift",
                theme === option.value && "ring-2 ring-brand/50",
              )}
            >
              <div className="h-20">
                <ThemePreview mode={option.preview} />
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-[13px] font-medium text-ink">{option.label}</span>
                {theme === option.value ? <Icon name="check" className="h-4 w-4 text-brand" /> : null}
              </div>
              <p className="mt-0.5 text-[11.5px] text-ink-faint">{option.desc}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="card p-5">
        <h3 className="text-[14px] font-semibold text-ink">数据与隐私</h3>
        <div className="mt-3 space-y-2 text-[12.5px] leading-relaxed text-ink-soft">
          <p className="flex items-center gap-2">
            <Icon name="shield-check" className="h-4 w-4 text-jade" />
            所有数据保存在本机数据库，不上传任何第三方服务。
          </p>
          <p className="flex items-center gap-2">
            <Icon name="key-round" className="h-4 w-4 text-brand" />
            API Key 使用 Fernet 加密后落库，界面只显示掩码。
          </p>
          <p className="flex items-center gap-2 break-all font-mono text-[11.5px] text-ink-faint">
            <Icon name="folder-open" className="h-4 w-4 shrink-0" />
            {info?.data_dir ?? "—"}
          </p>
        </div>
      </div>
    </div>
  );
}

function AboutTab() {
  const info = useApp((s) => s.info);
  const toast = useApp((s) => s.toast);
  const [copied, setCopied] = useState(false);
  const command = "python -m app.cli new-capability my-feature --name 我的能力";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
      toast({ title: "命令已复制", tone: "success" });
    } catch {
      toast({ title: "复制失败，请手动选择", tone: "error" });
    }
  };

  const rows = [
    { label: "版本", value: `v${info?.app.version ?? "0.1.0"}` },
    { label: "技术栈", value: "React 19 · FastAPI · SQLite" },
    { label: "能力", value: `${info?.capabilities ?? 0} 个已注册 · ${info?.tools ?? 0} 个工具` },
    { label: "数据目录", value: shortenPath(info?.data_dir ?? "—", 34) },
  ];

  return (
    <div className="space-y-6">
      <div className="card overflow-hidden">
        <div className="relative border-b border-line/70 bg-[radial-gradient(120%_140%_at_0%_0%,var(--color-brand-soft),transparent_70%)] p-6">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand to-jade text-canvas">
              <svg viewBox="0 0 32 32" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
                <path d="M3.5 18.5c3 0 3-2.4 6.2-2.4s3.2 2.4 6.2 2.4 3.2-2.4 6.2-2.4 3.2 2.4 6.2 2.4" />
                <path d="M3.5 24.5c3 0 3-2.4 6.2-2.4s3.2 2.4 6.2 2.4 3.2-2.4 6.2-2.4 3.2 2.4 6.2 2.4" opacity="0.55" />
                <circle cx="24.5" cy="9.5" r="2.6" fill="currentColor" stroke="none" />
              </svg>
            </div>
            <div>
              <h2 className="font-display text-xl font-semibold tracking-wide text-ink">天健湖</h2>
              <p className="mt-0.5 text-[12.5px] text-ink-faint">Tianjian Lake · 一个可以自己长功能的学习助手</p>
            </div>
            <Badge tone="jade" className="ml-auto">
              框架版 v{info?.app.version ?? "0.1.0"}
            </Badge>
          </div>
        </div>
        <div className="divide-y divide-line/60">
          {rows.map((row) => (
            <div key={row.label} className="flex items-center justify-between gap-4 px-5 py-3">
              <span className="text-[12.5px] text-ink-faint">{row.label}</span>
              <span className="truncate font-mono text-[12px] text-ink">{row.value}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card p-5">
        <h3 className="text-[14px] font-semibold text-ink">新增一个能力</h3>
        <p className="mt-1 text-[12.5px] leading-relaxed text-ink-faint">
          在 <span className="font-mono">apps/server</span> 目录执行下面的命令，会同时生成后端能力目录和前端页面目录，重启后自动出现在侧栏与工具列表。
        </p>
        <div className="mt-3 flex items-center gap-2 rounded-xl bg-surface-2 p-2 pl-3">
          <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-[12px] text-ink-soft">{command}</code>
          <Button size="sm" variant="secondary" onClick={copy}>
            {copied ? "已复制" : "复制"}
          </Button>
        </div>
      </div>

      <div className="card p-5">
        <h3 className="text-[14px] font-semibold text-ink">快捷键</h3>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {[
            { keys: "⌘ K", desc: "打开命令面板" },
            { keys: "Esc", desc: "关闭浮层" },
            { keys: "↑ ↓", desc: "在命令面板中选择" },
            { keys: "⌘ ↵", desc: "速记里保存" },
          ].map((item) => (
            <div key={item.keys} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2">
              <span className="text-[12.5px] text-ink-soft">{item.desc}</span>
              <span className="kbd">{item.keys}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function Settings() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabId) || "models";

  const change = (next: TabId) => {
    const updated = new URLSearchParams(params);
    updated.set("tab", next);
    setParams(updated, { replace: true });
  };

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="设置"
        title="把湖面调成你想要的样子"
        description="模型接入、能力开关、外观与数据，都在这里。"
      />

      <div className="mb-6 flex gap-1 overflow-x-auto border-b border-line/70 pb-px">
        {TABS.map((item) => (
          <button
            key={item.id}
            onClick={() => change(item.id)}
            className={cn(
              "relative flex shrink-0 items-center gap-2 rounded-t-lg px-4 py-2.5 text-[13px] font-medium transition-colors",
              tab === item.id ? "text-brand-strong" : "text-ink-faint hover:text-ink",
            )}
          >
            <Icon name={item.icon} className="h-4 w-4" />
            {item.label}
            {tab === item.id ? <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand" /> : null}
          </button>
        ))}
      </div>

      <div className="page-enter">
        {tab === "models" ? <ProviderPanel /> : null}
        {tab === "capabilities" ? <CapabilityPanel /> : null}
        {tab === "appearance" ? <AppearanceTab /> : null}
        {tab === "about" ? <AboutTab /> : null}
      </div>
    </div>
  );
}
