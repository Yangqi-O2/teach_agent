import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(iso?: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const minute = 60_000;
  if (diff < minute) return "刚刚";
  if (diff < 60 * minute) return `${Math.floor(diff / minute)} 分钟前`;
  if (diff < 24 * 60 * minute) return `${Math.floor(diff / (60 * minute))} 小时前`;
  if (diff < 30 * 24 * 60 * minute) return `${Math.floor(diff / (24 * 60 * minute))} 天前`;
  return formatTime(iso);
}

export function shortenPath(path: string, max = 46): string {
  if (path.length <= max) return path;
  const parts = path.split("/");
  return `…/${parts.slice(-2).join("/")}`;
}

/** 能力成熟度的唯一真源：后端 manifest.status，前端只做展示映射。 */
export type StatusTone = "jade" | "amber" | "neutral";

export function capabilityStatusMeta(status?: string | null): { label: string; tone: StatusTone; hint: string } {
  switch (status) {
    case "beta":
      return { label: "公测中", tone: "amber", hint: "功能可用，细节可能调整" };
    case "planned":
      return { label: "规划中", tone: "neutral", hint: "尚未实现，导航里不会出现" };
    case "stable":
    default:
      return { label: "已上线", tone: "jade", hint: "功能完整，可放心使用" };
  }
}

/**
 * 服务端绝对路径对外展示时只保留末两级。
 * 原始路径包含用户名与部署目录结构，公网环境下属于不必要的信息暴露。
 */
export function maskPath(path?: string | null, max = 46): string {
  if (!path) return "—";
  const parts = path.split(/[\\/]/).filter(Boolean);
  if (parts.length <= 2) return path;
  return shortenPath(`…/${parts.slice(-2).join("/")}`, max);
}
