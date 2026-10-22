import { useState } from "react";

import { Icon } from "./Icon";
import { Badge, Button, Field, Input, Switch } from "./ui/primitives";
import { api, type CapabilityInfo, type SettingProp } from "../lib/api";
import { cn } from "../lib/utils";
import { useApp } from "../store/app";

function SchemaField({
  name,
  prop,
  value,
  onChange,
}: {
  name: string;
  prop: SettingProp;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = prop.title ?? name;
  const hint = prop.description;
  if (prop.type === "boolean") {
    return (
      <div className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-2.5">
        <div>
          <p className="text-[13px] text-ink">{label}</p>
          {hint ? <p className="text-[11.5px] text-ink-faint">{hint}</p> : null}
        </div>
        <Switch checked={Boolean(value)} onCheckedChange={onChange} />
      </div>
    );
  }
  if (prop.type === "number" || prop.type === "integer") {
    return (
      <Field label={label} hint={hint}>
        <Input
          type="number"
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => onChange(prop.type === "integer" ? parseInt(e.target.value || "0", 10) : Number(e.target.value))}
        />
      </Field>
    );
  }
  if (prop.enum?.length) {
    return (
      <Field label={label} hint={hint}>
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-ink focus:border-brand/60 focus:outline-none"
        >
          {prop.enum.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </Field>
    );
  }
  return (
    <Field label={label} hint={hint}>
      <Input value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

function CapabilityRow({ cap }: { cap: CapabilityInfo }) {
  const refresh = useApp((s) => s.refreshCapabilities);
  const toast = useApp((s) => s.toast);
  const [enabled, setEnabled] = useState(cap.enabled);
  const [settings, setSettings] = useState<Record<string, unknown>>({ ...cap.settings });
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const properties = cap.settings_schema?.properties ?? {};
  const hasSettings = Object.keys(properties).length > 0;

  const toggle = async (next: boolean) => {
    setEnabled(next);
    try {
      await api.capabilities.update(cap.id, { enabled: next });
      await refresh();
      toast({ title: next ? `已启用「${cap.name}」` : `已禁用「${cap.name}」`, tone: "success" });
    } catch (error) {
      setEnabled(!next);
      toast({ title: "操作失败", description: String(error), tone: "error" });
    }
  };

  const saveSettings = async () => {
    setSaving(true);
    try {
      await api.capabilities.update(cap.id, { settings });
      await refresh();
      toast({ title: "设置已保存", tone: "success" });
    } catch (error) {
      toast({ title: "保存失败", description: String(error), tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={cn("card overflow-hidden transition-opacity", !enabled && "opacity-70")}>
      <div className="flex items-start gap-4 p-5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-strong">
          <Icon name={cap.icon} className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-[15.5px] font-semibold text-ink">{cap.name}</h3>
            <Badge tone="outline">v{cap.version}</Badge>
            {cap.has_tools ? <Badge tone="brand">Agent 工具</Badge> : null}
            {hasSettings ? <Badge tone="neutral">可配置</Badge> : null}
          </div>
          <p className="mt-1.5 text-[13px] leading-relaxed text-ink-soft">{cap.description}</p>
          {cap.nav ? (
            <p className="mt-2 font-mono text-[11px] text-ink-faint">
              {cap.nav.path} · 排序 {cap.nav.order}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          {hasSettings ? (
            <button
              onClick={() => setOpen((value) => !value)}
              className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
              aria-label="展开设置"
            >
              <Icon name={open ? "x" : "settings"} className="h-4 w-4" />
            </button>
          ) : null}
          <Switch checked={enabled} onCheckedChange={toggle} />
        </div>
      </div>

      {hasSettings && open ? (
        <div className="border-t border-line/70 bg-surface-2/40 p-5">
          <p className="mb-3 text-[11px] uppercase tracking-[0.16em] text-ink-faint">
            由 settings_schema 自动渲染
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            {Object.entries(properties).map(([key, prop]) => (
              <SchemaField
                key={key}
                name={key}
                prop={prop}
                value={settings[key] ?? prop.default}
                onChange={(value) => setSettings((prev) => ({ ...prev, [key]: value }))}
              />
            ))}
          </div>
          <div className="mt-4 flex justify-end">
            <Button size="sm" variant="primary" loading={saving} onClick={saveSettings}>
              保存设置
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function CapabilityPanel() {
  const capabilities = useApp((s) => s.capabilities);
  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-[17px] font-semibold text-ink">能力管理</h2>
        <p className="mt-1 text-[12.5px] leading-relaxed text-ink-faint">
          能力是独立的插件：自带页面、接口、数据库迁移与 Agent 工具。禁用后导航消失、工具不再暴露；数据会保留。
        </p>
      </div>
      {capabilities.map((cap) => (
        <CapabilityRow key={cap.id} cap={cap} />
      ))}
      <div className="rounded-card border border-dashed border-line p-5">
        <p className="text-[13px] font-medium text-ink">新增一个能力</p>
        <p className="mt-1 text-[12.5px] leading-relaxed text-ink-faint">
          在 <span className="font-mono">apps/server</span> 下执行，生成前后端骨架后重启即可：
        </p>
        <pre className="mt-3 overflow-x-auto rounded-xl bg-surface-2 p-3 font-mono text-[11.5px] leading-relaxed text-ink-soft">
          python -m app.cli new-capability my-feature --name 我的能力 --icon sparkles
        </pre>
      </div>
    </div>
  );
}
