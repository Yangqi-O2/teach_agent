import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";

import { useApp, type Toast } from "../../store/app";
import { cn } from "../../lib/utils";
import { Icon } from "../Icon";

/* ---------------- Modal ---------------- */

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  const width = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" }[size];
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="overlay-mask fixed inset-0 z-50 bg-ink/25 backdrop-blur-[3px]" />
        <DialogPrimitive.Content
          className={cn(
            "modal-pop fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-surface p-6 shadow-lift focus:outline-none",
            width,
          )}
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <DialogPrimitive.Title className="font-display text-lg font-semibold text-ink">{title}</DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="mt-1 text-[13px] leading-relaxed text-ink-faint">
                  {description}
                </DialogPrimitive.Description>
              ) : null}
            </div>
            <DialogPrimitive.Close asChild>
              <button className="rounded-full p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink">
                <Icon name="x" className="h-4 w-4" />
              </button>
            </DialogPrimitive.Close>
          </div>
          <div className="space-y-4">{children}</div>
          {footer ? <div className="mt-6 flex items-center justify-end gap-2">{footer}</div> : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ---------------- Dropdown ---------------- */

export const Dropdown = DropdownPrimitive.Root;
export const DropdownTrigger = DropdownPrimitive.Trigger;

export function DropdownMenu({ children, align = "end" }: { children: ReactNode; align?: "start" | "end" }) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        align={align}
        sideOffset={6}
        className="menu-pop z-50 min-w-40 rounded-xl border border-line bg-surface p-1.5 shadow-lift"
      >
        {children}
      </DropdownPrimitive.Content>
    </DropdownPrimitive.Portal>
  );
}

export function DropdownItem({
  children,
  onSelect,
  danger,
}: {
  children: ReactNode;
  onSelect?: () => void;
  danger?: boolean;
}) {
  return (
    <DropdownPrimitive.Item
      onSelect={(event) => {
        event.preventDefault();
        onSelect?.();
      }}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] outline-none transition-colors data-[highlighted]:bg-surface-2",
        danger ? "text-danger" : "text-ink",
      )}
    >
      {children}
    </DropdownPrimitive.Item>
  );
}

export function DropdownSeparator() {
  return <DropdownPrimitive.Separator className="my-1 h-px bg-line" />;
}

/* ---------------- Toasts ---------------- */

const TOAST_TONE: Record<NonNullable<Toast["tone"]>, { icon: string; className: string }> = {
  default: { icon: "info", className: "text-brand" },
  success: { icon: "check", className: "text-jade" },
  error: { icon: "alert-circle", className: "text-danger" },
};

export function Toaster() {
  const toasts = useApp((s) => s.toasts);
  const dismiss = useApp((s) => s.dismissToast);
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[70] flex w-[min(360px,calc(100vw-2.5rem))] flex-col gap-2">
      {toasts.map((toast) => {
        const tone = TOAST_TONE[toast.tone ?? "default"];
        return (
          <div
            key={toast.id}
            className="toast-pop pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-surface/95 p-3.5 shadow-lift backdrop-blur"
          >
            <span className={cn("mt-0.5", tone.className)}>
              <Icon name={tone.icon} className="h-4.5 w-4.5" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium text-ink">{toast.title}</p>
              {toast.description ? (
                <p className="mt-0.5 break-words text-xs leading-relaxed text-ink-faint">{toast.description}</p>
              ) : null}
            </div>
            <button
              onClick={() => dismiss(toast.id)}
              className="rounded-md p-1 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <Icon name="x" className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
