import type { EnglishVocabItem } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { Button, EmptyState, Progress } from "../../../components/ui/primitives";
import { cn } from "../../../lib/utils";
import { Drawer } from "./Drawer";

const RATINGS: { rating: number; label: string; className: string }[] = [
  { rating: 1, label: "忘了", className: "text-danger" },
  { rating: 2, label: "模糊", className: "text-amber" },
  { rating: 3, label: "记得", className: "text-jade" },
  { rating: 4, label: "轻松", className: "text-brand" },
];

export function VocabDrawer({
  open,
  onOpenChange,
  items,
  dueCount,
  loading,
  reviewing,
  onReview,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: EnglishVocabItem[];
  dueCount: number;
  loading: boolean;
  reviewing: string | null;
  onReview: (lemma: string, rating: number) => void;
  onRefresh: () => void;
}) {
  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="生词本"
      subtitle={
        <>
          {dueCount} 个到期 · 共 {items.length} 个 · FSRS 间隔复习
        </>
      }
      footer={
        <Button variant="secondary" size="sm" className="w-full" loading={loading} onClick={onRefresh}>
          <Icon name="refresh-cw" className="h-3.5 w-3.5" />
          刷新
        </Button>
      }
    >
      {loading && !items.length ? (
        <div className="space-y-2">
          <div className="shimmer h-24 rounded-xl" />
          <div className="shimmer h-24 rounded-xl" />
          <div className="shimmer h-24 rounded-xl" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon="bookmark"
          className="border-0 px-2 py-10"
          title="还没有生词"
          description="对话里点 AI 回复下方的「+ 单词」即可保存；保存后按 FSRS 安排复习。"
        />
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <article
              key={item.lemma}
              className={cn(
                "rounded-xl border p-3",
                item.due ? "border-brand/30 bg-brand-soft/25" : "border-line bg-surface",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="flex min-w-0 items-baseline gap-1.5 text-[14px] font-medium text-ink">
                  <span className="truncate">{item.lemma}</span>
                  {item.pos ? <span className="text-[10.5px] text-ink-faint">{item.pos}</span> : null}
                </p>
                {item.due ? (
                  <span className="shrink-0 rounded-full bg-danger/12 px-1.5 py-0.5 text-[10px] font-medium text-danger">
                    到期
                  </span>
                ) : (
                  <span className="shrink-0 rounded-full bg-surface-2 px-1.5 py-0.5 text-[10px] text-ink-faint">
                    {item.intervalDays} 天后
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-[12px] text-ink-soft">{item.glossZh ?? "—"}</p>
              {item.context ? (
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-ink-faint">{item.context}</p>
              ) : null}
              <div className="mt-2">
                <Progress value={Math.round((item.mastery ?? 0) * 100)} />
                <div className="mt-2 flex items-center gap-1.5">
                  {RATINGS.map((rating) => (
                    <button
                      key={rating.rating}
                      type="button"
                      disabled={reviewing === item.lemma}
                      onClick={() => onReview(item.lemma, rating.rating)}
                      className={cn(
                        "rounded-full border border-line px-2 py-0.5 text-[11px] transition-colors hover:border-brand/40 hover:bg-surface-2",
                        rating.className,
                        reviewing === item.lemma && "opacity-50",
                      )}
                    >
                      {rating.label}
                    </button>
                  ))}
                  <span className="ml-auto text-[10px] text-ink-faint">
                    复习 {item.reps} 次 · 掌握 {Math.round((item.mastery ?? 0) * 100)}%
                  </span>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </Drawer>
  );
}
