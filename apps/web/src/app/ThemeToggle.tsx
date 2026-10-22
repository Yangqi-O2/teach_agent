import { useApp, type Theme } from "../store/app";
import { cn } from "../lib/utils";
import { Icon } from "../components/Icon";

const ORDER: Theme[] = ["light", "dark", "system"];
const META: Record<Theme, { icon: string; label: string }> = {
  light: { icon: "sun", label: "浅色" },
  dark: { icon: "moon", label: "深色" },
  system: { icon: "monitor", label: "跟随系统" },
};

export function ThemeToggle({ className }: { className?: string }) {
  const theme = useApp((s) => s.theme);
  const setTheme = useApp((s) => s.setTheme);
  const next = () => setTheme(ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length]);
  const meta = META[theme];
  return (
    <button
      onClick={next}
      title="切换主题"
      className={cn(
        "group inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink-soft transition-colors hover:text-ink",
        className,
      )}
    >
      <Icon name={meta.icon} className="h-3.5 w-3.5" />
      <span>{meta.label}</span>
    </button>
  );
}
