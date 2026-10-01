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

function compareToolRuns(left: ToolRun, right: ToolRun): number {
  return (left.timeline_order ?? 0) - (right.timeline_order ?? 0) || left.sequence - right.sequence;
}

/**
 * 手机聊天时间线只消费 mobileStore 已按 stream_id、sequence 和会话归并的状态。
 * WebSocket 事件不得在 Hook 内二次订阅，否则重复事件与旧连接事件会再次拼接。
 *
 * 排序：消息保持服务端顺序（created_at 严格递增，新消息按到达追加，状态变化原位替换）。
 * 工具卡与助手 segment 共用 timeline_order，工具卡插到第一条 timeline_order 更大的
 * 消息之前；用户和角色消息没有 timeline_order，不参与比较。无序号的旧工具记录排在最后，
 * 排队项始终在末尾。
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
    const toolItem = (toolRun: ToolRun): TimelineItem => ({
      kind: "tool_run",
      id: `tool-${toolRun.tool_call_id}`,
      toolRun,
    });
    const orderedTools = toolRuns
      .filter((toolRun) => typeof toolRun.timeline_order === "number")
      .sort(compareToolRuns);
    const legacyTools = toolRuns
      .filter((toolRun) => typeof toolRun.timeline_order !== "number")
      .sort((left, right) => left.sequence - right.sequence);

    let nextTool = 0;
    for (const message of messages) {
      const order = message.timeline_order;
      if (typeof order === "number") {
        while (
          nextTool < orderedTools.length &&
          (orderedTools[nextTool].timeline_order as number) < order
        ) {
          list.push(toolItem(orderedTools[nextTool]));
          nextTool += 1;
        }
      }
      list.push({ kind: "message", id: `msg-${message.message_id}`, message });
    }
    orderedTools.slice(nextTool).forEach((toolRun) => list.push(toolItem(toolRun)));
    legacyTools.forEach((toolRun) => list.push(toolItem(toolRun)));

    queueItems
      .filter((queueItem) => queueItem.conversation_id === conversationId)
      .sort((left, right) => left.position - right.position)
      .forEach((queueItem) => {
        list.push({
          kind: "queue_item",
          id: `queue-${queueItem.queue_item_id}`,
          queueItem,
        });
      });

    return list;
  }, [conversationId, messages, toolRuns, queueItems]);

  const isStreaming = useMemo(
    () =>
      messages.some((message) => message.streaming === true) ||
      toolRuns.some((toolRun) => toolRun.status === "running"),
    [messages, toolRuns],
  );

  return { items, messages, toolRuns, isStreaming };
}
