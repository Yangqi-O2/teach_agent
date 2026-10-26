import type { EnglishErrorPattern, EnglishErrorProfile } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { Badge, Button, EmptyState } from "../../../components/ui/primitives";
import { cn } from "../../../lib/utils";
import { Drawer } from "./Drawer";

const TREND_META: Record<EnglishErrorPattern["trend"], { label: string; className: string }> = {
  up: { label: "↑ 变多", className: "text-amber" },
  down: { label: "↓ 变少", className: "text-jade" },
  flat: { label: "→ 持平", className: "text-ink-faint" },
  new: { label: "● 新增", className: "text-brand" },
};

export function ErrorProfileDrawer({
  open,
  onOpenChange,
  profile,
  loading,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  profile: EnglishErrorProfile | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="错误档案"
      subtitle={
        profile
          ? `${profile.active} 个待改 · ${profile.improved} 个已改正 · 按出现次数排序`
          : "按错误类型统计趋势，连续无错即视为已改正"
      }
      footer={
        <Button variant="secondary" size="sm" className="w-full" loading={loading} onClick={onRefresh}>
          <Icon name="refresh-cw" className="h-3.5 w-3.5" />
          刷新
        </Button>
      }
    >
      {loading && !profile ? (
        <div className="space-y-2">
          <div className="shimmer h-20 rounded-xl" />
          <div className="shimmer h-20 rounded-xl" />
          <div className="shimmer h-20 rounded-xl" />
        </div>
      ) : !profile?.items.length ? (
        <EmptyState
          icon="list-checks"
          className="border-0 px-2 py-10"
          title="还没有错误记录"
          description="多发几句英文，系统会自动归类；错误会按类型聚合，用于生成下一轮的重点提示。"
        />
      ) : (
        <div className="space-y-2">
          {profile.items.map((pattern) => {
            const trend = TREND_META[pattern.trend] ?? TREND_META.flat;
            return (
              <article
                key={pattern.code}
                className={cn(
                  "rounded-xl border p-3",
                  pattern.improved ? "border-jade/30 bg-jade/5" : "border-line bg-surface",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 truncate text-[13px] font-medium text-ink">{pattern.label}</p>
                  {pattern.improved ? (
                    <Badge tone="jade">已改正</Badge>
                  ) : (
                    <span className={cn("shrink-0 text-[11px]", trend.className)}>{trend.label}</span>
                  )}
                </div>
                <p className="mt-1 text-[11.5px] text-ink-soft">
                  累计 {pattern.occurrences} 次 · 近 7 天 {pattern.recent7} 次 · 前 7 天 {pattern.prev7} 次
                </p>
                <p className="mt-0.5 font-mono text-[10px] text-ink-faint/70">{pattern.code}</p>
              </article>
            );
          })}
        </div>
      )}
    </Drawer>
  );
}
