import type { EnglishMemoryView } from "../../../lib/api";
import { Icon } from "../../../components/Icon";
import { Badge } from "../../../components/ui/primitives";
import { Drawer } from "./Drawer";

function MemoryList({ title, items, tone }: { title: string; items: string[]; tone?: string }) {
  if (!items.length) return null;
  return (
    <section>
      <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">
        {title}
        <span className="text-[10px] normal-case tracking-normal text-ink-faint/70">{items.length}</span>
      </p>
      <ul className="space-y-1">
        {items.map((item) => (
          <li
            key={item}
            className="rounded-lg bg-surface-2/70 px-2.5 py-1.5 text-[12.5px] leading-relaxed text-ink-soft"
          >
            <span className={tone}>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** 情景记忆抽屉：事实 / 待解决线索 / 已完成的节拍 */
export function MemoryDrawer({
  open,
  onOpenChange,
  memory,
  scenarioTitle,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  memory: EnglishMemoryView | null;
  scenarioTitle: string | null;
}) {
  const counts = memory?.counts ?? { facts: 0, threads: 0, beats: 0 };
  const facts = memory?.established_facts ?? [];
  const threads = memory?.open_threads ?? [];
  const beats = memory?.beats_done ?? [];

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="情景记忆"
      subtitle={
        <>
          当前情景：{scenarioTitle ?? "未选择"}
          {typeof memory?.revision === "number" ? ` · v${memory.revision}` : ""}
        </>
      }
    >
      {!memory ? (
        <p className="rounded-xl bg-surface-2/70 px-3 py-4 text-[12.5px] leading-relaxed text-ink-faint">
          还没有情景记忆。先聊几轮，AI 会记住已确认的事实、还没聊完的线索和已完成的节拍。
        </p>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-1.5">
            {[
              { label: "事实", value: counts.facts },
              { label: "待解决", value: counts.threads },
              { label: "节拍", value: counts.beats },
            ].map((item) => (
              <div key={item.label} className="rounded-xl border border-line bg-surface-2/40 p-2.5 text-center">
                <p className="text-[16px] font-semibold text-ink">{item.value}</p>
                <p className="text-[10.5px] text-ink-faint">{item.label}</p>
              </div>
            ))}
          </div>

          {memory.setting ? (
            <div className="rounded-xl border border-line p-3">
              <p className="mb-1 text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">当前场景</p>
              <p className="text-[12.5px] leading-relaxed text-ink-soft">{memory.setting}</p>
            </div>
          ) : null}

          <MemoryList title="已确定的事实" items={facts} />
          <MemoryList title="待解决的线索" items={threads} />
          <MemoryList title="已过的节拍" items={beats} tone="text-ink-faint" />

          {!facts.length && !threads.length && !beats.length ? (
            <p className="rounded-xl bg-surface-2/70 px-3 py-4 text-[12.5px] leading-relaxed text-ink-faint">
              记忆是空的：这一轮没有提取到可长期保留的信息。
            </p>
          ) : null}

          <p className="flex items-start gap-1.5 rounded-xl border border-dashed border-line p-2.5 text-[11px] leading-relaxed text-ink-faint">
            <Icon name="brain" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand" />
            记忆按情景隔离，只作用于当前账号与当前情景，用于让 AI 记住前文。
          </p>
          <div className="flex flex-wrap gap-1">
            <Badge tone="outline">revision {memory.revision ?? 0}</Badge>
            <Badge tone="outline">facts {facts.length}</Badge>
            <Badge tone="outline">threads {threads.length}</Badge>
          </div>
        </div>
      )}
    </Drawer>
  );
}
