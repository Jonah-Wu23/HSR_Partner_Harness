import { type FormEvent, type KeyboardEvent, useState } from "react";
import { CloseIcon, SendIcon, SpinnerIcon } from "../../components/cards/icons";

export type ChatComposerTarget = "character" | "assistant";

export interface ChatComposerProps {
  target: ChatComposerTarget;
  onSubmit: (text: string) => Promise<void>;
  disabled?: boolean;
  /** 前置禁用原因（如对话模式下助手不可用），展示在输入区上方。 */
  disabledHint?: string | null;
}

const TARGET_META: Record<
  ChatComposerTarget,
  { placeholder: string; submitLabel: string; ariaLabel: string; errorPrefix: string }
> = {
  character: {
    placeholder: "发送消息给角色…",
    submitLabel: "发送",
    ariaLabel: "消息输入框",
    errorPrefix: "发送失败",
  },
  assistant: {
    placeholder: "输入任务交给助手执行…",
    submitLabel: "交给助手",
    ariaLabel: "委派任务输入框",
    errorPrefix: "委派失败",
  },
};

/**
 * V0.3.4 手机端聊天输入区（替代 V0.3.3 仅委派的 DelegationComposer）：
 * - target=character：普通角色消息（任何模式可用，V0.3.4 缺陷 3）
 * - target=assistant：委派任务（仅协作模式可用，由调用方前置禁用并说明）
 * 触控目标 ≥44px；提交失败如实呈现真实错误，不合成成功。
 */
export function ChatComposer({
  target,
  onSubmit,
  disabled = false,
  disabledHint = null,
}: ChatComposerProps) {
  const meta = TARGET_META[target];
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
    <div className="mobile-composer-body" data-testid="chat-composer">
      {disabledHint && disabled ? (
        <p className="mobile-composer-hint" data-testid="chat-composer-hint" role="note">
          {disabledHint}
        </p>
      ) : null}

      {error ? (
        <div className="mobile-composer-error" data-testid="chat-composer-error" role="alert">
          <span className="mobile-composer-error-text">{meta.errorPrefix}：{error}</span>
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
            data-testid="chat-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={meta.placeholder}
            disabled={disabled || submitting}
            rows={1}
            aria-label={meta.ariaLabel}
          />
        </div>

        <button
          type="submit"
          className="mobile-composer-submit-btn primary"
          data-testid="chat-submit-btn"
          disabled={disabled || submitting || !text.trim()}
          aria-label={meta.submitLabel}
        >
          {submitting ? (
            <>
              <SpinnerIcon />
              <span className="mobile-composer-submit-label">提交中…</span>
            </>
          ) : (
            <>
              <SendIcon />
              <span className="mobile-composer-submit-label">{meta.submitLabel}</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
}
