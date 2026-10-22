import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow ? (
          <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.22em] text-brand/80">{eyebrow}</p>
        ) : null}
        <h1 className="font-display text-[28px] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-ink-soft">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
