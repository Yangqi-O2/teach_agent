import { Link, useLocation } from "react-router-dom";

import { Icon } from "../components/Icon";
import { UserMenu } from "../components/UserMenu";
import { cn } from "../lib/utils";
import { useApp } from "../store/app";

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const location = useLocation();
  const capabilities = useApp((s) => s.capabilities);
  const providers = useApp((s) => s.providers);
  const setPaletteOpen = useApp((s) => s.setPaletteOpen);

  const title = (() => {
    if (location.pathname === "/") return "首页";
    if (location.pathname.startsWith("/settings")) return "设置";
    if (location.pathname.startsWith("/jobs")) return "任务中心";
    if (location.pathname.startsWith("/admin/users")) return "成员管理";
    const cap = capabilities.find((c) => c.nav && location.pathname.startsWith(c.nav.path));
    return cap?.nav?.label ?? "天健湖";
  })();

  const provider = providers.find((p) => p.is_default) ?? providers[0];

  return (
    <header className="sticky top-0 z-30 border-b border-line/60 bg-canvas/75 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-[1180px] items-center gap-3 px-4 md:px-9">
        <button
          onClick={onMenu}
          className="rounded-lg p-2 text-ink-soft transition-colors hover:bg-surface-2 hover:text-ink md:hidden"
          aria-label="打开导航"
        >
          <Icon name="list-checks" className="h-5 w-5" />
        </button>

        <div className="hidden items-center gap-2 text-[12.5px] text-ink-faint sm:flex">
          <span className="font-display tracking-wide">天健湖</span>
          <Icon name="chevron-right" className="h-3.5 w-3.5 opacity-60" />
          <span className="font-medium text-ink">{title}</span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setPaletteOpen(true)}
            className="group flex h-9 items-center gap-2 rounded-full border border-line bg-surface/80 pl-3 pr-2 text-[12.5px] text-ink-faint transition-colors hover:border-brand/30 hover:text-ink"
          >
            <Icon name="search" className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">搜索或跳转</span>
            <span className="kbd ml-1 hidden sm:inline-flex">⌘K</span>
          </button>

          <Link
            to="/settings?tab=models"
            className={cn(
              "hidden h-9 items-center gap-2 rounded-full border px-3 text-[12px] font-medium transition-colors sm:flex",
              provider
                ? "border-line bg-surface text-ink-soft hover:text-ink"
                : "border-amber/30 bg-amber/10 text-amber hover:bg-amber/15",
            )}
          >
            <span
              className={cn(
                "inline-block h-1.5 w-1.5 rounded-full",
                provider ? "bg-jade animate-pulse-dot" : "bg-amber",
              )}
            />
            {provider ? provider.name : "未配置模型"}
          </Link>

          <UserMenu />
        </div>
      </div>
    </header>
  );
}
