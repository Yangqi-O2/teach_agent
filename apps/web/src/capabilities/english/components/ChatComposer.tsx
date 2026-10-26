import { useEffect, useRef } from "react";

import { Icon } from "../../../components/Icon";
import { Button } from "../../../components/ui/primitives";
import { cn } from "../../../lib/utils";

export function ChatComposer({
  draft,
  busy,
  canSend,
  disabled,
  onChange,
  onSend,
  onStop,
}: {
  draft: string;
  busy: boolean;
  canSend: boolean;
  disabled: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 128)}px`;
  }, [draft]);

  return (
    <div className="border-t border-line bg-surface px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:px-5">
      <div className="mx-auto flex max-w-2xl items-end gap-2">
        <textarea
          ref={textareaRef}
          value={draft}
          rows={1}
          maxLength={800}
          disabled={disabled}
          placeholder={disabled ? "先选择一个情景…" : "用英文说点什么…（Enter 发送，Shift+Enter 换行）"}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              onSend();
            }
          }}
          className={cn(
            "max-h-32 min-h-10 flex-1 resize-none rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[14px] leading-relaxed text-ink placeholder:text-ink-faint/80 transition-colors focus:border-brand/60 focus:outline-none focus:ring-4 focus:ring-brand/10 disabled:opacity-50",
          )}
          aria-label="输入英文"
        />
        {busy ? (
          <Button variant="secondary" size="md" onClick={onStop} className="h-10 shrink-0">
            <Icon name="square" className="h-3.5 w-3.5" />
            停止
          </Button>
        ) : (
          <Button
            variant="primary"
            size="md"
            disabled={!canSend}
            onClick={onSend}
            className="h-10 shrink-0"
          >
            <Icon name="send" className="h-3.5 w-3.5" />
            发送
          </Button>
        )}
      </div>
      <p className="mx-auto mt-1.5 flex max-w-2xl items-center justify-between gap-2 text-[11px] text-ink-faint">
        <span>语法问题会以波浪线标出；AI 生成内容仅供参考。</span>
        {draft.length ? (
          <span className={draft.length > 760 ? "shrink-0 font-medium text-amber" : "shrink-0"}>
            {draft.length}/800
          </span>
        ) : null}
      </p>
    </div>
  );
}
