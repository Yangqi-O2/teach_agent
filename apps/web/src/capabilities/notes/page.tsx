import { useCallback, useEffect, useState } from "react";

import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/PageHeader";
import { Badge, Button, EmptyState, Input, Textarea } from "../../components/ui/primitives";
import { api, type Note } from "../../lib/api";
import { cn, relativeTime } from "../../lib/utils";
import { useApp } from "../../store/app";

export function NotesPage() {
  const toast = useApp((s) => s.toast);
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");

  const load = useCallback(async (q = "") => {
    try {
      setNotes(await api.notes.list(q));
    } catch (error) {
      toast({ title: "加载速记失败", description: String(error), tone: "error" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    const timer = window.setTimeout(() => load(query), 250);
    return () => window.clearTimeout(timer);
  }, [query, load]);

  const save = async () => {
    if (!content.trim() && !title.trim()) {
      toast({ title: "先写点什么吧", tone: "default" });
      return;
    }
    setSaving(true);
    try {
      await api.notes.create({ title, content, tags });
      setTitle("");
      setContent("");
      setTags("");
      await load(query);
      toast({ title: "已记下", description: "速记已保存到本地数据库", tone: "success" });
    } catch (error) {
      toast({ title: "保存失败", description: String(error), tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (note: Note) => {
    try {
      await api.notes.remove(note.id);
      setNotes((list) => list.filter((item) => item.id !== note.id));
      toast({ title: "已删除", tone: "success" });
    } catch (error) {
      toast({ title: "删除失败", description: String(error), tone: "error" });
    }
  };

  return (
    <div className="page-enter">
      <PageHeader
        eyebrow="能力 · 示例"
        title="速记"
        description="随手记下课堂灵感、待办与摘录。这个能力也是「新增能力」的模板：一个目录 + 一份 manifest，导航、路由、设置、Agent 工具都会自动接上。"
      />

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="card sticky top-24 p-5">
          <div className="mb-4 flex items-center gap-2 text-[13px] font-medium text-ink">
            <Icon name="pencil-line" className="h-4 w-4 text-brand" />
            写一条速记
          </div>
          <div className="space-y-3">
            <Input placeholder="标题（可留空，自动取正文首行）" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Textarea
              placeholder="记下此刻想到的东西…（⌘ + Enter 保存）"
              value={content}
              className="min-h-40"
              onChange={(e) => setContent(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") save();
              }}
            />
            <Input placeholder="标签，用逗号分隔（默认：课堂）" value={tags} onChange={(e) => setTags(e.target.value)} />
            <div className="flex items-center justify-between pt-1">
              <span className="text-[11.5px] text-ink-faint">保存在本机 SQLite</span>
              <Button variant="primary" size="sm" loading={saving} onClick={save}>
                <Icon name="check" className="h-3.5 w-3.5" />
                保存
              </Button>
            </div>
          </div>
        </div>

        <div>
          <div className="mb-3 flex items-center gap-3">
            <div className="relative flex-1">
              <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索标题或内容"
                className="pl-9"
              />
            </div>
            <Badge tone="neutral">{notes.length} 条</Badge>
          </div>

          {loading ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="card shimmer h-24" />
              ))}
            </div>
          ) : notes.length === 0 ? (
            <EmptyState
              icon="notebook-pen"
              title={query ? "没有匹配的速记" : "还没有速记"}
              description={query ? "换个关键词试试。" : "在左边写下第一条吧，它会同时出现在学习记录里。"}
            />
          ) : (
            <div className="stagger space-y-3">
              {notes.map((note) => (
                <article key={note.id} className="card group p-4 transition-shadow hover:shadow-lift">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-display text-[15px] font-semibold text-ink">{note.title || "无标题"}</h3>
                    <button
                      onClick={() => remove(note)}
                      className="rounded-md p-1 text-ink-faint opacity-0 transition-all hover:bg-danger/10 hover:text-danger group-hover:opacity-100"
                      aria-label="删除"
                    >
                      <Icon name="trash-2" className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {note.content ? (
                    <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-soft">{note.content}</p>
                  ) : null}
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {note.tags.map((tag) => (
                      <span key={tag} className={cn("rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-ink-faint")}>
                        #{tag}
                      </span>
                    ))}
                    <span className="ml-auto text-[11px] text-ink-faint">{relativeTime(note.created_at)}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
