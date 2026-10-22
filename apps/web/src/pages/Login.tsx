import { useState } from "react";

import { Brand } from "../components/Brand";
import { Icon } from "../components/Icon";
import { Button, Field, Input } from "../components/ui/primitives";
import { ThemeToggle } from "../app/ThemeToggle";
import { useApp } from "../store/app";

type Mode = "login" | "register";

const FEATURES = [
  { icon: "library", title: "教材问答", desc: "上传课件与教材，答案带页码引用" },
  { icon: "radar", title: "校园雷达", desc: "订阅教务处通知，别错过竞赛与截止" },
  { icon: "brain", title: "联想记忆", desc: "把知识点长在你的兴趣上，按曲线复习" },
];

export function LoginPage() {
  const login = useApp((s) => s.login);
  const register = useApp((s) => s.register);
  const authConfig = useApp((s) => s.authConfig);

  const [mode, setMode] = useState<Mode>(() => (authConfig?.has_users ? "login" : "register"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const allowRegistration = authConfig?.allow_registration ?? true;
  const firstRun = !authConfig?.has_users;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (mode === "register") {
      if (username.trim().length < 3) return setError("用户名至少 3 位");
      if (password.length < 8) return setError("密码至少 8 位");
    }
    setLoading(true);
    try {
      if (mode === "login") await login(username.trim(), password);
      else await register(username.trim(), password, displayName.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
  };

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[1.02fr_1fr]">
      {/* 品牌面板 */}
      <aside className="relative hidden overflow-hidden bg-[#0b3540] p-12 text-[#eef6f4] lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_100%_at_0%_0%,#17687a_0%,transparent_60%),radial-gradient(90%_90%_at_100%_100%,#1f7d6c_0%,transparent_55%)] opacity-90" />
        <svg
          className="pointer-events-none absolute -right-28 top-1/2 h-[560px] w-[560px] -translate-y-1/2 text-white/10"
          viewBox="0 0 200 200"
          fill="none"
          stroke="currentColor"
          aria-hidden
        >
          {[36, 58, 80, 102, 124, 146].map((r, i) => (
            <circle key={r} cx="100" cy="100" r={r} strokeWidth={i === 0 ? 1.6 : 1} opacity={0.9 - i * 0.12} />
          ))}
        </svg>

        <div className="relative z-10">
          <Brand />
        </div>

        <div className="relative z-10 max-w-md">
          <p className="text-[11.5px] uppercase tracking-[0.28em] text-white/50">Personal study companion</p>
          <h1 className="mt-4 font-display text-[40px] font-semibold leading-[1.2] tracking-tight">
            把知识，
            <br />
            收进一片湖里。
          </h1>
          <p className="mt-4 text-[13.5px] leading-relaxed text-white/65">
            教材、通知和记忆都在一个地方。账号之间彼此独立，每个人的数据只属于自己。
          </p>

          <div className="mt-10 space-y-4">
            {FEATURES.map((feature) => (
              <div key={feature.title} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-white/85">
                  <Icon name={feature.icon} className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-[13px] font-medium">{feature.title}</p>
                  <p className="text-[12px] leading-relaxed text-white/55">{feature.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="relative z-10 text-[11.5px] text-white/40">
          本地优先 · 数据保存在你自己的机器上 · API Key 加密存储
        </p>
      </aside>

      {/* 表单面板 */}
      <main className="relative flex min-h-screen flex-col items-center justify-center bg-canvas px-5 py-12">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>

        <div className="w-full max-w-[380px]">
          <div className="mb-8 lg:hidden">
            <Brand />
          </div>

          <div className="mb-6">
            <h2 className="font-display text-[26px] font-semibold tracking-tight text-ink">
              {mode === "login" ? "欢迎回来" : firstRun ? "创建第一个账号" : "加入天健湖"}
            </h2>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink-soft">
              {mode === "login"
                ? "登录后继续你的学习进度。"
                : firstRun
                  ? "第一个注册的账号会成为管理员，可以管理其他成员。"
                  : "注册后拥有独立的教材、通知与记忆空间。"}
            </p>
          </div>

          {allowRegistration || mode === "login" ? (
            <div className="mb-5 inline-flex rounded-full border border-line bg-surface-2 p-1">
              <button
                onClick={() => switchMode("login")}
                className={`rounded-full px-4 py-1.5 text-[12.5px] font-medium transition-colors ${
                  mode === "login" ? "bg-surface text-ink shadow-sm" : "text-ink-faint hover:text-ink"
                }`}
              >
                登录
              </button>
              <button
                onClick={() => switchMode("register")}
                disabled={!allowRegistration && !firstRun}
                className={`rounded-full px-4 py-1.5 text-[12.5px] font-medium transition-colors disabled:opacity-40 ${
                  mode === "register" ? "bg-surface text-ink shadow-sm" : "text-ink-faint hover:text-ink"
                }`}
              >
                注册
              </button>
            </div>
          ) : null}

          <form onSubmit={submit} className="space-y-4">
            <Field label="用户名" hint={mode === "register" ? "3–24 位字母、数字或下划线" : undefined}>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="例如 xiaoming"
                autoComplete="username"
                autoFocus
              />
            </Field>

            {mode === "register" ? (
              <Field label="昵称" hint="显示在界面上的名字，可留空">
                <Input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="例如 小明"
                  autoComplete="nickname"
                />
              </Field>
            ) : null}

            <Field label="密码" hint={mode === "register" ? "至少 8 位" : undefined}>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </Field>

            {error ? (
              <div className="flex items-start gap-2 rounded-xl bg-danger/10 px-3 py-2.5 text-[12.5px] leading-relaxed text-danger">
                <Icon name="alert-circle" className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}

            <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading}>
              {mode === "login" ? "登录" : "注册并进入"}
              <Icon name="arrow-up-right" className="h-4 w-4" />
            </Button>
          </form>

          {!allowRegistration && mode === "register" ? (
            <p className="mt-5 rounded-xl bg-surface-2 px-3 py-2.5 text-[12px] leading-relaxed text-ink-faint">
              站点已关闭注册。请联系管理员为你开通账号。
            </p>
          ) : null}

          <p className="mt-8 text-center text-[11.5px] leading-relaxed text-ink-faint">
            登录即表示你了解：所有数据保存在这台机器上，不会上传到第三方。
          </p>
        </div>
      </main>
    </div>
  );
}
