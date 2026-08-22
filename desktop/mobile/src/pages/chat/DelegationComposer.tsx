import { type FormEvent, type KeyboardEvent, useState } from "react";
import { CloseIcon, SendIcon, SpinnerIcon } from "../../components/cards/icons";

export interface DelegationComposerProps {
  onSubmit: (text: string) => Promise<void>;
  disabled?: boolean;
  placeholder?: string;
}

/**
 * V0.3.3 手机端「交给助手」委派输入区：
 * 输入框 + 提交按钮，触控目标 ≥44px；
 * 调用 submitDelegation 发起真实任务；提交失败如实呈现真实错误，不合成成功。
 */
export function DelegationComposer({
  onSubmit,
  disabled = false,
  placeholder = "输入任务交给助手执行…",
}: DelegationComposerProps) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event?: FormEvent) => {
    event?.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || submitting || disabled) return;

    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(trimmed);
      setText("");
    } catch (err) {
      // Let It Fail: 如实展示真实错误信息
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // 手机端通常用按钮发送，但支持键盘快捷提交 (Ctrl+Enter 或 Cmd+Enter)
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      void handleSubmit();
    }
  };

  return (
    <footer className="mobile-composer" data-testid="delegation-composer">
      {error ? (
        <div className="mobile-composer-error" data-testid="delegation-error" role="alert">
          <span className="mobile-composer-error-text">委派失败：{error}</span>
          <button
            type="button"
            className="mobile-composer-error-close"
            onClick={() => setError(null)}
            aria-label="关闭错误提示"
          >
            <CloseIcon />
          </button>
        </div>
      ) : null}

      <form className="mobile-composer-form" onSubmit={handleSubmit}>
        <div className="mobile-composer-input-wrap">
          <textarea
            className="mobile-composer-textarea"
            data-testid="delegation-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled || submitting}
            rows={1}
            aria-label="委派任务输入框"
          />
        </div>

        <button
          type="submit"
          className="mobile-composer-submit-btn primary"
          data-testid="delegation-submit-btn"
          disabled={disabled || submitting || !text.trim()}
          aria-label="交给助手执行"
        >
          {submitting ? (
            <>
              <SpinnerIcon />
              <span className="mobile-composer-submit-label">提交中…</span>
            </>
          ) : (
            <>
              <SendIcon />
              <span className="mobile-composer-submit-label">交给助手</span>
            </>
          )}
        </button>
      </form>
    </footer>
  );
}
