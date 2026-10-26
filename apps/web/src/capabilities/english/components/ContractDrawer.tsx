import { useEffect, useState } from "react";

import type { EnglishContract } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { Badge, Button, Input } from "../../../components/ui/primitives";
import { Drawer } from "./Drawer";

const INTENSITIES: { value: EnglishContract["correction_intensity"]; label: string }[] = [
  { value: "light", label: "轻 · 只报硬错" },
  { value: "medium", label: "中 · 常规纠错" },
  { value: "strict", label: "严 · 全都报" },
];

const DIFFICULTIES: { value: number; label: string }[] = [
  { value: -1, label: "简单一点" },
  { value: 0, label: "按我的水平" },
  { value: 1, label: "难一点" },
];

function splitWords(value: string): string[] {
  return value
    .split(/[,，、\s]+/)
    .map((word) => word.trim())
    .filter(Boolean);
}

export function ContractDrawer({
  open,
  onOpenChange,
  contract,
  loading,
  saving,
  warnings,
  onSave,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  contract: EnglishContract | null;
  loading: boolean;
  saving: boolean;
  warnings: string[];
  onSave: (contract: EnglishContract) => void;
  onRefresh: () => void;
}) {
  const [words, setWords] = useState("");
  const [grammar, setGrammar] = useState("");
  const [intensity, setIntensity] = useState<EnglishContract["correction_intensity"]>("medium");
  const [difficultyDelta, setDifficultyDelta] = useState(0);
  const [maxWords, setMaxWords] = useState(90);

  useEffect(() => {
    if (!contract) return;
    setWords((contract.must_use_words ?? []).join(", "));
    setGrammar((contract.grammar_focus ?? []).join(", "));
    setIntensity(contract.correction_intensity ?? "medium");
    setDifficultyDelta(contract.difficulty_delta ?? 0);
    setMaxWords(contract.max_reply_words ?? 90);
  }, [contract, open]);

  const submit = () => {
    if (!contract) return;
    onSave({
      ...contract,
      must_use_words: splitWords(words).slice(0, 3),
      grammar_focus: splitWords(grammar).slice(0, 3),
      correction_intensity: intensity,
      difficulty_delta: difficultyDelta,
      max_reply_words: maxWords,
    });
  };

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="偏好契约"
      subtitle="给 AI 提要求，保存后下一轮生效"
      footer={
        <Button variant="primary" size="md" className="w-full" loading={saving} disabled={!contract} onClick={submit}>
          <Icon name="check" className="h-4 w-4" />
          保存偏好
        </Button>
      }
    >
      {loading && !contract ? (
        <div className="space-y-3">
          <div className="shimmer h-10 rounded-xl" />
          <div className="shimmer h-10 rounded-xl" />
          <div className="shimmer h-10 rounded-xl" />
          <div className="shimmer h-10 rounded-xl" />
        </div>
      ) : !contract ? (
        <div className="rounded-xl bg-danger/10 p-3 text-[12.5px] leading-relaxed text-danger">
          偏好读取失败。
          <Button variant="ghost" size="sm" className="mt-2" onClick={onRefresh}>
            <Icon name="refresh-cw" className="h-3.5 w-3.5" />
            重试
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-[12px] text-ink-soft">想多用的词（逗号分隔，最多 3 个）</span>
            <Input value={words} onChange={(event) => setWords(event.target.value)} placeholder="例如：sustainable, infrastructure" />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[12px] text-ink-soft">语法重点（逗号分隔）</span>
            <Input value={grammar} onChange={(event) => setGrammar(event.target.value)} placeholder="例如：past perfect, articles" />
          </label>

          <div>
            <span className="mb-1.5 block text-[12px] text-ink-soft">纠错强度</span>
            <div className="grid grid-cols-3 gap-1.5">
              {INTENSITIES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setIntensity(option.value)}
                  aria-pressed={intensity === option.value}
                  className={
                    intensity === option.value
                      ? "rounded-xl border border-brand/40 bg-brand-soft/60 px-2 py-2 text-[11.5px] font-medium text-brand-strong"
                      : "rounded-xl border border-line bg-surface px-2 py-2 text-[11.5px] text-ink-soft transition-colors hover:bg-surface-2"
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="mb-1.5 block text-[12px] text-ink-soft">难度偏移</span>
            <div className="grid grid-cols-3 gap-1.5">
              {DIFFICULTIES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setDifficultyDelta(option.value)}
                  aria-pressed={difficultyDelta === option.value}
                  className={
                    difficultyDelta === option.value
                      ? "rounded-xl border border-brand/40 bg-brand-soft/60 px-2 py-2 text-[11.5px] font-medium text-brand-strong"
                      : "rounded-xl border border-line bg-surface px-2 py-2 text-[11.5px] text-ink-soft transition-colors hover:bg-surface-2"
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <label className="block">
            <span className="mb-1.5 flex items-center justify-between text-[12px] text-ink-soft">
              回复长度上限
              <Badge tone="brand">{maxWords} 词</Badge>
            </span>
            <input
              type="range"
              min={40}
              max={160}
              step={10}
              value={maxWords}
              onChange={(event) => setMaxWords(Number(event.target.value))}
              className="w-full accent-[var(--color-brand)]"
              aria-label="回复长度上限"
            />
          </label>

          {warnings.length ? (
            <div className="space-y-1 rounded-xl border border-amber/30 bg-amber/10 p-2.5 text-[11.5px] leading-relaxed text-amber">
              {warnings.map((warning, index) => (
                <p key={index}>· {warning}</p>
              ))}
            </div>
          ) : null}

          <p className="text-[11px] leading-relaxed text-ink-faint">
            偏好只影响自己账号下的对话；后端会校验并把越界值钳制到允许范围。
          </p>
        </div>
      )}
    </Drawer>
  );
}
