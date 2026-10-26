import { NavLink } from "react-router-dom";

import { Brand } from "../components/Brand";
import { Icon } from "../components/Icon";
import { cn } from "../lib/utils";
import { useApp } from "../store/app";
import { ThemeToggle } from "./ThemeToggle";

function NavItem({
  to,
  icon,
  label,
  end,
  onNavigate,
}: {
  to: string;
  icon: string;
  label: string;
  end?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] font-medium transition-all duration-200",
          isActive
            ? "bg-brand-soft text-brand-strong"
            : "text-ink-soft hover:bg-surface-2 hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={cn(
              "absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-brand transition-opacity",
              isActive ? "opacity-100" : "opacity-0",
            )}
          />
          <Icon name={icon} className="h-[18px] w-[18px] shrink-0" />
          <span className="truncate">{label}</span>
        </>
      )}
    </NavLink>
  );
}

function GroupLabel({ children }: { children: string }) {
  return (
    <p className="px-3 pb-1.5 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-ink-faint/80">
      {children}
    </p>
  );
}

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const capabilities = useApp((s) => s.capabilities);
  const user = useApp((s) => s.user);
  const info = useApp((s) => s.info);
  const enabled = capabilities.filter((c) => c.enabled && c.nav);

  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-5 pt-6">
        <Brand />
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        <div>
          <GroupLabel>工作台</GroupLabel>
          <div className="space-y-0.5">
            <NavItem to="/" end icon="layout-dashboard" label="首页" onNavigate={onNavigate} />
            <NavItem to="/jobs" icon="list-checks" label="任务中心" onNavigate={onNavigate} />
            {user?.role === "admin" ? (
              <NavItem to="/admin/users" icon="users" label="成员管理" onNavigate={onNavigate} />
            ) : null}
          </div>
        </div>

        <div>
          <GroupLabel>能力</GroupLabel>
          <div className="space-y-0.5">
            {enabled.map((cap) => (
              <NavItem
                key={cap.id}
                to={cap.nav!.path}
                icon={cap.icon}
                label={cap.nav!.label}
                onNavigate={onNavigate}
              />
            ))}
            <NavLink
              to="/settings?tab=capabilities"
              onClick={onNavigate}
              className="flex items-center gap-3 rounded-xl px-3 py-2 text-[12.5px] text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <Icon name="plus" className="h-4 w-4" />
              <span>管理能力</span>
            </NavLink>
          </div>
        </div>
      </nav>

      <div className="space-y-1 border-t border-line/70 p-3">
        <NavItem to="/settings" icon="settings" label="设置" onNavigate={onNavigate} />
        <div className="flex items-center justify-between px-2 pt-2">
          <ThemeToggle />
          <span className="text-[10.5px] tracking-wider text-ink-faint/80">
            {info?.app.version ? `v${info.app.version}` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[268px] flex-col border-r border-line/80 bg-surface/70 backdrop-blur-xl md:flex">
      <SidebarContent />
    </aside>
  );
}
