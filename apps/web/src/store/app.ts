import { create } from "zustand";

import {
  ApiError,
  api,
  type AppInfo,
  type AuthConfig,
  type CapabilityInfo,
  type ProfileInput,
  type Provider,
  type User,
  type UserProfile,
} from "../lib/api";

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
  authConfig: AuthConfig | null;
  user: User | null;
  profile: UserProfile | null;
  info: AppInfo | null;
  capabilities: CapabilityInfo[];
  providers: Provider[];
  theme: Theme;
  paletteOpen: boolean;
  toasts: Toast[];

  initialize: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, displayName: string) => Promise<void>;
  loadProfile: () => Promise<UserProfile | null>;
  saveProfile: (input: ProfileInput) => Promise<UserProfile>;
  logout: () => Promise<void>;
  loadWorkspace: () => Promise<void>;
  resetAuth: () => void;

  refreshProviders: () => Promise<void>;
  refreshCapabilities: () => Promise<void>;
  setTheme: (theme: Theme) => void;
  setPaletteOpen: (open: boolean) => void;
  toast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: number) => void;
};

let toastSeq = 0;

const EMPTY_WORKSPACE = {
  info: null as AppInfo | null,
  profile: null as UserProfile | null,
  capabilities: [] as CapabilityInfo[],
  providers: [] as Provider[],
};

export const useApp = create<AppState>((set, get) => ({
  booted: false,
  bootError: null,
  authConfig: null,
  user: null,
  profile: null,
  info: null,
  capabilities: [],
  providers: [],
  theme: (localStorage.getItem("tjh-theme") as Theme) || "system",
  paletteOpen: false,
  toasts: [],

  initialize: async () => {
    try {
      const authConfig = await api.auth.config();
      set({ authConfig });
      try {
        const user = await api.auth.me();
        set({ user });
        await get().loadWorkspace();
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) throw error;
        set({ user: null });
      }
      set({ booted: true, bootError: null });
    } catch (error) {
      set({
        booted: true,
        bootError: error instanceof Error ? error.message : String(error),
      });
    }
  },

  login: async (username, password) => {
    const user = await api.auth.login(username, password);
    set({ user });
    await get().loadWorkspace();
  },

  register: async (username, password, displayName) => {
    const user = await api.auth.register(username, password, displayName);
    set({ user });
    await get().loadWorkspace();
  },

  logout: async () => {
    try {
      await api.auth.logout();
    } catch {
      /* 忽略：本地状态照常清空 */
    }
    get().resetAuth();
  },

  resetAuth: () => {
    set({
      user: null,
      ...EMPTY_WORKSPACE,
      paletteOpen: false,
    });
  },

  loadWorkspace: async () => {
    const [info, capabilities, providers, profile] = await Promise.all([
      api.info(),
      api.capabilities.list(),
      api.providers.list(),
      // 画像失败不影响整个工作台加载：个性化推荐可以退化，登录不能
      api.profile.get().catch(() => null),
    ]);
    set({ info, capabilities, providers, profile });
  },

  loadProfile: async () => {
    try {
      const profile = await api.profile.get();
      set({ profile });
      return profile;
    } catch {
      return null;
    }
  },

  saveProfile: async (input) => {
    const profile = await api.profile.update(input);
    set({ profile });
    return profile;
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
