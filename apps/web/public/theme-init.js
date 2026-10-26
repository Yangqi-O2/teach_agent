/*
 * 主题引导脚本：在首屏渲染前同步执行，避免深色模式下闪白。
 * 放在 public/ 下由 index.html 以同源方式引入，这样 CSP 可以保持 script-src 'self'，
 * 不需要为它开 'unsafe-inline'。
 */
try {
  var stored = localStorage.getItem("tjh-theme") || "system";
  var prefersDark =
    stored === "dark" ||
    (stored === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = prefersDark ? "dark" : "light";
} catch (error) {
  document.documentElement.dataset.theme = "light";
}
