import { cn } from "../lib/utils";

export function BrandMark({ size = 38, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cn(
        "relative inline-flex items-center justify-center rounded-[12px] bg-gradient-to-br from-brand to-jade text-canvas shadow-[0_10px_22px_-10px_rgba(20,104,123,0.85)]",
        className,
      )}
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 32 32" className="h-[62%] w-[62%]" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
        <path d="M3.5 18.5c3 0 3-2.4 6.2-2.4s3.2 2.4 6.2 2.4 3.2-2.4 6.2-2.4 3.2 2.4 6.2 2.4" />
        <path d="M3.5 24.5c3 0 3-2.4 6.2-2.4s3.2 2.4 6.2 2.4 3.2-2.4 6.2-2.4 3.2 2.4 6.2 2.4" opacity="0.55" />
        <circle cx="24.5" cy="9.5" r="2.6" fill="currentColor" stroke="none" />
      </svg>
    </span>
  );
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <BrandMark />
      {!compact ? (
        <div className="leading-tight">
          <p className="font-display text-[19px] font-semibold tracking-[0.06em] text-ink">天健湖</p>
          <p className="mt-0.5 text-[10px] uppercase tracking-[0.22em] text-ink-faint">Tianjian Lake</p>
        </div>
      ) : null}
    </div>
  );
}
