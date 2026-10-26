import { Component, type ErrorInfo, type ReactNode } from "react";

import { Icon } from "./Icon";
import { Button } from "./ui/primitives";

/**
 * 顶层错误边界。
 *
 * 上线后最怕的不是报错，而是「白屏」——用户看不到任何信息，也找不到出路。
 * 这里把渲染期异常兜住，保留导航外壳，给出可执行的下一步。
 */
type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 控制台留一份完整堆栈，便于用户反馈时截图
    console.error("[天健湖] 页面渲染异常", error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex min-h-[70vh] items-center justify-center px-4">
        <div className="card w-full max-w-lg p-7 text-center">
          <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-danger/10 text-danger">
            <Icon name="alert-circle" className="h-6 w-6" />
          </div>
          <h1 className="font-display text-lg font-semibold text-ink">这个页面出了点问题</h1>
          <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">
            其他功能不受影响，可以重试当前页面，或者回到首页继续。
          </p>
          <p className="mt-3 max-h-24 overflow-auto rounded-xl bg-surface-2 p-3 text-left font-mono text-[11.5px] leading-relaxed text-ink-faint">
            {error.message || "未知错误"}
          </p>
          <div className="mt-6 flex items-center justify-center gap-2">
            <Button variant="primary" onClick={this.reset}>
              重试
            </Button>
            <Button variant="ghost" onClick={() => window.location.assign("/")}>
              回到首页
            </Button>
          </div>
        </div>
      </div>
    );
  }
}
