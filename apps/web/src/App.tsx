import { useEffect } from "react";
import { BrowserRouter } from "react-router-dom";

import { AppRoutes } from "./app/router";
import { Shell } from "./app/Shell";
import { BrandMark } from "./components/Brand";
import { Button } from "./components/ui/primitives";
import { applyTheme, useApp } from "./store/app";

function BootScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas">
      <div className="flex flex-col items-center gap-6">
        <div className="relative">
          <span className="absolute inset-0 rounded-2xl border border-brand/30 animate-ripple" />
          <BrandMark size={58} />
        </div>
        <div className="text-center">
          <p className="font-display text-lg font-semibold tracking-[0.08em] text-ink">天健湖</p>
          <p className="mt-1 text-[12px] tracking-wide text-ink-faint">正在准备湖面…</p>
        </div>
      </div>
    </div>
  );
}

function BootError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="card w-full max-w-md p-7 text-center">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-danger/10 text-danger">
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <path d="M12 8v5" strokeLinecap="round" />
            <circle cx="12" cy="16.5" r="0.9" fill="currentColor" stroke="none" />
            <path d="M12 3.5 21 20H3z" strokeLinejoin="round" />
          </svg>
        </div>
        <h1 className="font-display text-lg font-semibold text-ink">连不上后端服务</h1>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-faint">{message}</p>
        <div className="mt-6 flex items-center justify-center gap-2">
          <Button variant="primary" onClick={onRetry}>
            重试
          </Button>
          <Button variant="ghost" onClick={() => window.location.reload()}>
            刷新页面
          </Button>
        </div>
        <p className="mt-5 rounded-xl bg-surface-2 p-3 text-left font-mono text-[11.5px] leading-relaxed text-ink-faint">
          ./scripts/start.sh
          <br />
          # 或开发模式：make dev
        </p>
      </div>
    </div>
  );
}

export default function App() {
  const booted = useApp((s) => s.booted);
  const bootError = useApp((s) => s.bootError);
  const theme = useApp((s) => s.theme);
  const bootstrap = useApp((s) => s.bootstrap);
  const paletteOpen = useApp((s) => s.paletteOpen);
  const setPaletteOpen = useApp((s) => s.setPaletteOpen);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyTheme("system");
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }, [theme]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(!paletteOpen);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [paletteOpen, setPaletteOpen]);

  if (!booted) return <BootScreen />;
  if (bootError) return <BootError message={bootError} onRetry={() => bootstrap()} />;

  return (
    <BrowserRouter>
      <Shell>
        <AppRoutes />
      </Shell>
    </BrowserRouter>
  );
}
