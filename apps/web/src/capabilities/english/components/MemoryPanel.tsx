import type { EnglishMemoryView } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { cn } from "../../../lib/utils";

export function MemoryPanel({
  memory,
  expanded,
  onToggle,
}: {
  memory: EnglishMemoryView | null;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (!memory) return null;
  const facts = memory.established_facts ?? [];
  const threads = memory.open_threads ?? [];
  const beats = memory.beats_done ?? [];
  const counts = memory.counts ?? { facts: 0, threads: 0, beats: 0 };
  if (!counts.facts && !counts.threads && !counts.beats) return null;

  return (
    <div className="border-b border-line bg-surface-2/40 px-4 py-1.5 md:px-5">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 text-left text-[11.5px] text-ink-soft transition-colors hover:text-ink"
      >
        <span className="rounded-full bg-brand-soft px-1.5 py-0.5 text-[10.5px] font-medium text-brand-strong">
          情景记忆
        </span>
        <span className="min-w-0 truncate">
          事实 {counts.facts} · 待解决 {counts.threads} · 节拍 {counts.beats}
          {typeof memory.revision === "number" ? ` · v${memory.revision}` : ""}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1 text-ink-faint">
          {expanded ? "收起" : "展开"}
          <Icon
            name="chevron-down"
            className={cn("h-3 w-3 transition-transform", expanded && "rotate-180")}
          />
        </span>
      </button>

      {expanded ? (
        <div className="mt-1.5 max-h-40 space-y-0.5 overflow-y-auto pb-1.5 text-[11.5px] leading-relaxed">
          {facts.map((fact) => (
            <p key={`fact-${fact}`} className="text-ink-soft">
              · 事实：{fact}
            </p>
          ))}
          {threads.map((thread) => (
            <p key={`thread-${thread}`} className="text-ink-soft">
              · 待办：{thread}
            </p>
          ))}
          {beats.map((beat) => (
            <p key={`beat-${beat}`} className="text-ink-faint">
              · 已过：{beat}
            </p>
          ))}
          {!facts.length && !threads.length && !beats.length ? (
            <p className="text-ink-faint">还没有积累记忆，多聊几轮就会出现。</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
