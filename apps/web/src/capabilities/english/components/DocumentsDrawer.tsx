import { useRef, useState } from "react";

import type { EnglishDocItem } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { Button, EmptyState, Input } from "../../../components/ui/primitives";
import { relativeTime } from "../../../lib/utils";
import { Drawer } from "./Drawer";

const ACCEPT = ".pdf,.docx,.pptx,.txt,.md,.csv,.epub,.html,.htm";

export function DocumentsDrawer({
  open,
  onOpenChange,
  items,
  loading,
  importing,
  scenarioTitle,
  onImportText,
  onUpload,
  onDelete,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: EnglishDocItem[];
  loading: boolean;
  importing: boolean;
  scenarioTitle: string | null;
  onImportText: (filename: string, content: string) => Promise<boolean>;
  onUpload: (file: File) => Promise<boolean>;
  onDelete: (id: string) => void;
  onRefresh: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState("notes.md");
  const [content, setContent] = useState("");

  const submit = async () => {
    if (!content.trim()) return;
    const ok = await onImportText(filename.trim() || "notes.md", content);
    if (ok) setContent("");
  };

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="资料库"
      subtitle="导入后 AI 会参考其中事实回答，并给出处"
      footer={
        <Button variant="secondary" size="sm" className="w-full" loading={loading} onClick={onRefresh}>
          <Icon name="refresh-cw" className="h-3.5 w-3.5" />
          刷新
        </Button>
      }
    >
      <div className="space-y-2.5 rounded-xl border border-dashed border-line bg-surface-2/40 p-3">
        <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-line bg-surface px-3 py-2.5 text-[12px] text-ink-soft transition-colors hover:border-brand/40 hover:text-ink">
          <Icon name="upload" className="h-4 w-4 text-brand" />
          {importing ? "解析中…" : "选择文件（PDF / DOCX / PPTX / EPUB / TXT / MD / HTML）"}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            disabled={importing}
            onChange={async (event) => {
              const input = event.target;
              const file = input.files?.[0];
              if (!file) return;
              await onUpload(file);
              input.value = "";
            }}
          />
        </label>
        <p className="text-[11px] text-ink-faint">
          导入到：{scenarioTitle ? `「${scenarioTitle}」` : "全局资料"}（文本会按段切分，仅用于本账号的检索）
        </p>
        <Input
          value={filename}
          onChange={(event) => setFilename(event.target.value)}
          placeholder="或直接粘贴文本，起个文件名"
          className="py-2 text-[13px]"
        />
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={5}
          placeholder="粘贴文本内容（.txt / .md / .csv 等纯文本）"
          className="w-full resize-y rounded-xl border border-line bg-surface px-3 py-2 text-[12.5px] leading-relaxed text-ink placeholder:text-ink-faint/80 focus:border-brand/60 focus:outline-none focus:ring-4 focus:ring-brand/10"
        />
        <Button
          variant="primary"
          size="sm"
          className="w-full"
          loading={importing}
          disabled={!content.trim()}
          onClick={() => void submit()}
        >
          <Icon name="plus" className="h-3.5 w-3.5" />
          导入文本
        </Button>
      </div>

      <div className="mt-4 space-y-2">
        {loading && !items.length ? (
          <div className="space-y-2">
            <div className="shimmer h-16 rounded-xl" />
            <div className="shimmer h-16 rounded-xl" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon="file-text"
            className="border-0 px-2 py-8"
            title="还没有资料"
            description="上传一份 Word / PDF，或直接粘贴一段背景材料，之后的对话会引用它。"
          />
        ) : (
          items.map((item) => (
            <article key={item.id} className="rounded-xl border border-line bg-surface p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 break-words text-[13px] font-medium text-ink">{item.filename}</p>
                <button
                  type="button"
                  onClick={() => onDelete(item.id)}
                  className="shrink-0 rounded-md p-1 text-ink-faint transition-colors hover:bg-danger/10 hover:text-danger"
                  aria-label={`删除 ${item.filename}`}
                >
                  <Icon name="trash-2" className="h-3.5 w-3.5" />
                </button>
              </div>
              <p className="mt-0.5 text-[11px] text-ink-faint">
                {item.chunk_count} 段 · {item.scenario ?? "全局"}
                {item.created_at ? ` · ${relativeTime(item.created_at)}` : ""}
              </p>
            </article>
          ))
        )}
      </div>
    </Drawer>
  );
}
