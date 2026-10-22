import { Route, Routes } from "react-router-dom";

import { capabilityModules } from "../capabilities/registry";
import { Home } from "../pages/Home";
import { Jobs } from "../pages/Jobs";
import { NotFound } from "../pages/NotFound";
import { Settings } from "../pages/Settings";
import { useApp } from "../store/app";

export function AppRoutes() {
  const capabilities = useApp((s) => s.capabilities);
  const enabled = new Set(capabilities.filter((c) => c.enabled).map((c) => c.id));
  const dynamicRoutes = capabilityModules
    .filter((module) => enabled.has(module.id))
    .flatMap((module) => module.routes);

  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="/jobs" element={<Jobs />} />
      {dynamicRoutes.map((route) => (
        <Route key={`${route.path}`} path={route.path} element={route.element} />
      ))}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
