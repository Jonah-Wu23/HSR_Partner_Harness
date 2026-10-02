import type { ReactNode } from "react";
import type { ConversationBadges } from "./useConversationBadges";
import "./ConversationBadges.css";

/** 会话行徽章：运行中、待审批、排队；数值为 0 或 false 时不渲染。 */

export interface ConversationBadgeRowProps {
  conversationId: string;
  badges: ConversationBadges;
}

export function ConversationBadgeRow({
  conversationId,
  badges,
}: ConversationBadgeRowProps) {
  const items: ReactNode[] = [];

  if (badges.running) {
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

  if (badges.pendingApprovals > 0) {
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

  if (badges.queued > 0) {
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
