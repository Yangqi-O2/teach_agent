import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Icon } from "./Icon";
import { Badge, Button, Field, Input } from "./ui/primitives";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownSeparator,
  DropdownTrigger,
  Modal,
} from "./ui/overlay";
import { api } from "../lib/api";
import { useApp } from "../store/app";

function ChangePasswordModal({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const toast = useApp((s) => s.toast);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    if (next.length < 8) return setError("新密码至少 8 位");
    if (next !== confirm) return setError("两次输入的新密码不一致");
    setSaving(true);
    try {
      await api.auth.changePassword(current, next);
      toast({ title: "密码已更新", description: "其他设备上的登录已失效", tone: "success" });
      setCurrent("");
      setNext("");
      setConfirm("");
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="修改密码"
      description="修改后，该账号在其他设备上的登录会全部失效。"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={saving} onClick={submit}>
            保存
          </Button>
        </>
      }
    >
      <Field label="当前密码">
        <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
      </Field>
      <Field label="新密码" hint="至少 8 位">
        <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
      </Field>
      <Field label="确认新密码">
        <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
      </Field>
      {error ? (
        <p className="rounded-xl bg-danger/10 px-3 py-2 text-[12.5px] text-danger">{error}</p>
      ) : null}
    </Modal>
  );
}

export function UserMenu() {
  const user = useApp((s) => s.user);
  const logout = useApp((s) => s.logout);
  const toast = useApp((s) => s.toast);
  const navigate = useNavigate();
  const [passwordOpen, setPasswordOpen] = useState(false);

  if (!user) return null;
  const name = user.display_name || user.username;
  const initial = name.slice(0, 1).toUpperCase();

  const doLogout = async () => {
    await logout();
    toast({ title: "已退出登录", tone: "success" });
  };

  return (
    <>
      <Dropdown>
        <DropdownTrigger asChild>
          <button className="flex items-center gap-2 rounded-full border border-line bg-surface py-1 pl-1 pr-2.5 text-[12.5px] text-ink-soft transition-colors hover:border-brand/30 hover:text-ink">
            <span className="flex h-6.5 w-6.5 items-center justify-center rounded-full bg-gradient-to-br from-brand to-jade text-[11px] font-semibold text-canvas">
              {initial}
            </span>
            <span className="hidden max-w-24 truncate sm:block">{name}</span>
            <Icon name="chevron-right" className="h-3 w-3 rotate-90 opacity-60" />
          </button>
        </DropdownTrigger>
        <DropdownMenu align="end">
          <div className="px-2.5 py-2">
            <p className="text-[13px] font-medium text-ink">{name}</p>
            <p className="mt-0.5 text-[11.5px] text-ink-faint">@{user.username}</p>
            <div className="mt-1.5">
              <Badge tone={user.role === "admin" ? "brand" : "neutral"}>
                {user.role === "admin" ? "管理员" : "成员"}
              </Badge>
            </div>
          </div>
          <DropdownSeparator />
          <DropdownItem onSelect={() => setPasswordOpen(true)}>
            <Icon name="key-round" className="h-3.5 w-3.5" />
            修改密码
          </DropdownItem>
          {user.role === "admin" ? (
            <DropdownItem onSelect={() => navigate("/admin/users")}>
              <Icon name="users" className="h-3.5 w-3.5" />
              成员管理
            </DropdownItem>
          ) : null}
          <DropdownSeparator />
          <DropdownItem danger onSelect={doLogout}>
            <Icon name="log-out" className="h-3.5 w-3.5" />
            退出登录
          </DropdownItem>
        </DropdownMenu>
      </Dropdown>
      <ChangePasswordModal open={passwordOpen} onOpenChange={setPasswordOpen} />
    </>
  );
}
