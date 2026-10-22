import type { ReactElement } from "react";

/**
 * 前端能力注册表。
 * 每个能力目录导出一个 { id, routes } 的模块；这里自动收集。
 * 导航信息以服务端 manifest 为准，前端只负责「页面长什么样」。
 */
export type CapabilityRoute = { path: string; element: ReactElement };

export type CapabilityModule = {
  id: string;
  routes: CapabilityRoute[];
};

const modules = import.meta.glob<{ default: CapabilityModule }>("./*/index.tsx", { eager: true });

export const capabilityModules: CapabilityModule[] = Object.values(modules)
  .map((module) => module.default)
  .filter((module): module is CapabilityModule => Boolean(module?.id));
