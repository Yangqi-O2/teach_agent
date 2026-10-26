import type { EnglishGrammarError, EnglishKnowledgeCard } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { Markdown } from "./Markdown";

/** 用户消息下方的纠错知识卡（点下划线后出现，不用弹窗打断阅读） */
export function ErrorCard({
  error,
  card,
  loading,
  onClose,
}: {
  error: EnglishGrammarError;
  card: EnglishKnowledgeCard | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <div className="ml-auto mt-1 w-full max-w-[88%] rounded-xl border border-line bg-surface p-3.5 text-left shadow-soft">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-1.5 text-[12px] text-ink-soft">
            <span className="rounded bg-danger/10 px-1.5 py-0.5 font-medium text-danger">
              {error.correction}
            </span>
            <span className="min-w-0 break-words">{error.explain_zh}</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
          aria-label="关闭知识卡"
        >
          <Icon name="x" className="h-3.5 w-3.5" />
        </button>
      </div>

      {loading ? (
        <div className="space-y-2" aria-label="正在生成知识卡">
          <div className="shimmer h-3 w-1/2 rounded-full" />
          <div className="shimmer h-3 w-5/6 rounded-full" />
          <div className="shimmer h-16 rounded-lg" />
        </div>
      ) : card ? (
        <>
          <p className="text-[13.5px] font-medium text-ink">{card.title}</p>
          <Markdown content={card.rule_md} className="mt-1 text-[13px] text-ink-soft" />
          {card.examples?.length ? (
            <div className="mt-2 space-y-1.5">
              {card.examples.map((example, index) => (
                <div key={index} className="rounded-lg bg-surface-2 px-2.5 py-2 text-[12px]">
                  <p className="text-danger line-through">{example.wrong}</p>
                  <p className="text-jade">{example.right}</p>
                  {example.note ? <p className="mt-0.5 text-ink-faint">{example.note}</p> : null}
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <p className="text-[12px] text-ink-faint">知识卡暂时拿不到，稍后再试。</p>
      )}
    </div>
  );
}
