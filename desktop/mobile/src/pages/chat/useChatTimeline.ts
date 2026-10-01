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

type OrderedItem = Extract<TimelineItem, { kind: "message" | "tool_run" }>;

const EMPTY_TIMELINE: TimelineItem[] = [];

// 同一条记录复用同一个时间线项：流式更新时未变化的行引用不变，列表行组件可以整行跳过。
const messageItems = new WeakMap<Message, OrderedItem>();
const toolRunItems = new WeakMap<ToolRun, OrderedItem>();

function messageItem(message: Message): OrderedItem {
  let item = messageItems.get(message);
  if (!item) {
    item = { kind: "message", id: `msg-${message.message_id}`, message };
    messageItems.set(message, item);
  }
  return item;
}

function toolRunItem(toolRun: ToolRun): OrderedItem {
  let item = toolRunItems.get(toolRun);
  if (!item) {
    item = { kind: "tool_run", id: `tool-${toolRun.tool_call_id}`, toolRun };
    toolRunItems.set(toolRun, item);
  }
  return item;
}

function timelineOrder(item: OrderedItem): number {
  return item.kind === "message" ? item.message.timeline_order : item.toolRun.timeline_order;
}

function byTimelineOrder(left: OrderedItem, right: OrderedItem): number {
  return timelineOrder(left) - timelineOrder(right);
}

/** 合并两段各自有序的时间线；序号相同时消息在前。 */
function mergeByTimelineOrder(messages: OrderedItem[], toolRuns: OrderedItem[]): TimelineItem[] {
  if (toolRuns.length === 0) return messages;
  if (messages.length === 0) return toolRuns;
  const merged: TimelineItem[] = [];
  let left = 0;
  let right = 0;
  while (left < messages.length && right < toolRuns.length) {
    merged.push(
      timelineOrder(messages[left]) <= timelineOrder(toolRuns[right])
        ? messages[left++]
        : toolRuns[right++],
    );
  }
  while (left < messages.length) merged.push(messages[left++]);
  while (right < toolRuns.length) merged.push(toolRuns[right++]);
  return merged;
}

/**
 * 手机聊天时间线只消费 mobileStore 已按 stream_id、sequence 和会话归并的状态，
 * Hook 内不再订阅 WebSocket 事件。
 *
 * store 里的消息、工具记录与排队项都属于 activeConversationId；页面路由的聊天还没成为
 * 当前聊天时返回空时间线。消息与工具记录共用同一聊天内的 timeline_order，各自排序后合并，
 * 流式更新只重排消息；排队项在末尾按 position 排列。
 */
export function useChatTimeline(conversationId: string): TimelineItem[] {
  const owned = useMobileStore((state) => state.activeConversationId === conversationId);
  const messages = useMobileStore((state) => state.messages);
  const toolRuns = useMobileStore((state) => state.toolRuns);
  const queueItems = useMobileStore((state) => state.queueItems);

  const orderedMessages = useMemo(
    () => messages.map(messageItem).sort(byTimelineOrder),
    [messages],
  );
  const orderedToolRuns = useMemo(
    () => toolRuns.map(toolRunItem).sort(byTimelineOrder),
    [toolRuns],
  );
  const queuedItems = useMemo(
    () =>
      [...queueItems]
        .sort((left, right) => left.position - right.position)
        .map((queueItem): TimelineItem => ({
          kind: "queue_item",
          id: `queue-${queueItem.queue_item_id}`,
          queueItem,
        })),
    [queueItems],
  );

  return useMemo(() => {
    if (!owned) return EMPTY_TIMELINE;
    const ordered = mergeByTimelineOrder(orderedMessages, orderedToolRuns);
    return queuedItems.length === 0 ? ordered : [...ordered, ...queuedItems];
  }, [owned, orderedMessages, orderedToolRuns, queuedItems]);
}
