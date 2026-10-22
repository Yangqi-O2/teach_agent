import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";

import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Badge, Button, EmptyState, Field, Input, Switch } from "../components/ui/primitives";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownSeparator,
  DropdownTrigger,
  Modal,
} from "../components/ui/overlay";
import { api, type AdminUser } from "../lib/api";
import { relativeTime } from "../lib/utils";
import { useApp } from "../store/app";

function initials(name: string) {
  return (name || "?").slice(0, 1).toUpperCase();
}

export function AdminUsers() {
  const me = useApp((s) => s.user);
  const toast = useApp((s) => s.toast);

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [registration, setRegistration] = useState(true);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "user" });
  const [creating, setCreating] = useState(false);

  const [pwdTarget, setPwdTarget] = useState<AdminUser | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, config] = await Promise.all([api.admin.users(), api.auth.config()]);
      setUsers(list);
      setRegistration(config.allow_registration);
    } catch (error) {
      toast({
        title: "加载成员失败",
        description: error instanceof Error ? error.message : String(error),
        tone: "error",
      });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    if (me?.role === "admin") load();
  }, [load, me?.role]);

  if (me?.role !== "admin") return <Navigate to="/" replace />;

  const patch = async (target: AdminUser, body: { role?: string; is_active?: boolean; display_name?: string }) => {
    try {
      await api.admin.updateUser(target.id, body);
      await load();
      toast({ title: "已更新", tone: "success" });
    } catch (error) {
      toast({ title: "更新失败", description: error instanceof Error ? error.message : String(error), tone: "error" });
    }
  };

  const create = async () => {
    if (!form.username.trim() || !form.password) {
      toast({ title: "用户名和密码不能为空", tone: "error" });
      return;
    }
    setCreating(true);
    try {
      await api.admin.createUser({
        username: form.username.trim(),
        password: form.password,
        display_name: form.display_name.trim(),
        role: form.role,
      });
      setCreateOpen(false);
      setForm({ username: "", display_name: "", password: "", role: "user" });
      await load();
      toast({ title: "成员已创建", description: "把用户名和初始密码告诉对方即可", tone: "success" });
    } catch (error) {
      toast({ title: "创建失败", description: error instanceof Error ? error.message : String(error), tone: "error" });
    } finally {
      setCreating(false);
    }
  };

  const resetPassword = async () => {
    if (!pwdTarget) return;
    if (newPassword.length < 8) {
      toast({ title: "密码至少 8 位", tone: "error" });
      return;
    }
    try {
      await api.admin.resetPassword(pwdTarget.id, newPassword);
      setPwdTarget(null);
      setNewPassword("");
      toast({ title: "密码已重置", description: "对方需要用新密码重新登录", tone: "success" });
    } catch (error) {
      toast({ title: "重置失败", description: error instanceof Error ? error.message : String(error), tone: "error" });
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      await api.admin.removeUser(deleteTarget.id);
      setDeleteTarget(null);
      await load();
      toast({ title: "成员已删除", tone: "success" });
    } catch (error) {
      toast({ title: "删除失败", description: error instanceof Error ? error.message : String(error), tone: "error" });
    }
  };

  const toggleRegistration = async (allow: boolean) => {
    setRegistration(allow);
    try {
      await api.admin.setRegistration(allow);
      toast({ title: allow ? "已开放注册" : "已关闭注册", tone: "success" });
    } catch (error) {
      setRegistration(!allow);
      toast({ title: "设置失败", description: error instanceof Error ? error.message : String(error), tone: "error" });
    }
  };

  const admins = users.filter((u) => u.role === "admin").length;
  const active = users.filter((u) => u.is_active).length;

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="管理"
        title="成员管理"
        description="每个成员拥有独立的供应商、速记、简报与任务数据；禁用或删除成员会立即失效其登录。"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <Icon name="user-plus" className="h-4 w-4" />
            新建成员
          </Button>
        }
      />

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        {[
          { label: "成员总数", value: users.length, icon: "users" },
          { label: "管理员", value: admins, icon: "shield" },
          { label: "启用中", value: active, icon: "check" },
        ].map((stat) => (
          <div key={stat.label} className="card flex items-center gap-3 p-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-soft text-brand-strong">
              <Icon name={stat.icon} className="h-4 w-4" />
            </span>
            <div>
              <p className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">{stat.label}</p>
              <p className="text-[17px] font-semibold text-ink">{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="card mb-6 flex flex-wrap items-center justify-between gap-4 p-5">
        <div>
          <p className="text-[13.5px] font-medium text-ink">开放自助注册</p>
          <p className="mt-0.5 text-[12.5px] text-ink-faint">
            关闭后，新用户只能由管理员在「新建成员」里创建；已登录用户不受影响。
          </p>
        </div>
        <Switch checked={registration} onCheckedChange={toggleRegistration} />
      </div>

      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card shimmer h-20" />
          ))}
        </div>
      ) : users.length === 0 ? (
        <EmptyState icon="users" title="还没有成员" description="新建一个成员，或开放注册让别人自己注册。" />
      ) : (
        <div className="stagger space-y-3">
          {users.map((member) => (
            <div key={member.id} className="card flex flex-wrap items-center gap-4 p-4">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand to-jade text-[13px] font-semibold text-canvas">
                {initials(member.display_name || member.username)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-[14px] font-medium text-ink">{member.display_name || member.username}</p>
                  <span className="text-[11.5px] text-ink-faint">@{member.username}</span>
                  <Badge tone={member.role === "admin" ? "brand" : "neutral"}>
                    {member.role === "admin" ? "管理员" : "成员"}
                  </Badge>
                  {!member.is_active ? <Badge tone="danger">已停用</Badge> : null}
                  {member.id === me?.id ? <Badge tone="jade">你</Badge> : null}
                </div>
                <p className="mt-1 text-[11.5px] text-ink-faint">
                  上次登录 {relativeTime(member.last_login_at)} · 供应商 {member.providers} 个 · 任务 {member.jobs} 个
                </p>
              </div>

              <Dropdown>
                <DropdownTrigger asChild>
                  <button className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] text-ink-soft transition-colors hover:text-ink">
                    操作
                    <Icon name="chevron-right" className="ml-1 inline h-3 w-3 rotate-90" />
                  </button>
                </DropdownTrigger>
                <DropdownMenu>
                  <DropdownItem onSelect={() => setPwdTarget(member)}>重置密码</DropdownItem>
                  <DropdownItem
                    onSelect={() =>
                      patch(member, { role: member.role === "admin" ? "user" : "admin" })
                    }
                  >
                    {member.role === "admin" ? "设为普通成员" : "设为管理员"}
                  </DropdownItem>
                  <DropdownItem
                    onSelect={() => patch(member, { is_active: !member.is_active })}
                  >
                    {member.is_active ? "停用账号" : "启用账号"}
                  </DropdownItem>
                  <DropdownSeparator />
                  <DropdownItem danger onSelect={() => setDeleteTarget(member)}>
                    删除成员
                  </DropdownItem>
                </DropdownMenu>
              </Dropdown>
            </div>
          ))}
        </div>
      )}

      {/* 新建成员 */}
      <Modal
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="新建成员"
        description="创建一个账号并设置初始密码；对方登录后可以自行修改。"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button variant="primary" loading={creating} onClick={create}>
              创建
            </Button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="用户名" hint="3–24 位字母、数字或下划线">
            <Input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              placeholder="xiaoming"
              autoComplete="off"
            />
          </Field>
          <Field label="昵称" hint="可留空">
            <Input
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              placeholder="小明"
            />
          </Field>
        </div>
        <Field label="初始密码" hint="至少 8 位">
          <Input
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            placeholder="至少 8 位"
            autoComplete="new-password"
          />
        </Field>
        <Field label="角色">
          <select
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
            className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-sm text-ink focus:border-brand/60 focus:outline-none"
          >
            <option value="user">普通成员</option>
            <option value="admin">管理员</option>
          </select>
        </Field>
      </Modal>

      {/* 重置密码 */}
      <Modal
        open={Boolean(pwdTarget)}
        onOpenChange={(open) => !open && setPwdTarget(null)}
        title={`重置 ${pwdTarget?.display_name || pwdTarget?.username || ""} 的密码`}
        description="重置后，对方所有已登录设备会立刻失效。"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPwdTarget(null)}>
              取消
            </Button>
            <Button variant="primary" onClick={resetPassword}>
              重置
            </Button>
          </>
        }
      >
        <Field label="新密码" hint="至少 8 位">
          <Input value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" />
        </Field>
      </Modal>

      {/* 删除 */}
      <Modal
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="删除成员？"
        description={`将删除「${deleteTarget?.display_name || deleteTarget?.username || ""}」及其全部个人数据（供应商、速记、简报、任务），此操作不可恢复。`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button variant="danger" onClick={remove}>
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-[13px] text-ink-soft">如果只是想暂时禁止登录，建议用「停用账号」。</p>
      </Modal>
    </div>
  );
}
