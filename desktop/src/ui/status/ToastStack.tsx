import type { ToastItem } from "./types";

interface ToastStackProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
  /** 用户点「查看技术详情」时打开技术详情抽屉。 */
  onOpenDetails?: (id: string) => void;
}

/** 右上角 Toast 队列：错误与结果通知，同一错误只出现一次由 store 保证。 */
export function ToastStack({ toasts, onDismiss, onOpenDetails }: ToastStackProps) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.kind}`}>
          <span className="toast-text">{toast.text}</span>
          {toast.hasDetails && onOpenDetails ? (
            <button
              type="button"
              className="toast-action"
              onClick={() => onOpenDetails(toast.id)}
            >
              查看技术详情
            </button>
          ) : null}
          <button
            type="button"
            className="toast-close"
            aria-label="关闭通知"
            onClick={() => onDismiss(toast.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
