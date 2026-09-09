import type { ActiveTask, PendingApproval, QueueItem } from "@shared/contracts/protocol";
import { useMobileStore } from "../../lib/mobileStore";

/**
 * V0.3.9 V01：会话行徽章数据（组件内适配层，store 归逻辑轨）。
 *
 * 契约依据（docs/plans/V0.3.9-契约冻结.md）：
 * - §3 运行快照：active_tasks 是全账号权威集合，active_task 仅当前/目标聊天的兼容视图；
 * - §3 本地未读：只在客户端本地派生，键为 conversation_id + message_id，仅后台聊天
 *   收到新的最终 character/assistant 消息计数，进入该聊天即清零；
 * - §5 指标：未观测字段必须为 null 且键仍存在，真实零值用 0；本文件同样区分
 *   「无数据源（null）」与「真实零值（0）」，未知一律不渲染徽章。
 *
 * 待真实接线：mobileStore 目前只提供单会话 activeTask，不提供 active_tasks 全量集合、
 * 未读派生与每聊天最近终态。本适配层按上述契约在 store 上读取可选字段；字段缺失时
 * 返回 null（未知），绝不把未知当成 0 或 false 渲染。
 */

/** 每聊天最近终态（来自 turn.status_changed / message.status_changed 的真实终态）。 */
export interface ConversationTerminal {
  status: "completed" | "failed" | "cancelled";
  /** 失败/取消的原始错误文本；无值保持 null。 */
  error: string | null;
  /** 终态产生时间；无值保持 null。 */
  at: string | null;
}

/**
 * 徽章数据来源。每个字段的 null 语义都是「客户端尚未取得该数据源」，
 * 空数组/空对象才是「真实为零」。
 */
export interface ConversationBadgeSource {
  /** 契约 §3 权威全量活动任务集合；null = 尚未取得全量集合。 */
  activeTasks: ActiveTask[] | null;
  /** 兼容视图 active_task：只能证明「这个聊天在运行」，不能证明其他聊天空闲。 */
  activeTask: ActiveTask | null;
  /** 待审批列表（store.approvals，已含 conversation_id）。 */
  approvals: PendingApproval[] | null;
  /** 队列项（store.queueItems，已含 conversation_id 与 status）。 */
  queueItems: QueueItem[] | null;
  /** 未读计数（键 conversation_id）；null = 尚未取得未读派生。 */
  unreadByConversation: Record<string, number> | null;
  /** 每聊天最近终态；null = 尚未取得终态派生。 */
  terminalByConversation: Record<string, ConversationTerminal> | null;
}

/** 单个会话行的徽章数据；null 表示未知，组件不得渲染为 0。 */
export interface ConversationBadges {
  running: boolean | null;
  pendingApprovals: number | null;
  queued: number | null;
  unread: number | null;
  lastTerminal: ConversationTerminal | null;
}

export function deriveConversationBadges(
  conversationId: string,
  source: ConversationBadgeSource,
): ConversationBadges {
  const running =
    source.activeTasks !== null
      ? source.activeTasks.some((task) => task.conversation_id === conversationId)
      : source.activeTask?.conversation_id === conversationId
        ? true
        : null;

  const pendingApprovals =
    source.approvals === null
      ? null
      : source.approvals.filter((item) => item.conversation_id === conversationId).length;

  const queued =
    source.queueItems === null
      ? null
      : source.queueItems.filter(
          (item) => item.conversation_id === conversationId && item.status === "queued",
        ).length;

  const unread =
    source.unreadByConversation === null
      ? null
      : (source.unreadByConversation[conversationId] ?? 0);

  const lastTerminal =
    source.terminalByConversation === null
      ? null
      : (source.terminalByConversation[conversationId] ?? null);

  return { running, pendingApprovals, queued, unread, lastTerminal };
}

/** store 上尚未冻结的可选扩展字段（逻辑轨补齐后本类型即可删除）。 */
interface BadgeStoreExtensions {
  activeTasks?: ActiveTask[] | null;
  unreadByConversation?: Record<string, number> | null;
  terminalByConversation?: Record<string, ConversationTerminal> | null;
}

/** 从 mobileStore 读取徽章数据源（只读，不修改 store）。 */
export function useConversationBadgeSource(): ConversationBadgeSource {
  const activeTask = useMobileStore((state) => state.activeTask);
  const approvals = useMobileStore((state) => state.approvals);
  const queueItems = useMobileStore((state) => state.queueItems);
  const extensions = useMobileStore(
    (state) => state as unknown as BadgeStoreExtensions,
  );

  return {
    // 待真实接线：store 补齐 active_tasks 全量集合后直接透传；缺失时为 null（未知）。
    activeTasks: extensions.activeTasks ?? null,
    activeTask: activeTask ?? null,
    approvals: approvals ?? null,
    queueItems: queueItems ?? null,
    unreadByConversation: extensions.unreadByConversation ?? null,
    terminalByConversation: extensions.terminalByConversation ?? null,
  };
}
