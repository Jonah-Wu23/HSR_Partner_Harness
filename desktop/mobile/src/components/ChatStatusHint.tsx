import "./ChatStatusHint.css";

export interface ChatStatusHintProps {
  /** 连接已建立但快照装载与事件重放尚未完成。 */
  resyncing: boolean;
}

/** 聊天页内的「正在重新同步」提示；连接状态由顶部 ConnectionBanner 展示。 */
export function ChatStatusHint({ resyncing }: ChatStatusHintProps) {
  if (!resyncing) return null;
  return (
    <aside
      className="chat-status-hint"
      role="status"
      aria-live="polite"
      data-testid="chat-status-hint"
    >
      <span className="chat-status-line is-resync" data-testid="chat-status-resync">
        正在重新同步…
      </span>
    </aside>
  );
}
