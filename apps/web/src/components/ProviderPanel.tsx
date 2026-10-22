import { useState } from "react";

import { Icon } from "./Icon";
import { Button, Badge, EmptyState, Field, Input } from "./ui/primitives";
import { Dropdown, DropdownItem, DropdownMenu, DropdownSeparator, DropdownTrigger, Modal } from "./ui/overlay";
import { api, type Provider, type TestResult } from "../lib/api";
import { cn } from "../lib/utils";
import { useApp } from "../store/app";

type FormState = {
  name: string;
  base_url: string;
  api_key: string;
  chat_model: string;
  embed_model: string;
};

const EMPTY_FORM: FormState = { name: "", base_url: "", api_key: "", chat_model: "", embed_model: "" };

const PRESETS = [
  { label: "DeepSeek", name: "DeepSeek", base_url: "https://api.deepseek.com/v1", chat_model: "deepseek-chat" },
  { label: "Kimi", name: "Moonshot", base_url: "https://api.moonshot.cn/v1", chat_model: "moonshot-v1-8k" },
  { label: "通义千问", name: "通义千问", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", chat_model: "qwen-plus" },
  { label: "硅基流动", name: "硅基流动", base_url: "https://api.siliconflow.cn/v1", chat_model: "deepseek-ai/DeepSeek-V3" },
  { label: "OpenAI", name: "OpenAI", base_url: "https://api.openai.com/v1", chat_model: "gpt-4o-mini" },
  { label: "Ollama 本地", name: "Ollama", base_url: "http://127.0.0.1:11434/v1", chat_model: "qwen2.5:7b" },
];

export function ProviderPanel() {
  const providers = useApp((s) => s.providers);
  const refresh = useApp((s) => s.refreshProviders);
  const toast = useApp((s) => s.toast);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const [results, setResults] = useState<Record<number, TestResult>>({});
  const [deleteTarget, setDeleteTarget] = useState<Provider | null>(null);

  const openCreate = (preset?: (typeof PRESETS)[number]) => {
    setEditing(null);
    setForm(preset ? { ...EMPTY_FORM, ...preset, api_key: "" } : EMPTY_FORM);
    setFormOpen(true);
  };

  const openEdit = (provider: Provider) => {
    setEditing(provider);
    setForm({
      name: provider.name,
      base_url: provider.base_url,
      api_key: "",
      chat_model: provider.chat_model,
      embed_model: provider.embed_model ?? "",
    });
    setFormOpen(true);
  };

  const submit = async () => {
    if (!form.name.trim() || !form.base_url.trim()) {
      toast({ title: "名称和 Base URL 不能为空", tone: "error" });
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        const payload: Record<string, string> = {
          name: form.name,
          base_url: form.base_url,
          chat_model: form.chat_model,
          embed_model: form.embed_model,
        };
        if (form.api_key.trim()) payload.api_key = form.api_key.trim();
        await api.providers.update(editing.id, payload);
        toast({ title: "已更新供应商", tone: "success" });
      } else {
        await api.providers.create({
          name: form.name,
          base_url: form.base_url,
          api_key: form.api_key.trim(),
          chat_model: form.chat_model,
          embed_model: form.embed_model || null,
        });
        toast({ title: "已添加供应商", description: "建议点一下「测试连接」确认可用", tone: "success" });
      }
      setFormOpen(false);
      await refresh();
    } catch (error) {
      toast({ title: "保存失败", description: error instanceof Error ? error.message : String(error), tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  const test = async (provider: Provider) => {
    setTesting(provider.id);
    try {
      const result = await api.providers.test(provider.id);
      setResults((prev) => ({ ...prev, [provider.id]: result }));
      toast({
        title: result.ok ? "连接正常" : "连接失败",
        description: result.ok
          ? `${result.latency_ms} ms · ${result.models.length} 个模型可用`
          : result.error ?? "请检查 Base URL、Key 与模型名",
        tone: result.ok ? "success" : "error",
      });
    } catch (error) {
      toast({ title: "测试失败", description: error instanceof Error ? error.message : String(error), tone: "error" });
    } finally {
      setTesting(null);
    }
  };

  const setDefault = async (provider: Provider) => {
    try {
      await api.providers.setDefault(provider.id);
      await refresh();
      toast({ title: `已把「${provider.name}」设为默认`, tone: "success" });
    } catch (error) {
      toast({ title: "设置失败", description: String(error), tone: "error" });
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      await api.providers.remove(deleteTarget.id);
      setDeleteTarget(null);
      await refresh();
      toast({ title: "已删除供应商", tone: "success" });
    } catch (error) {
      toast({ title: "删除失败", description: String(error), tone: "error" });
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-[17px] font-semibold text-ink">模型供应商</h2>
          <p className="mt-1 text-[12.5px] text-ink-faint">
            任何 OpenAI 兼容端点都能接入；API Key 只以密文保存在本机。
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => openCreate()}>
          <Icon name="plus" className="h-3.5 w-3.5" />
          添加供应商
        </Button>
      </div>

      {providers.length === 0 ? (
        <EmptyState
          icon="cpu"
          title="还没有配置模型"
          description="填一个 OpenAI 兼容的 Base URL 和 API Key 就能开始。下面是一些常用端点，点一下自动填好。"
          action={
            <div className="flex max-w-md flex-wrap justify-center gap-2">
              {PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  onClick={() => openCreate(preset)}
                  className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-[12.5px] text-ink-soft transition-colors hover:border-brand/30 hover:text-ink"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          }
        />
      ) : (
        <div className="grid gap-4">
          {providers.map((provider) => {
            const result = results[provider.id];
            return (
              <div key={provider.id} className="card p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
                      <Icon name="server" className="h-[18px] w-[18px]" />
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-[14.5px] font-semibold text-ink">{provider.name}</h3>
                        {provider.is_default ? <Badge tone="brand">默认</Badge> : null}
                        {provider.has_key ? <Badge tone="jade">Key 已加密保存</Badge> : <Badge tone="amber">缺少 Key</Badge>}
                      </div>
                      <p className="mt-1 truncate font-mono text-[11.5px] text-ink-faint">{provider.base_url}</p>
                    </div>
                  </div>
                  <Dropdown>
                    <DropdownTrigger asChild>
                      <button className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink">
                        <Icon name="chevron-right" className="h-4 w-4 rotate-90" />
                      </button>
                    </DropdownTrigger>
                    <DropdownMenu>
                      {!provider.is_default ? <DropdownItem onSelect={() => setDefault(provider)}>设为默认</DropdownItem> : null}
                      <DropdownItem onSelect={() => openEdit(provider)}>编辑</DropdownItem>
                      <DropdownItem onSelect={() => test(provider)}>测试连接</DropdownItem>
                      <DropdownSeparator />
                      <DropdownItem danger onSelect={() => setDeleteTarget(provider)}>
                        删除
                      </DropdownItem>
                    </DropdownMenu>
                  </Dropdown>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-xl bg-surface-2 px-3 py-2">
                    <p className="text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">对话模型</p>
                    <p className="mt-0.5 truncate font-mono text-[12px] text-ink">{provider.chat_model || "未填写"}</p>
                  </div>
                  <div className="rounded-xl bg-surface-2 px-3 py-2">
                    <p className="text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">向量模型</p>
                    <p className="mt-0.5 truncate font-mono text-[12px] text-ink">{provider.embed_model || "未填写（可后补）"}</p>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line/70 pt-3">
                  <span className="font-mono text-[11px] text-ink-faint">
                    {provider.key_hint ? `Key ${provider.key_hint}` : "Key 通过本机密钥加密"}
                  </span>
                  <Button variant="secondary" size="sm" loading={testing === provider.id} onClick={() => test(provider)}>
                    测试连接
                  </Button>
                </div>

                {result ? (
                  <div
                    className={cn(
                      "mt-3 rounded-xl px-3 py-2 text-[12px]",
                      result.ok ? "bg-jade/10 text-jade" : "bg-danger/10 text-danger",
                    )}
                  >
                    {result.ok
                      ? `连接正常 · ${result.latency_ms} ms · 可用模型 ${result.models.length} 个`
                      : result.error ?? "连接失败"}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      <Modal
        open={formOpen}
        onOpenChange={setFormOpen}
        title={editing ? "编辑供应商" : "添加供应商"}
        description="只需要一个 OpenAI 兼容的 Base URL。保存后可以点「测试连接」验证。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setFormOpen(false)}>
              取消
            </Button>
            <Button variant="primary" loading={saving} onClick={submit}>
              {editing ? "保存修改" : "添加"}
            </Button>
          </>
        }
      >
        {!editing ? (
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((preset) => (
              <button
                key={preset.label}
                onClick={() => setForm((prev) => ({ ...prev, ...preset }))}
                className="rounded-full border border-line px-2.5 py-1 text-[11.5px] text-ink-soft transition-colors hover:border-brand/30 hover:text-ink"
              >
                {preset.label}
              </button>
            ))}
          </div>
        ) : null}

        <Field label="名称">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如 DeepSeek" />
        </Field>
        <Field label="Base URL" hint="需要包含 /v1；保存时会自动补全缺失的 /v1。">
          <Input
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            placeholder="https://api.deepseek.com/v1"
            className="font-mono"
          />
        </Field>
        <Field
          label="API Key"
          hint={editing ? "留空表示不修改；填新值会覆盖。" : "只保存在本机，加密存储，界面上永远不显示明文。"}
        >
          <Input
            type="password"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            placeholder={editing ? "留空则不修改" : "sk-…"}
            className="font-mono"
            autoComplete="off"
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="对话模型">
            <Input
              value={form.chat_model}
              onChange={(e) => setForm({ ...form, chat_model: e.target.value })}
              placeholder="deepseek-chat"
              className="font-mono"
            />
          </Field>
          <Field label="向量模型（可选）">
            <Input
              value={form.embed_model}
              onChange={(e) => setForm({ ...form, embed_model: e.target.value })}
              placeholder="text-embedding-3-small"
              className="font-mono"
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="删除供应商？"
        description={`「${deleteTarget?.name ?? ""}」的配置会被移除，已存的 API Key 密文一并删除。`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button variant="danger" onClick={remove}>
              删除
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-ink-soft">教材、速记等数据不受影响。</p>
      </Modal>
    </div>
  );
}
