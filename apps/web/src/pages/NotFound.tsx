import { useNavigate } from "react-router-dom";

import { Icon } from "../components/Icon";
import { Button } from "../components/ui/primitives";

export function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="page-enter flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="relative mb-6 flex h-16 w-16 items-center justify-center rounded-3xl border border-line bg-surface text-brand">
        <span className="absolute inset-0 rounded-3xl border border-brand/20 animate-ripple" />
        <Icon name="search" className="h-7 w-7" />
      </div>
      <p className="font-display text-2xl font-semibold text-ink">这里还没有内容</p>
      <p className="mt-2 max-w-sm text-[13px] leading-relaxed text-ink-faint">
        页面可能来自尚未接入的能力，或者链接写错了。回到首页看看吧。
      </p>
      <Button variant="primary" className="mt-6" onClick={() => navigate("/")}>
        回到首页
      </Button>
    </div>
  );
}
