import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Message, PairRecord } from "../../contracts/protocol";
import type { ConversationTimelineViewModel } from "../../contracts/view-models";
import { ReasoningRibbon } from "./ReasoningRibbon";

interface MessageListProps {
  timeline: ConversationTimelineViewModel;
  pair: PairRecord;
  emptyText: string;
}

function sourceLabel(message: Message, pair: PairRecord): string | null {
  if (message.source === "character") return pair.character.name;
  if (message.source === "assistant") return pair.assistant.name;
  if (message.source === "user") return "你";
  return null;
}

function Bubble({ message, pair }: { message: Message; pair: PairRecord }) {
  const label = sourceLabel(message, pair);
  const reasoning =
    typeof message.payload?.reasoning === "string" ? (message.payload.reasoning as string) : null;
  const reasoningStreaming = message.payload?.reasoning_streaming === true;
  const reasoningSeconds =
    typeof message.payload?.reasoning_seconds === "number"
      ? (message.payload.reasoning_seconds as number)
      : undefined;
  const rowClass =
    message.source === "user"
      ? "msg-row msg-row-user"
      : message.source === "system" || message.source === "tool"
        ? "msg-row msg-row-system"
        : "msg-row";
  const bubbleClass =
    message.source === "character"
      ? "msg-bubble msg-character"
      : message.source === "assistant"
        ? "msg-bubble msg-assistant"
      : message.source === "user"
          ? "msg-bubble msg-user"
          : "msg-bubble msg-system";
  const displayText = message.text || (message.streaming ? "..." : "");

  return (
    <div className={rowClass} data-message-source={message.source}>
      <div className={bubbleClass}>
        {reasoning !== null || reasoningStreaming ? (
          <ReasoningRibbon text={reasoning ?? ""} streaming={reasoningStreaming} elapsedSeconds={reasoningSeconds} />
        ) : null}
        {label ? <span className="msg-source">{label}</span> : null}
        {displayText}
        {message.streaming && message.text ? <span className="msg-streaming-caret" aria-hidden /> : null}
      </div>
    </div>
  );
}

/** 消息流：气泡分色、思考折叠、流式光标、近底部自动跟随。 */
export function MessageList({ timeline, pair, emptyText }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const shouldVirtualize = timeline.messages.length > 50;
  const virtualizer = useVirtualizer({
    count: timeline.messages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 76,
    overscan: 8,
    getItemKey: (index) => timeline.messages[index]?.message_id ?? index,
  });

  const checkPinned = () => {
    const node = scrollRef.current;
    if (!node) return;
    setPinned(node.scrollHeight - node.scrollTop - node.clientHeight < 80);
  };

  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !pinned || timeline.messages.length === 0) return;
    if (shouldVirtualize) {
      virtualizer.scrollToIndex(timeline.messages.length - 1, { align: "end" });
    } else {
      node.scrollTop = node.scrollHeight;
    }
  }, [timeline.messages, timeline.isStreaming, pinned, shouldVirtualize, virtualizer]);

  useEffect(() => {
    if (shouldVirtualize) virtualizer.measure();
  }, [timeline.messages, shouldVirtualize, virtualizer]);

  const jumpToLatest = () => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
    setPinned(true);
  };

  return (
    <div className="message-scroll" ref={scrollRef} onScroll={checkPinned}>
      <div className="message-column">
        {timeline.messages.length === 0 ? (
          <div className="msg-row msg-row-system">
            <div className="msg-bubble msg-system">{emptyText}</div>
          </div>
        ) : shouldVirtualize ? (
          <div
            className="message-column message-column-virtual"
            style={{ height: `${virtualizer.getTotalSize()}px` }}
          >
            {virtualizer.getVirtualItems().map((item) => {
              const message = timeline.messages[item.index];
              return message ? (
                <div
                  key={item.key}
                  ref={virtualizer.measureElement}
                  data-index={item.index}
                  className="message-virtual-row"
                  style={{ transform: `translateY(${item.start}px)` }}
                >
                  <Bubble message={message} pair={pair} />
                </div>
              ) : null;
            })}
          </div>
        ) : (
          timeline.messages.map((message) => (
            <Bubble key={message.message_id} message={message} pair={pair} />
          ))
        )}
      </div>
      {!pinned ? (
        <button type="button" className="scroll-latest-btn" onClick={jumpToLatest}>
          回到最新
        </button>
      ) : null}
    </div>
  );
}
