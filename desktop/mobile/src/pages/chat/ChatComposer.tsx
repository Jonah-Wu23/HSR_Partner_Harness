import {
  type FormEvent,
  type KeyboardEvent,
  type RefObject,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { CloseIcon, SendIcon, SpinnerIcon } from "../../components/cards/icons";

export type ChatComposerTarget = "character" | "assistant";

export interface ChatComposerProps {
  target: ChatComposerTarget;
  onSubmit: (text: string) => Promise<void>;
  disabled?: boolean;
  /** 前置禁用原因（如对话模式下助手不可用），展示在输入区上方。 */
  disabledHint?: string | null;
}

/** 输入框自增高上限，超过后内部滚动；与 chat.css 的 max-height 一致。 */
export const COMPOSER_MAX_TEXTAREA_HEIGHT_PX = 160;

/** 支持 field-sizing 的引擎由 CSS 按内容自增高，输入时不需要脚本测量。 */
const SUPPORTS_FIELD_SIZING = CSS.supports("field-sizing", "content");

/**
 * 输入框高度：内容高度为 0（尚未布局）时返回 null，调用方跳过设置；
 * 未超过上限时返回内容高度，超过后封顶，由 CSS overflow-y 内部滚动。
 */
export function computeTextareaHeight(
  scrollHeight: number,
  maxHeightPx: number = COMPOSER_MAX_TEXTAREA_HEIGHT_PX,
): number | null {
  if (!Number.isFinite(scrollHeight) || scrollHeight <= 0) return null;
  return Math.min(scrollHeight, maxHeightPx);
}

/**
 * 不支持 field-sizing 时按内容设置高度：在绘制前测量，只有高度变化才写入。
 * 文本变长且仍放得下、或变短时仍是默认单行高度，都不测量；变短且已撑高时
 * 先复位到 auto 才能量出更小的内容高度。
 */
function useTextareaAutoHeight(
  textareaRef: RefObject<HTMLTextAreaElement | null>,
  text: string,
): void {
  const previousLengthRef = useRef(0);
  useLayoutEffect(() => {
    if (SUPPORTS_FIELD_SIZING) return;
    const node = textareaRef.current;
    if (!node) return;
    const shrinking = text.length < previousLengthRef.current;
    previousLengthRef.current = text.length;
    if (!text) {
      if (node.style.height) node.style.height = "";
      return;
    }
    if (shrinking ? !node.style.height : node.scrollHeight <= node.clientHeight) return;
    const previousHeight = node.style.height;
    if (shrinking) node.style.height = "auto";
    const borderHeight = node.offsetHeight - node.clientHeight;
    const next = computeTextareaHeight(node.scrollHeight + borderHeight);
    const nextHeight = next === null ? previousHeight : `${next}px`;
    if (node.style.height !== nextHeight) node.style.height = nextHeight;
  }, [text, textareaRef]);
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
 * 手机端聊天输入区：
 * - target=character：普通角色消息，任何模式可用；
 * - target=assistant：委派任务，只在协作模式可用，由调用方禁用并说明原因。
 * 提交失败时展示错误原文并保留输入。
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useTextareaAutoHeight(textareaRef, text);

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
      setError(err instanceof Error ? err.message : String(err));
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
            ref={textareaRef}
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
