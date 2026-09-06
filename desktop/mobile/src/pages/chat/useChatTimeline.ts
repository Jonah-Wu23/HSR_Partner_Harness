import { useMemo } from "react";
import type { Message, QueueItem, ToolRun } from "@shared/contracts/protocol";
import { useMobileStore } from "../../lib/mobileStore";

export type TimelineItem =
  | {
      kind: "message";
      id: string;
      message: Message;
      order: number;
    }
  | {
      kind: "tool_run";
      id: string;
      toolRun: ToolRun;
      order: number;
    }
  | {
      /** V0.3.8 T5（契约 §14.1）：忙时排队中的用户消息（可撤回/编辑/置顶）。 */
      kind: "queue_item";
      id: string;
      queueItem: QueueItem;
      order: number;
    };

/**
 * 手机聊天时间线只消费 mobileStore 已按 stream_id、sequence 和会话归并的状态。
 * WebSocket 事件不得在 Hook 内二次订阅，否则重复事件与旧连接事件会再次拼接。
 */
export function useChatTimeline(conversationId: string) {
  const storeMessages = useMobileStore((state) => state.messages);
  const storeToolRuns = useMobileStore((state) => state.toolRuns);
  const queueItems = useMobileStore((state) => state.queueItems);

  const messages = useMemo(
    () => storeMessages.filter((message) => message.conversation_id === conversationId),
    [conversationId, storeMessages],
  );
  const toolRuns = useMemo(
    () => storeToolRuns.filter((toolRun) => toolRun.conversation_id === conversationId),
    [conversationId, storeToolRuns],
  );

  const items = useMemo<TimelineItem[]>(() => {
    const list: TimelineItem[] = [];

    messages.forEach((message, index) => {
      list.push({
        kind: "message",
        id: `msg-${message.message_id}`,
        message,
        order:
          typeof message.timeline_order === "number"
            ? message.timeline_order
            : index * 10,
      });
    });

    toolRuns.forEach((toolRun, index) => {
      list.push({
        kind: "tool_run",
        id: `tool-${toolRun.tool_call_id}`,
        toolRun,
        order:
          typeof toolRun.timeline_order === "number"
            ? toolRun.timeline_order
            : (toolRun.sequence ?? index) * 10 + 5,
      });
    });

    // 排队项天然在当前回合之后：order 取消息最大 order 之后的偏移段。
    const lastOrder = list.reduce((max, item) => Math.max(max, item.order), 0);
    queueItems
      .filter((queueItem) => queueItem.conversation_id === conversationId)
      .forEach((queueItem) => {
        list.push({
          kind: "queue_item",
          id: `queue-${queueItem.queue_item_id}`,
          queueItem,
          order: lastOrder + 1000 + queueItem.position,
        });
      });

    return list.sort((a, b) => a.order - b.order);
  }, [messages, toolRuns, queueItems]);

  const isStreaming = useMemo(
    () =>
      messages.some((message) => message.streaming === true) ||
      toolRuns.some((toolRun) => toolRun.status === "running"),
    [messages, toolRuns],
  );

  return { items, messages, toolRuns, isStreaming };
}
