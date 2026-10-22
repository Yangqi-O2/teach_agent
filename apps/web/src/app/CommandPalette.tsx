import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Icon } from "../components/Icon";
import { cn } from "../lib/utils";
import { useApp } from "../store/app";

type Command = {
  id: string;
  group: "导航" | "操作";
  label: string;
  hint?: string;
  icon: string;
  run: () => void;
};

export function CommandPalette() {
  const open = useApp((s) => s.paletteOpen);
  const setOpen = useApp((s) => s.setPaletteOpen);
  const capabilities = useApp((s) => s.capabilities);
  const setTheme = useApp((s) => s.setTheme);
  const toast = useApp((s) => s.toast);
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 40);
    return () => window.clearTimeout(timer);
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const nav: Command[] = [
      { id: "home", group: "导航", label: "首页", icon: "layout-dashboard", run: () => navigate("/") },
      { id: "jobs", group: "导航", label: "任务中心", icon: "list-checks", run: () => navigate("/jobs") },
      ...capabilities
        .filter((c) => c.enabled && c.nav)
        .map<Command>((c) => ({
          id: `cap-${c.id}`,
          group: "导航",
          label: c.nav!.label,
          hint: c.name,
          icon: c.icon,
          run: () => navigate(c.nav!.path),
        })),
      { id: "settings", group: "导航", label: "设置", icon: "settings", run: () => navigate("/settings") },
      {
        id: "models",
        group: "导航",
        label: "模型接入",
        icon: "cpu",
        run: () => navigate("/settings?tab=models"),
      },
      {
        id: "capabilities",
        group: "导航",
        label: "能力管理",
        icon: "sparkles",
        run: () => navigate("/settings?tab=capabilities"),
      },
    ];
    const actions: Command[] = [
      { id: "theme-light", group: "操作", label: "切换到浅色主题", icon: "sun", run: () => setTheme("light") },
      { id: "theme-dark", group: "操作", label: "切换到深色主题", icon: "moon", run: () => setTheme("dark") },
      { id: "theme-system", group: "操作", label: "主题跟随系统", icon: "monitor", run: () => setTheme("system") },
      {
        id: "refresh",
        group: "操作",
        label: "刷新数据",
        icon: "refresh-cw",
        run: () => {
          window.location.reload();
        },
      },
      {
        id: "add-note",
        group: "操作",
        label: "写一条速记",
        icon: "notebook-pen",
        run: () => {
          navigate("/cap/notes");
          toast({ title: "已打开速记", description: "在左侧输入框写下内容即可保存" });
        },
      },
    ];
    return [...nav, ...actions];
  }, [capabilities, navigate, setTheme, toast]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => (c.label + " " + (c.hint ?? "")).toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    setActive((index) => Math.min(index, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((index) => (filtered.length ? (index + 1) % filtered.length : 0));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((index) => (filtered.length ? (index - 1 + filtered.length) % filtered.length : 0));
      } else if (event.key === "Enter") {
        event.preventDefault();
        const command = filtered[active];
        if (command) {
          setOpen(false);
          command.run();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, filtered, active, setOpen]);

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  let lastGroup = "";

  return (
    <div className="fixed inset-0 z-[65]">
      <div className="overlay-mask absolute inset-0 bg-ink/30 backdrop-blur-[4px]" onClick={() => setOpen(false)} />
      <div className="palette-pop relative mx-auto mt-[12vh] w-[min(600px,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-line bg-surface shadow-lift">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Icon name="search" className="h-4 w-4 text-ink-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索页面、能力或操作…"
            className="h-12 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-faint"
          />
          <span className="kbd">esc</span>
        </div>
        <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <p className="px-3 py-8 text-center text-[13px] text-ink-faint">没有匹配项</p>
          ) : (
            filtered.map((command, index) => {
              const showGroup = command.group !== lastGroup;
              lastGroup = command.group;
              return (
                <div key={command.id}>
                  {showGroup ? (
                    <p className="px-3 pb-1 pt-2 text-[10.5px] font-semibold uppercase tracking-[0.18em] text-ink-faint">
                      {command.group}
                    </p>
                  ) : null}
                  <button
                    data-index={index}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => {
                      setOpen(false);
                      command.run();
                    }}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[13.5px] transition-colors",
                      index === active ? "bg-brand-soft text-brand-strong" : "text-ink hover:bg-surface-2",
                    )}
                  >
                    <Icon name={command.icon} className="h-4 w-4 shrink-0 opacity-80" />
                    <span className="flex-1 truncate">{command.label}</span>
                    {command.hint ? <span className="text-[11.5px] text-ink-faint">{command.hint}</span> : null}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
