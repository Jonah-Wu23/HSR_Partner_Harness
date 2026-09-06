import { Component, type ErrorInfo, type ReactNode } from "react";
import "./ErrorBoundary.css";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * V0.3.8 T3（真机验收 C5）：React 渲染期异常的最后一道边界。
 *
 * 渲染期未捕获异常此前会让整棵树卸载成白屏（进程活、页面空白）。
 * 边界捕获后如实呈现原始错误并给出重载入口——不伪造在线、不静默。
 * 重载（location.reload）不清 localStorage，配对与连接状态自动恢复。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 原始错误与组件栈进 console，供远程调试与验收取证。
    console.error("[ErrorBoundary] 渲染异常", error, info.componentStack);
  }

  private handleReload = () => {
    location.reload();
  };

  render() {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }
    return (
      <div className="error-boundary" role="alert">
        <h1 className="error-boundary-title">页面出错了</h1>
        <p className="error-boundary-message">{error.message || String(error)}</p>
        <button type="button" className="error-boundary-reload" onClick={this.handleReload}>
          重新加载
        </button>
      </div>
    );
  }
}
