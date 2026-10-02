import type { ActiveTask, PendingApproval, QueueItem } from "@shared/contracts/protocol";
import { useMobileStore } from "../../lib/mobileStore";

/** 会话行徽章的数据来源。 */
export interface ConversationBadgeSource {
  /** 全账号活动任务集合。 */
  activeTasks: ActiveTask[];
  /** 待审批列表（各项带 conversation_id）。 */
  approvals: PendingApproval[];
  /** 当前打开聊天的排队项。 */
  queueItems: QueueItem[];
}

/** 单个会话行的徽章数据。 */
export interface ConversationBadges {
  running: boolean;
  pendingApprovals: number;
  queued: number;
}

export function deriveConversationBadges(
  conversationId: string,
  source: ConversationBadgeSource,
): ConversationBadges {
  return {
    running: source.activeTasks.some((task) => task.conversation_id === conversationId),
    pendingApprovals: source.approvals.filter((item) => item.conversation_id === conversationId)
      .length,
    queued: source.queueItems.filter(
      (item) => item.conversation_id === conversationId && item.status === "queued",
    ).length,
  };
}

export function useConversationBadgeSource(): ConversationBadgeSource {
  const activeTasks = useMobileStore((state) => state.activeTasks);
  const approvals = useMobileStore((state) => state.approvals);
  const queueItems = useMobileStore((state) => state.queueItems);
  return { activeTasks, approvals, queueItems };
}
