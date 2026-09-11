import type { ReactNode } from "react";
import type { ConversationBadges, ConversationTerminal } from "./useConversationBadges";
import "./ConversationBadges.css";

/**
 * V0.3.9 V01：会话行徽章（运行中 / 待审批 / 排队 / 未读 / 最近终态）。
 *
 * 渲染纪律（契约 §3、§5）：
 * - 字段为 null 表示「尚未取得该数据源」→ 不渲染该徽章，绝不用 0 或 false 顶替；
 * - 字段为 0 / false 表示真实零值 → 同样不渲染（没有可提示的事）；
 * - 未知终态不渲染，避免用「上次完成」这类文案冒充真实终态。
 */

const TERMINAL_LABELS: Record<ConversationTerminal["status"], string> = {
  completed: "上次完成",
  failed: "上次失败",
  cancelled: "上次已取消",
};

export interface ConversationBadgeRowProps {
  conversationId: string;
  badges: ConversationBadges;
}

export function ConversationBadgeRow({
  conversationId,
  badges,
}: ConversationBadgeRowProps) {
  const items: ReactNode[] = [];

  if (badges.running === true) {
    items.push(
      <span
        key="running"
        className="conv-badge is-running"
        data-testid={`badge-running-${conversationId}`}
      >
        运行中
      </span>,
    );
  }

  if (badges.pendingApprovals !== null && badges.pendingApprovals > 0) {
    items.push(
      <span
        key="approvals"
        className="conv-badge is-approval"
        data-testid={`badge-approvals-${conversationId}`}
      >
        待审批 {badges.pendingApprovals}
      </span>,
    );
  }

  if (badges.queued !== null && badges.queued > 0) {
    items.push(
      <span
        key="queued"
        className="conv-badge is-queued"
        data-testid={`badge-queued-${conversationId}`}
      >
        排队 {badges.queued}
      </span>,
    );
  }

  if (badges.unread !== null && badges.unread > 0) {
    items.push(
      <span
        key="unread"
        className="conv-badge is-unread"
        data-testid={`badge-unread-${conversationId}`}
      >
        未读 {badges.unread}
      </span>,
    );
  }

  if (badges.lastTerminal !== null) {
    const terminal = badges.lastTerminal;
    const label = TERMINAL_LABELS[terminal.status];
    const error = terminal.error ?? null;
    items.push(
      <span
        key="terminal"
        className={`conv-badge badge-status-${terminal.status}`}
        data-testid={`badge-terminal-${conversationId}`}
        data-status={terminal.status}
        title={error ?? undefined}
        aria-label={error ? `${label}：${error}` : label}
      >
        {label}
      </span>,
    );
  }

  if (items.length === 0) {
    return null;
  }

  return (
    <span
      className="conversation-badges"
      data-testid={`conversation-badges-${conversationId}`}
      aria-label="会话状态"
    >
      {items}
    </span>
  );
}
