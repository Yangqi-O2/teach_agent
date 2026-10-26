import { useState } from "react";

import { Icon } from "./Icon";
import { Field, Input } from "./ui/primitives";
import { cn } from "../lib/utils";
import type { ProfileInput, UserProfile } from "../lib/api";

/**
 * 个人资料表单。
 *
 * 同一个组件被两处复用：注册第二步（引导页）与校园雷达页的「编辑资料」抽屉。
 * 表单只负责收集，不负责提交——提交时机由调用方决定（引导页要 onboarded=true，
 * 抽屉里保存不改变 onboarded）。
 */

const SCHOOL_SUGGESTIONS = ["郑州大学", "河南大学", "清华大学", "北京大学", "复旦大学"];

const GRADES = ["大一", "大二", "大三", "大四", "研一", "研二", "研三"];

// 郑州大学常见院系，仅作为输入提示，不限制
const DEPARTMENT_SUGGESTIONS = [
  "信息工程学院",
  "计算机与人工智能学院",
  "电气工程学院",
  "机械与动力工程学院",
  "土木工程学院",
  "材料科学与工程学院",
  "化工学院",
  "数学与统计学院",
  "物理学院",
  "化学学院",
  "生命科学学院",
  "商学院",
  "法学院",
  "文学院",
  "新闻与传播学院",
  "外国语与国际关系学院",
  "医学院",
];

const INTEREST_SUGGESTIONS = [
  "算法竞赛", "编程", "人工智能", "数学建模", "考研", "四六级",
  "篮球", "足球", "羽毛球", "音乐", "摄影", "志愿服务", "社团", "辩论",
];

const GOAL_OPTIONS = ["考研", "保研", "就业", "竞赛", "科研", "出国", "考公"];

export type ProfileDraft = {
  school: string;
  grade: string;
  department: string;
  major: string;
  class_name: string;
  interests: string[];
  goals: string[];
};

export function emptyDraft(profile?: UserProfile | null): ProfileDraft {
  return {
    school: profile?.school ?? "",
    grade: profile?.grade ?? "",
    department: profile?.department ?? "",
    major: profile?.major ?? "",
    class_name: profile?.class_name ?? "",
    interests: profile?.interests ?? [],
    goals: profile?.goals ?? [],
  };
}

export function draftToInput(draft: ProfileDraft, extra?: ProfileInput): ProfileInput {
  return {
    school: draft.school.trim(),
    grade: draft.grade.trim(),
    department: draft.department.trim(),
    major: draft.major.trim(),
    class_name: draft.class_name.trim(),
    interests: draft.interests,
    goals: draft.goals,
    ...extra,
  };
}

function TagEditor({
  values,
  onChange,
  suggestions,
  placeholder,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  suggestions: string[];
  placeholder: string;
}) {
  const [text, setText] = useState("");

  const add = (raw: string) => {
    const value = raw.trim();
    if (!value || values.includes(value)) return;
    onChange([...values, value].slice(0, 12));
    setText("");
  };

  const remove = (value: string) => onChange(values.filter((item) => item !== value));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span
            key={value}
            className="inline-flex items-center gap-1 rounded-full border border-brand/25 bg-brand-soft px-2.5 py-1 text-[12px] text-brand-strong"
          >
            {value}
            <button
              type="button"
              onClick={() => remove(value)}
              className="rounded-full p-0.5 text-brand-strong/60 transition-colors hover:bg-brand/10 hover:text-brand-strong"
              aria-label={`移除 ${value}`}
            >
              <Icon name="x" className="h-3 w-3" />
            </button>
          </span>
        ))}
        {values.length === 0 ? (
          <span className="text-[12px] text-ink-faint">还没选，可以先从下面点几个</span>
        ) : null}
      </div>

      <Input
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "," || event.key === "，") {
            event.preventDefault();
            add(text);
          }
          if (event.key === "Backspace" && !text && values.length) {
            remove(values[values.length - 1]);
          }
        }}
        placeholder={placeholder}
      />

      <div className="flex flex-wrap gap-1.5">
        {suggestions
          .filter((item) => !values.includes(item))
          .slice(0, 10)
          .map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => add(item)}
              className="rounded-full border border-line px-2.5 py-1 text-[11.5px] text-ink-soft transition-colors hover:border-brand/40 hover:text-brand-strong"
            >
              + {item}
            </button>
          ))}
      </div>
    </div>
  );
}

export function ProfileForm({
  draft,
  onChange,
  compact = false,
}: {
  draft: ProfileDraft;
  onChange: (next: ProfileDraft) => void;
  compact?: boolean;
}) {
  const set = <K extends keyof ProfileDraft>(key: K, value: ProfileDraft[K]) =>
    onChange({ ...draft, [key]: value });

  const toggleGoal = (goal: string) => {
    const has = draft.goals.includes(goal);
    set("goals", has ? draft.goals.filter((item) => item !== goal) : [...draft.goals, goal]);
  };

  return (
    <div className={cn("space-y-4", compact && "space-y-3.5")}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="学校" hint="决定抓哪所学校的通知">
          <Input
            value={draft.school}
            onChange={(event) => set("school", event.target.value)}
            placeholder="例如 郑州大学"
            list="tjh-school-options"
            autoComplete="off"
          />
          <datalist id="tjh-school-options">
            {SCHOOL_SUGGESTIONS.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </Field>

        <Field label="年级">
          <div className="flex flex-wrap gap-1.5">
            {GRADES.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => set("grade", draft.grade === item ? "" : item)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-[12.5px] transition-colors",
                  draft.grade === item
                    ? "border-brand/40 bg-brand-soft text-brand-strong"
                    : "border-line text-ink-soft hover:border-brand/30",
                )}
              >
                {item}
              </button>
            ))}
          </div>
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="院系">
          <Input
            value={draft.department}
            onChange={(event) => set("department", event.target.value)}
            placeholder="例如 信息工程学院"
            list="tjh-department-options"
            autoComplete="off"
          />
          <datalist id="tjh-department-options">
            {DEPARTMENT_SUGGESTIONS.map((item) => (
              <option key={item} value={item} />
            ))}
          </datalist>
        </Field>

        <Field label="专业">
          <Input
            value={draft.major}
            onChange={(event) => set("major", event.target.value)}
            placeholder="例如 计算机科学与技术"
            autoComplete="off"
          />
        </Field>
      </div>

      <Field label="班级" hint="可留空">
        <Input
          value={draft.class_name}
          onChange={(event) => set("class_name", event.target.value)}
          placeholder="例如 2024级1班"
          autoComplete="off"
        />
      </Field>

      <Field label="兴趣爱好" hint="填得越具体，推荐越准（回车或逗号添加）">
        <TagEditor
          values={draft.interests}
          onChange={(next) => set("interests", next)}
          suggestions={INTEREST_SUGGESTIONS}
          placeholder="例如 算法竞赛"
        />
      </Field>

      <Field label="近期目标" hint="决定哪类通知优先推给你">
        <div className="flex flex-wrap gap-1.5">
          {GOAL_OPTIONS.map((goal) => (
            <button
              key={goal}
              type="button"
              onClick={() => toggleGoal(goal)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-[12.5px] transition-colors",
                draft.goals.includes(goal)
                  ? "border-jade/40 bg-jade/12 text-jade"
                  : "border-line text-ink-soft hover:border-jade/30",
              )}
            >
              {goal}
            </button>
          ))}
        </div>
      </Field>
    </div>
  );
}
