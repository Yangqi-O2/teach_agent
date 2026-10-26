import { useMemo, useState } from "react";

import { Brand } from "../components/Brand";
import { Icon } from "../components/Icon";
import { ProfileForm, draftToInput, emptyDraft, type ProfileDraft } from "../components/ProfileForm";
import { Button } from "../components/ui/primitives";
import { useApp } from "../store/app";

/**
 * 注册第二步：完善个人资料。
 *
 * 为什么做成独立的整屏而不是塞在注册表单里：
 * 注册成功时 Cookie 已经下发、会话已建立，如果继续留在登录页，刷新一次就会
 * 丢掉刚填的内容。整屏引导由 App 按 `profile.onboarded` 决定是否拦截，
 * 中断也能续上。
 *
 * 「稍后再说」不是跳过校验，而是把 onboarded 置为 true 表示「已决定」，
 * 之后不再反复拦截；校园雷达页会常驻一个「完善资料」的入口。
 */

const WEIGHTS: [keyof ProfileDraft, number][] = [
  ["school", 30],
  ["grade", 20],
  ["department", 15],
  ["major", 15],
  ["interests", 20],
];

function completeness(draft: ProfileDraft): number {
  return WEIGHTS.reduce((sum, [key, weight]) => {
    const value = draft[key];
    const filled = Array.isArray(value) ? value.length > 0 : Boolean(value && value.trim());
    return sum + (filled ? weight : 0);
  }, 0);
}

export function OnboardingPage() {
  const user = useApp((s) => s.user);
  const profile = useApp((s) => s.profile);
  const saveProfile = useApp((s) => s.saveProfile);
  const [draft, setDraft] = useState<ProfileDraft>(() => emptyDraft(profile));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const score = useMemo(() => completeness(draft), [draft]);

  const submit = async (skip = false) => {
    setError(null);
    setSaving(true);
    try {
      if (skip) await saveProfile({ onboarded: true });
      else await saveProfile(draftToInput(draft, { onboarded: true }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas">
      <div className="mx-auto flex max-w-3xl flex-col px-5 py-10 md:py-14">
        <div className="flex items-center justify-between">
          <Brand />
          <span className="text-[11.5px] tracking-wide text-ink-faint">第 2 步 / 共 2 步</span>
        </div>

        <div className="mt-8">
          <div className="flex items-center gap-2">
            <span className="h-1 w-16 rounded-full bg-brand" />
            <span className="h-1 w-16 rounded-full bg-brand" />
          </div>
          <h1 className="mt-5 font-display text-[28px] font-semibold tracking-tight text-ink">
            {user?.display_name ? `${user.display_name}，` : ""}再补两句就完整了
          </h1>
          <p className="mt-2 max-w-xl text-[13.5px] leading-relaxed text-ink-soft">
            这些信息只存在你自己的机器上，用来决定「哪些通知跟你有关」。
            不填也能用，只是推荐会按通用情况给。
          </p>
        </div>

        <div className="mt-6 rounded-2xl border border-line bg-surface p-5 md:p-6">
          <div className="mb-5 flex items-center justify-between gap-4">
            <p className="text-[13px] font-medium text-ink">个人资料完整度</p>
            <div className="flex flex-1 items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-brand transition-all duration-300"
                  style={{ width: `${score}%` }}
                />
              </div>
              <span className="w-10 text-right text-[12px] tabular-nums text-ink-faint">{score}%</span>
            </div>
          </div>

          <ProfileForm draft={draft} onChange={setDraft} />

          {error ? (
            <div className="mt-4 flex items-start gap-2 rounded-xl bg-danger/10 px-3 py-2.5 text-[12.5px] leading-relaxed text-danger">
              <Icon name="alert-circle" className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => submit(true)}
              disabled={saving}
              className="text-[12.5px] text-ink-faint underline-offset-4 transition-colors hover:text-ink hover:underline disabled:opacity-50"
            >
              先跳过，稍后填
            </button>
            <Button variant="primary" size="lg" loading={saving} onClick={() => submit(false)}>
              完成，进入天健湖
              <Icon name="arrow-up-right" className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <p className="mt-5 text-[11.5px] leading-relaxed text-ink-faint">
          随时可以在「校园雷达」页或「设置」里修改。资料不会上传到任何第三方服务。
        </p>
      </div>
    </div>
  );
}
