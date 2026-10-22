import { Icon } from "./Icon";
import { cn } from "../lib/utils";

export function StatCard({
  icon,
  label,
  value,
  hint,
  tone = "brand",
}: {
  icon: string;
  label: string;
  value: string;
  hint?: string;
  tone?: "brand" | "jade" | "amber" | "neutral";
}) {
  const tones = {
    brand: "bg-brand-soft text-brand-strong",
    jade: "bg-jade/12 text-jade",
    amber: "bg-amber/12 text-amber",
    neutral: "bg-surface-2 text-ink-soft",
  };
  return (
    <div className="card card-hover flex items-start gap-3.5 p-4">
      <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-xl", tones[tone])}>
        <Icon name={icon} className="h-[18px] w-[18px]" />
      </span>
      <div className="min-w-0">
        <p className="text-[11.5px] font-medium uppercase tracking-[0.12em] text-ink-faint">{label}</p>
        <p className="mt-1 truncate text-[17px] font-semibold text-ink">{value}</p>
        {hint ? <p className="mt-0.5 truncate text-[11.5px] text-ink-faint">{hint}</p> : null}
      </div>
    </div>
  );
}
