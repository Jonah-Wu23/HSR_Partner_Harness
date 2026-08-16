import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import { AppController } from "./app/AppController";
import { createActionController } from "./services/actions";
import type { DesktopBackend } from "./services/backend";
import { MockDesktopBackend } from "./services/mockDesktopBackend";
import { TauriDesktopBackend } from "./services/tauriDesktopBackend";

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** 渲染期兜底：任何未捕获异常都显示可恢复的错误页，而不是整窗白屏。 */
class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null; retryKey: number }
> {
  state: { error: Error | null; retryKey: number } = { error: null, retryKey: 0 };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("渲染崩溃：", error);
  }

  private handleRetry = () => {
    // M5.5：重试通过 key 重挂整棵子树，清掉失败子树里的本地状态。
    this.setState((state) => ({ error: null, retryKey: state.retryKey + 1 }));
  };

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            height: "100vh",
            gap: "12px",
            fontFamily: "system-ui, sans-serif",
            color: "#e8e8f0",
            background: "#14151a",
          }}
        >
          <h2 style={{ margin: 0 }}>界面渲染遇到问题</h2>
          <p style={{ margin: 0, opacity: 0.7, maxWidth: 560, textAlign: "center" }}>
            {String(this.state.error?.message ?? this.state.error)}
          </p>
          <button onClick={this.handleRetry} style={{ padding: "8px 20px" }}>
            重试
          </button>
        </div>
      );
    }
    return (
      <div key={this.state.retryKey} style={{ display: "contents" }}>
        {this.props.children}
      </div>
    );
  }
}

const backend: DesktopBackend = isTauriRuntime()
  ? new TauriDesktopBackend()
  : new MockDesktopBackend("single-project");
const controller = createActionController(backend);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <AppController
        backend={backend}
        actions={controller.actions}
        loadBootstrap={controller.loadBootstrap}
      />
    </ErrorBoundary>
  </StrictMode>,
);
