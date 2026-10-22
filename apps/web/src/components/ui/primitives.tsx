import { cva, type VariantProps } from "class-variance-authority";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

import { Icon } from "../Icon";
import { cn } from "../../lib/utils";

/* ---------------- Button ---------------- */

const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium transition-all duration-200 disabled:pointer-events-none disabled:opacity-45 active:scale-[0.985]",
  {
    variants: {
      variant: {
        primary: "bg-brand text-canvas shadow-[0_10px_30px_-12px_rgba(20,104,123,0.75)] hover:bg-brand-strong",
        secondary: "border border-line bg-surface text-ink hover:bg-surface-2",
        ghost: "text-ink-soft hover:bg-surface-2 hover:text-ink",
        subtle: "bg-brand-soft text-brand-strong hover:bg-brand-soft/70",
        danger: "bg-danger/10 text-danger hover:bg-danger/15",
        plain: "text-ink-soft hover:text-ink",
      },
      size: {
        sm: "h-8 px-3 text-[13px]",
        md: "h-10 px-4 text-sm",
        lg: "h-11 px-6 text-[15px]",
        icon: "h-9 w-9 p-0",
        "icon-sm": "h-8 w-8 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { loading?: boolean };

export function Button({ className, variant, size, loading, children, disabled, ...props }: ButtonProps) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <span className="h-4 w-4 animate-spin rounded-full border-[1.8px] border-current border-t-transparent" /> : null}
      {children}
    </button>
  );
}

/* ---------------- Badge ---------------- */

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11.5px] font-medium tracking-wide",
  {
    variants: {
      tone: {
        neutral: "border-line bg-surface-2 text-ink-soft",
        brand: "border-transparent bg-brand-soft text-brand-strong",
        jade: "border-transparent bg-jade/12 text-jade",
        amber: "border-transparent bg-amber/12 text-amber",
        danger: "border-transparent bg-danger/12 text-danger",
        outline: "border-line text-ink-faint",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  children,
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)}>{children}</span>;
}

export function Dot({ className, tone = "jade" }: { className?: string; tone?: "jade" | "amber" | "danger" | "neutral" | "brand" }) {
  const colors = { jade: "bg-jade", amber: "bg-amber", danger: "bg-danger", neutral: "bg-ink-faint", brand: "bg-brand" };
  return <span className={cn("inline-block h-1.5 w-1.5 rounded-full", colors[tone], className)} />;
}

/* ---------------- Inputs ---------------- */

export function Label({ children, htmlFor, className }: { children: ReactNode; htmlFor?: string; className?: string }) {
  return (
    <label htmlFor={htmlFor} className={cn("mb-1.5 block text-[13px] font-medium text-ink", className)}>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-ink placeholder:text-ink-faint/80 transition-colors focus:border-brand/60 focus:outline-none focus:ring-4 focus:ring-brand/10 disabled:opacity-50";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(inputClass, className)} {...props} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(inputClass, "min-h-24 resize-y leading-relaxed", className)} {...props} />;
}

export function Field({
  label,
  hint,
  htmlFor,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint ? <p className="pt-0.5 text-xs text-ink-faint">{hint}</p> : null}
    </div>
  );
}

/* ---------------- Switch ---------------- */

export function Switch({
  checked,
  onCheckedChange,
  disabled,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      className={cn(
        "relative h-6 w-11 shrink-0 rounded-full border border-transparent transition-colors",
        checked ? "bg-brand" : "bg-ink/15",
        disabled && "opacity-50",
      )}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          "block h-4.5 w-4.5 translate-x-1 rounded-full bg-surface shadow transition-transform",
          "data-[state=checked]:translate-x-[1.4rem]",
        )}
      />
    </SwitchPrimitive.Root>
  );
}

/* ---------------- Progress ---------------- */

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-ink/8", className)}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-brand to-jade transition-[width] duration-500 ease-out"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}

/* ---------------- Empty state ---------------- */

export function EmptyState({
  icon = "sparkles",
  title,
  description,
  action,
  className,
}: {
  icon?: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-card border border-dashed border-line/90 px-6 py-12 text-center", className)}>
      <div className="relative mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-line bg-surface-2 text-brand">
        <span className="absolute inset-0 rounded-2xl border border-brand/15 animate-ripple" />
        <Icon name={icon} className="h-6 w-6" />
      </div>
      <p className="text-[15px] font-medium text-ink">{title}</p>
      {description ? <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-ink-faint">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

/* ---------------- Segmented ---------------- */

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={cn("inline-flex items-center gap-1 rounded-full border border-line bg-surface-2 p-1", className)}>
      {options.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors",
            value === option.value ? "bg-surface text-ink shadow-sm" : "text-ink-faint hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------- Section heading ---------------- */

export function SectionHeading({
  title,
  description,
  action,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-4 flex items-end justify-between gap-4", className)}>
      <div>
        <h2 className="font-display text-[19px] font-semibold tracking-tight text-ink">{title}</h2>
        {description ? <p className="mt-1 text-[13px] text-ink-faint">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
