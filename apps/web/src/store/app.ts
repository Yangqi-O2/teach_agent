import { create } from "zustand";

import { api, type AppInfo, type CapabilityInfo, type Provider } from "../lib/api";

export type Theme = "light" | "dark" | "system";
export type ToastTone = "default" | "success" | "error";

export type Toast = {
  id: number;
  title: string;
  description?: string;
  tone?: ToastTone;
};

function resolveTheme(theme: Theme): "light" | "dark" {
  if (theme !== "system") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = resolveTheme(theme);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", resolveTheme(theme) === "dark" ? "#0a1316" : "#f4f1e8");
}

type AppState = {
  booted: boolean;
  bootError: string | null;
  info: AppInfo | null;
  capabilities: CapabilityInfo[];
  providers: Provider[];
  theme: Theme;
  paletteOpen: boolean;
  toasts: Toast[];
  bootstrap: () => Promise<void>;
  refreshProviders: () => Promise<void>;
  refreshCapabilities: () => Promise<void>;
  setTheme: (theme: Theme) => void;
  setPaletteOpen: (open: boolean) => void;
  toast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: number) => void;
};

let toastSeq = 0;

export const useApp = create<AppState>((set, get) => ({
  booted: false,
  bootError: null,
  info: null,
  capabilities: [],
  providers: [],
  theme: (localStorage.getItem("tjh-theme") as Theme) || "system",
  paletteOpen: false,
  toasts: [],

  bootstrap: async () => {
    try {
      const [info, capabilities, providers] = await Promise.all([
        api.info(),
        api.capabilities.list(),
        api.providers.list(),
      ]);
      set({ info, capabilities, providers, booted: true, bootError: null });
    } catch (error) {
      set({ booted: true, bootError: error instanceof Error ? error.message : String(error) });
    }
  },

  refreshProviders: async () => {
    try {
      const [providers, info] = await Promise.all([api.providers.list(), api.info()]);
      set({ providers, info });
    } catch {
      /* 静默失败，界面保留旧数据 */
    }
  },

  refreshCapabilities: async () => {
    try {
      set({ capabilities: await api.capabilities.list() });
    } catch {
      /* 静默失败 */
    }
  },

  setTheme: (theme) => {
    localStorage.setItem("tjh-theme", theme);
    applyTheme(theme);
    set({ theme });
  },

  setPaletteOpen: (open) => set({ paletteOpen: open }),

  toast: (toast) => {
    const id = ++toastSeq;
    set({ toasts: [...get().toasts, { tone: "default", ...toast, id }] });
    window.setTimeout(() => get().dismissToast(id), toast.tone === "error" ? 6000 : 3600);
  },

  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));
