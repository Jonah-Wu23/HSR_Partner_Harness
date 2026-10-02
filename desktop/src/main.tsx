import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import { AppController } from "./app/AppController";
import { createActionController } from "./services/actions";
import type { DesktopBackend } from "./services/backend";
import { MockDesktopBackend } from "./services/mockDesktopBackend";
import { TauriDesktopBackend } from "./services/tauriDesktopBackend";

function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

/** 渲染期未捕获的异常显示带原文与重试按钮的错误页。 */
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
    // 重试通过 key 重挂整棵子树，清掉失败子树里的本地状态。
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

/** 独立聊天窗口的启动参数：Rust open_chat_window 创建窗口时在 URL query 携带
    conversation_id 与 view_id；view_id 由 store 初始化时读取，这里只取 conversation_id
    驱动首次 conversation.open 装载。 */
function readInitialConversationId(): string | null {
  const value = new URLSearchParams(window.location.search).get("conversation_id");
  return value && value.length > 0 ? value : null;
}

const backend: DesktopBackend = isTauriRuntime()
  ? new TauriDesktopBackend()
  : new MockDesktopBackend("single-project");
// 浏览器 Mock 模式把实例挂到 window，供无头浏览器检查界面时驱动 mock 状态
// （如 setVoiceConfigured、setScenario）；Tauri 运行时不走这一分支。
if (!isTauriRuntime()) {
  (window as unknown as { __mockBackend?: MockDesktopBackend }).__mockBackend =
    backend as MockDesktopBackend;
}
const controller = createActionController(backend);
const initialConversationId = readInitialConversationId();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <AppController
        backend={backend}
        actions={controller.actions}
        loadBootstrap={controller.loadBootstrap}
        conversationOpen={controller.conversationOpen}
        initialConversationId={initialConversationId}
      />
    </ErrorBoundary>
  </StrictMode>,
);
