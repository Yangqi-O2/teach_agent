import type { EnglishStats } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { Badge, Button, Progress } from "../../../components/ui/primitives";
import { cn } from "../../../lib/utils";
import { Drawer } from "./Drawer";

function number(value: number | null | undefined, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function StatTile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2/40 p-3">
      <p className="text-[11px] text-ink-faint">{label}</p>
      <p className={cn("mt-0.5 text-[17px] font-semibold text-ink", tone)}>{value}</p>
    </div>
  );
}

export function StatsDrawer({
  open,
  onOpenChange,
  stats,
  loading,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stats: EnglishStats | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const budgetRatio = Math.min(100, number(stats?.budget?.ratio) * 100);
  const degraded = Boolean(stats?.health?.degraded);
  const chains = stats?.health?.chains ?? [];
  const okTotal = number(stats?.health?.okCount ?? stats?.health?.ok, chains.reduce((sum, chain) => sum + number(chain.ok), 0));
  const failTotal = number(stats?.health?.failCount ?? stats?.health?.fail, chains.reduce((sum, chain) => sum + number(chain.fail), 0));
  const rates: { name: string; rate: number }[] =
    stats?.health?.rates && Object.keys(stats.health.rates).length
      ? Object.entries(stats.health.rates).map(([name, rate]) => ({ name, rate: number(rate) }))
      : chains.map((chain) => ({ name: chain.name, rate: number(chain.rate) }));

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="成本看板"
      subtitle="近 24 小时 · 成本按供应商单价估算"
      footer={
        <Button variant="secondary" size="sm" className="w-full" loading={loading} onClick={onRefresh}>
          <Icon name="refresh-cw" className="h-3.5 w-3.5" />
          刷新
        </Button>
      }
    >
      {loading && !stats ? (
        <div className="space-y-2">
          <div className="shimmer h-20 rounded-xl" />
          <div className="shimmer h-20 rounded-xl" />
          <div className="shimmer h-32 rounded-xl" />
        </div>
      ) : !stats ? (
        <div className="rounded-xl bg-danger/10 p-3 text-[12.5px] leading-relaxed text-danger">
          统计读取失败。
          <Button variant="ghost" size="sm" className="mt-2" onClick={onRefresh}>
            <Icon name="refresh-cw" className="h-3.5 w-3.5" />
            重试
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          {degraded ? (
            <div className="flex items-start gap-2 rounded-xl border border-amber/30 bg-amber/10 p-2.5 text-[11.5px] leading-relaxed text-amber">
              <Icon name="alert-circle" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>辅助链路异常：对话仍可用，但纠错 / 记忆可能不完整。</span>
            </div>
          ) : null}

          <div className="grid grid-cols-2 gap-2">
            <StatTile label="对话轮次" value={number(stats.turns24h).toLocaleString("zh-CN")} />
            <StatTile label="TTFT 均值" value={`${Math.round(number(stats.ttftAvg))}ms`} />
            <StatTile label="延迟 P95" value={`${Math.round(number(stats.latencyP95))}ms`} />
            <StatTile label="估算成本" value={`¥${number(stats.costYuan24h).toFixed(2)}`} />
          </div>

          <section className="rounded-xl border border-line p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11.5px] text-ink-soft">今日 token</p>
              <span className="font-mono text-[11px] text-ink-faint">
                {number(stats.tokens24h).toLocaleString("zh-CN")}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-ink-faint">
              月预算 {number(stats.budget?.used).toLocaleString("zh-CN")} /{" "}
              {number(stats.budget?.limit).toLocaleString("zh-CN")} · 已用{" "}
              {(number(stats.budget?.ratio) * 100).toFixed(1)}%
            </p>
            <Progress value={budgetRatio} className="mt-1.5" />
            {stats.budget?.degrade ? (
              <p className="mt-1 flex items-center gap-1 text-[11px] text-amber">
                <Icon name="alert-circle" className="h-3 w-3" />
                预算超过阈值，已降级到备用模型
              </p>
            ) : null}
          </section>

          <section className="rounded-xl border border-line p-3">
            <p className="text-[11.5px] text-ink-soft">回复质量 · 近 24h</p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-ink-faint">
              已测 {number(stats.quality?.measured)} 条 · 平均 {number(stats.quality?.avgWords)} 词 · 以问句结尾{" "}
              {number(stats.quality?.pctEndsWithQuestion)}%
            </p>
            {stats.quality?.flagged ? (
              <p className="mt-1 text-[11px] text-amber">被标记 {stats.quality.flagged} 条</p>
            ) : null}
            {stats.quality?.topFlags?.length ? (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {stats.quality.topFlags.map((flag) => (
                  <Badge key={flag.flag} tone="amber">
                    {flag.flag} ×{flag.n}
                  </Badge>
                ))}
              </div>
            ) : null}
          </section>

          <section className="rounded-xl border border-line p-3">
            <p className="text-[11.5px] text-ink-soft">辅助链路</p>
            <p className="mt-1 text-[11.5px] text-ink-faint">
              成功 {okTotal} · 失败 {failTotal}
              {degraded ? " · 已降级" : " · 正常"}
            </p>
            {chains.length ? (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {chains.map((chain) => (
                  <span
                    key={chain.name}
                    className={
                      chain.degraded
                        ? "rounded-full bg-danger/10 px-2 py-0.5 text-[10.5px] text-danger"
                        : "rounded-full bg-surface-2 px-2 py-0.5 text-[10.5px] text-ink-faint"
                    }
                  >
                    {chain.name} {number(chain.ok)}/{number(chain.ok) + number(chain.fail)}
                  </span>
                ))}
              </div>
            ) : rates.length ? (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {rates.map((entry) => (
                  <span
                    key={entry.name}
                    className="rounded-full bg-surface-2 px-2 py-0.5 text-[10.5px] text-ink-faint"
                  >
                    {entry.name} {(entry.rate * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
            ) : null}
          </section>
        </div>
      )}
    </Drawer>
  );
}
