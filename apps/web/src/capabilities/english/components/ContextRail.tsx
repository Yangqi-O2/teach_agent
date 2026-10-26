import type { ReactNode } from "react";

import type { EnglishHealth, EnglishTopic, EnglishVocabItem } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { cn } from "../../../lib/utils";

function RailSection({ title, icon, children, action }: { title: string; icon: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-card border border-line bg-surface p-3.5">
      <div className="mb-2 flex items-center gap-1.5">
        <Icon name={icon} className="h-3.5 w-3.5 text-brand" />
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">{title}</p>
        {action ? <span className="ml-auto">{action}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function ContextRail({
  topics,
  topicTitle,
  dueCount,
  dueWords,
  health,
  onOpenVocab,
  onOpenErrors,
  onOpenDocuments,
  onOpenStats,
  onOpenContract,
}: {
  topics: EnglishTopic[];
  topicTitle: string;
  dueCount: number;
  dueWords: EnglishVocabItem[];
  health: EnglishHealth | null;
  onOpenVocab: () => void;
  onOpenErrors: () => void;
  onOpenDocuments: () => void;
  onOpenStats: () => void;
  onOpenContract: () => void;
}) {
  const unused = topics.filter((topic) => !topic.used_count);
  const quickActions = [
    { label: "生词本", icon: "book-open", onClick: onOpenVocab, badge: dueCount ? String(dueCount) : null },
    { label: "错误档案", icon: "list-checks", onClick: onOpenErrors },
    { label: "资料库", icon: "file-text", onClick: onOpenDocuments },
    { label: "成本看板", icon: "chart-column", onClick: onOpenStats },
    { label: "偏好", icon: "type", onClick: onOpenContract },
  ];

  return (
    <div className="space-y-3">
      <RailSection
        title="话题池"
        icon="target"
        action={<span className="text-[11px] text-ink-faint">{unused.length} 未用</span>}
      >
        {topics.length === 0 ? (
          <p className="text-[12px] text-ink-faint">选择情景后显示话题。</p>
        ) : (
          <ul className="space-y-1.5">
            {topics.slice(0, 6).map((topic) => {
              const active = topicTitle === topic.title;
              return (
                <li key={topic.id} className="flex items-start gap-1.5 text-[12px] leading-snug">
                  <span
                    className={cn(
                      "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                      active ? "bg-brand" : topic.used_count ? "bg-ink-faint/40" : "bg-jade",
                    )}
                  />
                  <span className={cn("min-w-0 flex-1", active ? "font-medium text-brand-strong" : "text-ink-soft")}>
                    {topic.title}
                    {topic.target_tenses?.length ? (
                      <span className="block text-[10.5px] text-ink-faint">
                        {topic.target_tenses.join(" / ")}
                      </span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </RailSection>

      <RailSection
        title="到期复习"
        icon="bookmark"
        action={
          <button type="button" onClick={onOpenVocab} className="text-[11px] text-brand hover:underline">
            打开
          </button>
        }
      >
        {dueCount > 0 ? (
          <>
            <p className="text-[12px] text-ink-soft">
              今天有 <span className="font-semibold text-danger">{dueCount}</span> 个词到期
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {dueWords.map((word) => (
                <span
                  key={word.lemma}
                  className="rounded-full border border-dashed border-line px-2 py-0.5 text-[11.5px] text-ink-soft"
                  title={word.glossZh ?? undefined}
                >
                  {word.lemma}
                </span>
              ))}
            </div>
          </>
        ) : (
          <p className="text-[12px] text-ink-faint">今天没有到期生词，聊几句攒点新词。</p>
        )}
      </RailSection>

      <RailSection title="学习档案" icon="layout-dashboard">
        <div className="grid grid-cols-2 gap-1.5">
          {quickActions.map((action) => (
            <button
              key={action.label}
              type="button"
              onClick={action.onClick}
              className="flex items-center gap-1.5 rounded-lg border border-line bg-surface-2/60 px-2 py-2 text-left text-[11.5px] text-ink-soft transition-colors hover:border-brand/30 hover:text-ink"
            >
              <Icon name={action.icon} className="h-3.5 w-3.5 shrink-0 text-brand" />
              <span className="min-w-0 truncate">{action.label}</span>
              {action.badge ? (
                <span className="ml-auto rounded-full bg-danger/12 px-1.5 text-[10px] text-danger">
                  {action.badge}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </RailSection>

      <RailSection title="模型与健康" icon="cpu">
        {health ? (
          <div className="space-y-1.5 text-[11.5px]">
            <p className="flex items-center gap-1.5 text-ink-soft">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  health.degraded ? "bg-amber" : "bg-jade",
                )}
              />
              {health.provider || "未配置模型"}
              {health.degraded ? <span className="text-amber">· 辅助链路降级</span> : null}
            </p>
            <p className="text-ink-faint">
              辅助链路 {health.okCount ?? 0} 成功 / {health.failCount ?? 0} 失败 · 情景 {health.scenarios ?? 0} 个
            </p>
          </div>
        ) : (
          <p className="text-[12px] text-ink-faint">健康状态读取中…</p>
        )}
      </RailSection>
    </div>
  );
}
