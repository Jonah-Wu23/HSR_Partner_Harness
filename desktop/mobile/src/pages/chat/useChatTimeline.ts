import { useMemo } from "react";
import type { Message, QueueItem, ToolRun } from "@shared/contracts/protocol";
import { useMobileStore } from "../../lib/mobileStore";

export type TimelineItem =
  | {
      kind: "message";
      id: string;
      message: Message;
    }
  | {
      kind: "tool_run";
      id: string;
      toolRun: ToolRun;
    }
  | {
      /** 忙时排队或派发失败的用户消息。 */
      kind: "queue_item";
      id: string;
      queueItem: QueueItem;
    };

/**
 * 手机聊天时间线只消费 mobileStore 已按 stream_id、sequence 和会话归并的状态，
 * Hook 内不再订阅 WebSocket 事件。
 *
 * 消息与工具记录共用同一聊天内的 timeline_order，时间线按它排序；排队项在末尾按 position 排列。
 */
export function useChatTimeline(conversationId: string): TimelineItem[] {
  const messages = useMobileStore((state) => state.messages);
  const toolRuns = useMobileStore((state) => state.toolRuns);
  const queueItems = useMobileStore((state) => state.queueItems);

  return useMemo(() => {
    const ordered: Array<{ order: number; item: TimelineItem }> = [
      ...messages
        .filter((message) => message.conversation_id === conversationId)
        .map((message) => ({
          order: message.timeline_order,
          item: { kind: "message", id: `msg-${message.message_id}`, message } as const,
        })),
      ...toolRuns
        .filter((toolRun) => toolRun.conversation_id === conversationId)
        .map((toolRun) => ({
          order: toolRun.timeline_order,
          item: { kind: "tool_run", id: `tool-${toolRun.tool_call_id}`, toolRun } as const,
        })),
    ];
    ordered.sort((left, right) => left.order - right.order);
    const queued: TimelineItem[] = queueItems
      .filter((queueItem) => queueItem.conversation_id === conversationId)
      .sort((left, right) => left.position - right.position)
      .map((queueItem) => ({ kind: "queue_item", id: `queue-${queueItem.queue_item_id}`, queueItem }));
    return [...ordered.map((entry) => entry.item), ...queued];
  }, [conversationId, messages, toolRuns, queueItems]);
}
