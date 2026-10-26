import { useEffect, useRef } from "react";

import type {
  EnglishGrammarError,
  EnglishKnowledgeCard,
  EnglishTopic,
} from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { ErrorCard } from "./ErrorCard";
import { MessageBubble, type ChatMessage } from "./MessageBubble";

function sameError(a: EnglishGrammarError, b: EnglishGrammarError): boolean {
  return a === b || (a.code === b.code && a.span === b.span);
}

export function ChatThread({
  messages,
  loadingHistory,
  topics,
  activeError,
  knowledgeCard,
  knowledgeLoading,
  onOpenError,
  onCloseError,
  onSaveWord,
  savingWord,
  topicTitle,
}: {
  messages: ChatMessage[];
  loadingHistory: boolean;
  topics: EnglishTopic[];
  activeError: EnglishGrammarError | null;
  knowledgeCard: EnglishKnowledgeCard | null;
  knowledgeLoading: boolean;
  onOpenError: (error: EnglishGrammarError) => void;
  onCloseError: () => void;
  onSaveWord: (word: string, context: string) => void;
  savingWord: string | null;
  topicTitle: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const lastContentLength = messages.length ? messages[messages.length - 1].content.length : 0;

  useEffect(() => {
    const element = listRef.current;
    if (!element) return;
    element.scrollTop = element.scrollHeight;
  }, [messages.length, lastContentLength, loadingHistory]);

  const unusedTopics = topics.filter((topic) => !topic.used_count);

  return (
    <div
      ref={listRef}
      className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5 md:px-5"
      aria-live="polite"
    >
      {loadingHistory ? (
        <div className="mx-auto max-w-2xl space-y-3">
          <div className="shimmer ml-auto h-12 w-2/3 rounded-2xl" />
          <div className="shimmer h-24 w-5/6 rounded-2xl" />
          <div className="shimmer ml-auto h-10 w-1/2 rounded-2xl" />
        </div>
      ) : messages.length === 0 ? (
        <div className="mx-auto flex max-w-lg flex-col items-center py-10 text-center md:py-16">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-line bg-surface-2 text-brand">
            <Icon name="message-square" className="h-6 w-6" />
          </div>
          <p className="text-[14px] font-medium text-ink">先开口，用英文聊下去</p>
          <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-ink-faint">
            AI 会扮演情景里的另一方，用英文推进话题；写完发送后，语法问题会以波浪下划线标出来。
          </p>
          {topics.length ? (
            <div className="mt-6 w-full rounded-card border border-line bg-surface-2/60 p-3.5 text-left">
              <p className="text-[12px] font-medium text-ink-soft">
                话题池还有 {unusedTopics.length} 个没用过
                {topicTitle ? ` · 当前：${topicTitle}` : ""}
              </p>
              <ul className="mt-1.5 space-y-1">
                {topics.slice(0, 4).map((topic) => (
                  <li key={topic.id} className="truncate text-[12px] text-ink-faint">
                    · {topic.title}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mx-auto max-w-2xl space-y-4">
          {messages.map((message) => {
            const showCard =
              message.role === "user" &&
              activeError != null &&
              (message.errors ?? []).some((error) => sameError(error, activeError));
            return (
              <div key={message.id} className="space-y-1.5">
                <MessageBubble
                  message={message}
                  onOpenError={onOpenError}
                  onSaveWord={onSaveWord}
                  savingWord={savingWord}
                />
                {showCard && activeError ? (
                  <ErrorCard
                    error={activeError}
                    card={knowledgeCard}
                    loading={knowledgeLoading}
                    onClose={onCloseError}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
