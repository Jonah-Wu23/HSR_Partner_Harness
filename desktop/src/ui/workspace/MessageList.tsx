import { useMemo } from "react";
import type { Message, MessageSource, PairRecord } from "../../contracts/protocol";
import type { ConversationTimelineViewModel } from "../../contracts/view-models";
import { ConversationList, type ConversationItemState } from "../conversation/ConversationList";
import { ReasoningRibbon } from "./ReasoningRibbon";

interface MessageListProps {
  timeline: ConversationTimelineViewModel;
  pair: PairRecord;
  emptyText: string;
}

const ROW_CLASS: Record<MessageSource, string> = {
  user: "msg-row msg-row-user",
  system: "msg-row msg-row-system",
  tool: "msg-row msg-row-system",
  character: "msg-row",
  assistant: "msg-row",
};

const BUBBLE_CLASS: Record<MessageSource, string> = {
  character: "msg-bubble msg-character",
  assistant: "msg-bubble msg-assistant",
  user: "msg-bubble msg-user",
  system: "msg-bubble msg-system",
  tool: "msg-bubble msg-system",
};

function sourceLabel(message: Message, pair: PairRecord): string | null {
  if (message.source === "character") return pair.character.name;
  if (message.source === "assistant") return pair.assistant.name;
  if (message.source === "user") return "你";
  return null;
}

export function MessageBubble({
  message,
  pair,
  itemState,
}: {
  message: Message;
  pair: PairRecord;
  itemState?: ConversationItemState;
}) {
  const label = sourceLabel(message, pair);
  const reasoning =
    typeof message.payload?.reasoning === "string" ? message.payload.reasoning : null;
  const reasoningStreaming = message.payload?.reasoning_streaming === true;
  const reasoningSeconds =
    typeof message.payload?.reasoning_seconds === "number"
      ? message.payload.reasoning_seconds
      : undefined;
  const rowClass = ROW_CLASS[message.source];
  const baseBubbleClass = BUBBLE_CLASS[message.source];
  const displayText = message.text || (message.streaming ? "..." : "");

  const isFailed = message.status === "failed";
  const isCancelled = message.status === "cancelled";
  const isQueued = message.status === "queued";
  const errorMessage =
    isFailed
      ? (typeof message.payload?.error === "string" && message.payload.error
          ? message.payload.error
          : typeof message.payload?.error_message === "string" && message.payload.error_message
            ? message.payload.error_message
            : null)
      : null;
  const cancelledReason =
    isCancelled
      ? (typeof message.payload?.cancelled_reason === "string" && message.payload.cancelled_reason
          ? message.payload.cancelled_reason
          : typeof message.payload?.reason === "string" && message.payload.reason
            ? message.payload.reason
            : null)
      : null;

  const statusModifier = isFailed
    ? " is-failed msg-bubble-failed"
    : isCancelled
      ? " is-cancelled msg-bubble-cancelled"
      : isQueued
        ? " is-queued msg-bubble-queued"
        : "";

  return (
    <div
      className={`${rowClass}${isFailed ? " is-failed" : ""}${isCancelled ? " is-cancelled" : ""}`}
      data-message-source={message.source}
      data-message-status={message.status ?? (message.streaming ? "streaming" : "done")}
    >
      <div className={`${baseBubbleClass}${statusModifier}`}>
        {reasoning !== null || reasoningStreaming ? (
          <ReasoningRibbon
            text={reasoning ?? ""}
            streaming={reasoningStreaming}
            elapsedSeconds={reasoningSeconds}
            expanded={itemState?.isExpanded(`reasoning:${message.message_id}`, reasoningStreaming)}
            onExpandedChange={(expanded) => itemState?.setExpanded(`reasoning:${message.message_id}`, expanded)}
          />
        ) : null}
        {label ? (
          <span className="msg-source">
            {label}
            {isQueued ? <span className="msg-status-tag-queued">排队中</span> : null}
          </span>
        ) : null}
        {displayText}
        {message.streaming && message.text ? <span className="msg-streaming-caret" aria-hidden /> : null}

        {isFailed ? (
          <div className="msg-status-banner msg-status-failed" role="alert" data-testid="msg-status-failed">
            <span className="msg-status-tag">失败</span>
            <span className="msg-status-detail">{errorMessage || "执行失败（未返回具体错误）"}</span>
          </div>
        ) : null}

        {isCancelled ? (
          <div className="msg-status-banner msg-status-cancelled" data-testid="msg-status-cancelled">
            <span className="msg-status-tag">已取消</span>
            {cancelledReason ? <span className="msg-status-detail">{cancelledReason}</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

type MessageListItem =
  | { kind: "message"; id: string; message: Message }
  | { kind: "queue"; id: string; text: string; status: string };

const messageItemKey = (item: MessageListItem) => item.id;

/** 消息流：气泡分色、思考折叠、流式光标与动态高度虚拟窗口。 */
export function MessageList({ timeline, pair, emptyText }: MessageListProps) {
  const items = useMemo<MessageListItem[]>(() => [
    ...timeline.messages.map((message) => ({
      kind: "message" as const,
      id: `message:${message.message_id}`,
      message,
    })),
    ...timeline.queueItems.map((item) => ({
      kind: "queue" as const,
      id: `queue:${item.queue_item_id}`,
      text: item.text,
      status: item.status,
    })),
  ], [timeline.messages, timeline.queueItems]);

  return (
    <ConversationList
      conversationId={timeline.conversationId}
      items={items}
      getItemKey={messageItemKey}
      estimateSize={76}
      overscan={8}
      scrollClassName="message-scroll"
      contentClassName="message-column"
      rowClassName="message-virtual-row"
      emptyContent={(
        <div className="msg-row msg-row-system">
          <div className="msg-bubble msg-system">{emptyText}</div>
        </div>
      )}
      renderItem={(item, itemState) => item.kind === "message" ? (
        <MessageBubble message={item.message} pair={pair} itemState={itemState} />
      ) : (
        <div className="msg-row msg-row-user" data-queued="true">
          <div className="msg-bubble msg-user queue-in-stream-bubble">
            <span className="queue-in-stream-badge">{item.status === "processing" ? "执行中" : "排队中"}</span>
            {item.text}
          </div>
        </div>
      )}
      renderJumpButton={(jump) => (
        <button type="button" className="scroll-latest-btn" onClick={jump}>
          回到最新
        </button>
      )}
    />
  );
}
