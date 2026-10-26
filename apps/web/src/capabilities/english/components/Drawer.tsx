import { useEffect, type ReactNode } from "react";

import { Icon } from "../../../components/Icon";
import { cn } from "../../../lib/utils";

/** 右侧抽屉：桌面/移动端共用，Esc 关闭，点遮罩关闭 */
export function Drawer({
  open,
  onOpenChange,
  title,
  subtitle,
  children,
  footer,
  width = "w-[min(100vw-2rem,380px)]",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="关闭抽屉"
        onClick={() => onOpenChange(false)}
        className="overlay-mask absolute inset-0 cursor-default bg-ink/25 backdrop-blur-[2px]"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "drawer-in relative flex h-full flex-col border-l border-line bg-surface shadow-lift",
          width,
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3.5">
          <div className="min-w-0">
            <p className="text-[14px] font-semibold text-ink">{title}</p>
            {subtitle ? <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink-faint">{subtitle}</p> : null}
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="shrink-0 rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
            aria-label="关闭"
          >
            <Icon name="x" className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
        {footer ? <div className="border-t border-line px-4 py-3">{footer}</div> : null}
      </aside>
    </div>
  );
}
