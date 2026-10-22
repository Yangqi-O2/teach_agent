export type SettingProp = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
};

export type CapabilityInfo = {
  id: string;
  name: string;
  description: string;
  icon: string;
  nav: { label: string; path: string; order: number } | null;
  version: string;
  status: "stable" | "beta" | "planned" | string;
  settings_schema: { type?: string; properties?: Record<string, SettingProp> };
  enabled: boolean;
  settings: Record<string, unknown>;
  has_tools: boolean;
};

export type Provider = {
  id: number;
  name: string;
  base_url: string;
  chat_model: string;
  embed_model: string | null;
  is_default: boolean;
  has_key: boolean;
  key_hint: string | null;
  created_at: string | null;
};

export type ProviderInput = {
  name: string;
  base_url: string;
  api_key?: string;
  chat_model: string;
  embed_model?: string | null;
};

export type TestResult = {
  ok: boolean;
  latency_ms: number;
  models: string[];
  models_error?: string | null;
  chat_ok?: boolean | null;
  chat_error?: string | null;
  error?: string | null;
};

export type Job = {
  id: string;
  type: string;
  title: string;
  status: "queued" | "running" | "done" | "error" | "cancelled" | string;
  progress: number;
  message: string | null;
  error: string | null;
  result: unknown;
  created_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
};

export type AppInfo = {
  app: { name: string; slug: string; version: string };
  data_dir: string;
  web_dist_exists: boolean;
  providers: { total: number; with_key: number; default: string | null };
  capabilities: number;
  tools: number;
  time: string;
};

export type EventItem = {
  id: number;
  kind: string;
  message: string;
  payload: string | null;
  created_at: string | null;
};

export type ToolInfo = {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  capability: string;
  scopes: string[];
  needs_confirm: boolean;
  capability_enabled: boolean;
};

export type Note = {
  id: number;
  title: string;
  content: string;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
};

export class ApiError extends Error {
  code: string;
  status: number;
  detail?: unknown;

  constructor(message: string, code = "error", status = 0, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    throw new ApiError(
      "无法连接到后端服务，请确认它正在运行（./scripts/start.sh）",
      "network_error",
      0,
      error,
    );
  }

  if (!response.ok) {
    let payload: { code?: string; message?: string; detail?: unknown } | null = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw new ApiError(
      payload?.message ?? `请求失败（HTTP ${response.status}）`,
      payload?.code ?? "http_error",
      response.status,
      payload?.detail,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ ok: boolean }>("/api/health"),
  info: () => request<AppInfo>("/api/info"),
  events: (limit = 12) => request<EventItem[]>(`/api/events?limit=${limit}`),
  tools: () => request<ToolInfo[]>("/api/tools"),

  capabilities: {
    list: () => request<CapabilityInfo[]>("/api/capabilities"),
    update: (id: string, body: { enabled?: boolean; settings?: Record<string, unknown> }) =>
      request<{ ok: boolean }>(`/api/capabilities/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  },

  providers: {
    list: () => request<Provider[]>("/api/providers"),
    create: (input: ProviderInput) =>
      request<Provider>("/api/providers", { method: "POST", body: JSON.stringify(input) }),
    update: (id: number, input: Partial<ProviderInput>) =>
      request<Provider>(`/api/providers/${id}`, { method: "PUT", body: JSON.stringify(input) }),
    remove: (id: number) => request<{ ok: boolean }>(`/api/providers/${id}`, { method: "DELETE" }),
    setDefault: (id: number) =>
      request<{ ok: boolean }>(`/api/providers/${id}/default`, { method: "POST" }),
    test: (id: number) => request<TestResult>(`/api/providers/${id}/test`, { method: "POST" }),
    models: (id: number) => request<{ models: string[] }>(`/api/providers/${id}/models`),
  },

  jobs: {
    list: () => request<Job[]>("/api/jobs"),
    get: (id: string) => request<Job>(`/api/jobs/${id}`),
    cancel: (id: string) => request<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
    streamUrl: "/api/jobs/stream/events",
  },

  settings: {
    get: () => request<Record<string, unknown>>("/api/settings"),
    update: (patch: Record<string, unknown>) =>
      request<{ ok: boolean }>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),
  },

  notes: {
    list: (q = "") =>
      request<Note[]>(`/api/c/notes/items${q ? `?q=${encodeURIComponent(q)}` : ""}`),
    create: (input: { title?: string; content: string; tags?: string }) =>
      request<Note>("/api/c/notes/items", { method: "POST", body: JSON.stringify(input) }),
    remove: (id: number) =>
      request<{ ok: boolean }>(`/api/c/notes/items/${id}`, { method: "DELETE" }),
  },
};
