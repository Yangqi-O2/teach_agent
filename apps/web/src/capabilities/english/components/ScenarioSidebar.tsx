import type { EnglishScenario } from "../../../lib/api";
import { cn } from "../../../lib/utils";
import { Icon } from "../../../components/Icon";
import { Button, Input } from "../../../components/ui/primitives";

const LEVELS = ["A2", "B1", "B2", "C1"];

function LevelSelect({ value, onChange, disabled }: { value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return (
    <div className="relative">
      <select
        aria-label="CEFR 等级"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full appearance-none rounded-xl border border-line bg-surface pl-3.5 pr-8 text-[13px] text-ink transition-colors focus:border-brand/60 focus:outline-none focus:ring-4 focus:ring-brand/10 disabled:opacity-50"
      >
        {LEVELS.map((level) => (
          <option key={level} value={level}>
            {level}
          </option>
        ))}
      </select>
      <Icon
        name="chevron-down"
        className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint"
      />
    </div>
  );
}

export function ScenarioSidebar({
  scenarios,
  currentId,
  domain,
  level,
  creating,
  loading,
  error,
  onDomainChange,
  onLevelChange,
  onCreate,
  onSelect,
  hideHeader = false,
}: {
  scenarios: EnglishScenario[];
  currentId: string | null;
  domain: string;
  level: string;
  creating: boolean;
  loading: boolean;
  error: string | null;
  onDomainChange: (value: string) => void;
  onLevelChange: (value: string) => void;
  onCreate: () => void;
  onSelect: (scenario: EnglishScenario) => void;
  hideHeader?: boolean;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      {hideHeader ? null : (
        <div className="border-b border-line px-4 py-3.5">
          <p className="flex items-center gap-1.5 text-[13.5px] font-medium text-ink">
            <Icon name="languages" className="h-4 w-4 text-brand" />
            情景
          </p>
          <p className="mt-0.5 text-[11.5px] text-ink-faint">选一个情景，用英文聊下去</p>
        </div>
      )}

      <div className="space-y-2.5 border-b border-line px-3.5 py-3.5">
        <Input
          value={domain}
          onChange={(event) => onDomainChange(event.target.value)}
          placeholder="想聊什么？例如「一带一路」"
          maxLength={60}
          className="py-2 text-[13px]"
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              onCreate();
            }
          }}
        />
        <div className="flex items-center gap-2">
          <LevelSelect value={level} onChange={onLevelChange} disabled={creating} />
          <Button
            variant="primary"
            size="sm"
            className="h-10 shrink-0 px-3.5"
            loading={creating}
            onClick={onCreate}
          >
            {creating ? "生成中…" : "生成情景"}
          </Button>
        </div>
        {error ? (
          <p className="flex items-start gap-1.5 rounded-lg bg-danger/10 px-2.5 py-2 text-[11.5px] leading-relaxed text-danger">
            <Icon name="alert-circle" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 break-words">{error}</span>
          </p>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        {loading ? (
          <div className="space-y-2 p-1">
            <div className="shimmer h-14 rounded-xl" />
            <div className="shimmer h-14 rounded-xl" />
            <div className="shimmer h-14 rounded-xl" />
          </div>
        ) : scenarios.length === 0 ? (
          <p className="px-3 py-8 text-center text-[12px] leading-relaxed text-ink-faint">
            还没有情景。
            <br />
            在上方输入一个领域，生成第一个情景。
          </p>
        ) : (
          scenarios.map((scenario) => {
            const active = scenario.id === currentId;
            return (
              <button
                key={scenario.id}
                type="button"
                onClick={() => onSelect(scenario)}
                aria-pressed={active}
                className={cn(
                  "w-full rounded-xl px-3 py-2.5 text-left transition-colors",
                  active
                    ? "bg-brand-soft/70 text-brand-strong"
                    : "text-ink hover:bg-surface-2",
                )}
              >
                <p className="flex items-center gap-1.5 truncate text-[13px] font-medium">
                  <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", active ? "bg-brand" : "bg-line")} />
                  {scenario.title_zh}
                </p>
                <p className="mt-0.5 truncate pl-3 text-[11px] text-ink-faint">
                  {scenario.domain} · {scenario.cefr} · {scenario.topic_count ?? 0} 个话题
                </p>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
