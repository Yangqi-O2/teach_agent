import type { EnglishGrammarError, EnglishSource } from "../../../lib/api";
import { cn } from "../../../lib/utils";
import { Icon } from "../../../components/Icon";
import { Markdown } from "./Markdown";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  error?: string;
  errors?: EnglishGrammarError[];
  candidates?: string[];
  sources?: EnglishSource[];
  createdAt?: string | null;
};

export type MessageSegment = { text: string; error: EnglishGrammarError | null };

/**
 * 把用户消息切成「正常文本 / 错误片段」。
 * 后端 annotations 里有 span，部分实现还会给 start/end；两者都兼容。
 */
export function segmentMessage(message: ChatMessage): MessageSegment[] {
  const content = message.content;
  const errors = message.errors ?? [];
  if (!errors.length) return [{ text: content, error: null }];

  const ranges: { start: number; end: number; error: EnglishGrammarError }[] = [];
  for (const error of errors) {
    let start = typeof error.start === "number" ? error.start : -1;
    let end = typeof error.end === "number" ? error.end : -1;
    const span = error.span ?? "";

    const aligned =
      start >= 0 && end > start && end <= content.length && content.slice(start, end) === span;
    if (!aligned) {
      const index = span ? content.toLowerCase().indexOf(span.toLowerCase()) : -1;
      if (index < 0) continue;
      start = index;
      end = index + span.length;
    }
    ranges.push({ start, end, error });
  }

  ranges.sort((a, b) => a.start - b.start);

  const segments: MessageSegment[] = [];
  let position = 0;
  for (const range of ranges) {
    if (range.start < position) continue;
    if (range.start > position) segments.push({ text: content.slice(position, range.start), error: null });
    segments.push({ text: content.slice(range.start, range.end), error: range.error });
    position = range.end;
  }
  if (position < content.length) segments.push({ text: content.slice(position), error: null });
  return segments.length ? segments : [{ text: content, error: null }];
}

function contextOf(text: string, word: string): string {
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const sentence = text
    .split(/(?<=[.!?])\s+/)
    .find((part) => new RegExp(`\\b${escaped}\\b`, "i").test(part));
  return (sentence ?? text).slice(0, 220).trim();
}

function UserBubble({
  message,
  onOpenError,
}: {
  message: ChatMessage;
  onOpenError: (error: EnglishGrammarError) => void;
}) {
  const segments = segmentMessage(message);
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="max-w-[88%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[14px] leading-relaxed text-canvas shadow-[0_16px_36px_-24px_rgba(20,104,123,0.9)]">
        {segments.map((segment, index) =>
          segment.error ? (
            <button
              key={`seg-${index}`}
              type="button"
              onClick={() => onOpenError(segment.error as EnglishGrammarError)}
              title={`${segment.error.correction} · ${segment.error.explain_zh}`}
              className={cn(
                "inline cursor-pointer border-b-2 border-dashed leading-[inherit] transition-colors hover:bg-canvas/10",
                segment.error.severity === "high" ? "border-amber" : "border-amber/60",
              )}
            >
              {segment.text}
            </button>
          ) : (
            <span key={`seg-${index}`}>{segment.text}</span>
          ),
        )}
      </div>
      {message.errors?.length ? (
        <button
          type="button"
          onClick={() => onOpenError(message.errors![0])}
          className="text-[11.5px] text-danger underline-offset-2 hover:underline"
        >
          发现 {message.errors.length} 处语法问题 · 点下划线看讲解
        </button>
      ) : null}
    </div>
  );
}

function AssistantBubble({
  message,
  onOpenError,
  onSaveWord,
  savingWord,
}: {
  message: ChatMessage;
  onOpenError: (error: EnglishGrammarError) => void;
  onSaveWord: (word: string, context: string) => void;
  savingWord: string | null;
}) {
  return (
    <div className="flex gap-3">
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[10px] font-semibold tracking-wider text-brand-strong">
        AI
      </div>
      <div className="min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-3 shadow-soft">
          {message.content ? (
            <Markdown content={message.content} />
          ) : message.streaming ? (
            <span className="flex items-center gap-1.5 py-1" aria-label="正在生成">
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-brand" />
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-brand [animation-delay:160ms]" />
              <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-brand [animation-delay:320ms]" />
            </span>
          ) : (
            <span className="text-[12px] text-ink-faint">（空回复）</span>
          )}
          {message.streaming && message.content ? (
            <span className="ml-0.5 inline-block h-4 w-[3px] animate-pulse rounded-full bg-brand align-text-bottom" />
          ) : null}
          {message.error ? (
            <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-danger/10 px-2.5 py-2 text-[12px] leading-relaxed text-danger">
              <Icon name="alert-circle" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 break-words">{message.error}</span>
            </div>
          ) : null}
          {message.errors?.length ? (
            <button
              type="button"
              onClick={() => onOpenError(message.errors![0])}
              className="mt-2 text-[11.5px] text-danger underline-offset-2 hover:underline"
            >
              发现 {message.errors.length} 处语法问题
            </button>
          ) : null}
        </div>

        {message.sources?.length ? (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-ink-faint">来源</span>
            {message.sources.map((source, index) => (
              <span
                key={`${source.title}-${index}`}
                className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[11px] text-ink-faint"
                title={source.score ? `相关度 ${source.score.toFixed(2)}` : undefined}
              >
                {source.title} · 第 {source.part} 段
              </span>
            ))}
          </div>
        ) : null}

        {message.candidates?.length && !message.streaming ? (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="flex items-center gap-1 text-[11px] text-ink-faint">
              <Icon name="bookmark" className="h-3 w-3" />
              生词
            </span>
            {message.candidates.map((word) => (
              <button
                key={word}
                type="button"
                disabled={savingWord === word}
                onClick={() => onSaveWord(word, contextOf(message.content, word))}
                className={cn(
                  "rounded-full border border-dashed border-line px-2 py-0.5 text-[11.5px] text-ink-soft transition-colors",
                  savingWord === word
                    ? "opacity-50"
                    : "hover:border-brand/50 hover:bg-brand-soft/50 hover:text-brand-strong",
                )}
              >
                + {word}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function MessageBubble({
  message,
  onOpenError,
  onSaveWord,
  savingWord,
}: {
  message: ChatMessage;
  onOpenError: (error: EnglishGrammarError) => void;
  onSaveWord: (word: string, context: string) => void;
  savingWord: string | null;
}) {
  if (message.role === "user") return <UserBubble message={message} onOpenError={onOpenError} />;
  return (
    <AssistantBubble
      message={message}
      onOpenError={onOpenError}
      onSaveWord={onSaveWord}
      savingWord={savingWord}
    />
  );
}
