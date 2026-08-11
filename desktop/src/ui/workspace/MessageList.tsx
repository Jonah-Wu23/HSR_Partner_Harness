import { useEffect, useRef, useState } from "react";
import type { Message, PairRecord } from "../../contracts/protocol";
import type { ConversationTimelineViewModel } from "../../contracts/view-models";
import { CollapseIcon } from "../../assets/icons/icons";

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

function ReasoningBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="msg-reasoning">
      <button
        type="button"
        className={`msg-reasoning-toggle${open ? " is-open" : ""}`}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <CollapseIcon style={{ transform: "rotate(-90deg)" }} />
        思考过程
      </button>
      {open ? <div className="msg-reasoning-body">{text}</div> : null}
    </div>
  );
}

function Bubble({ message, pair }: { message: Message; pair: PairRecord }) {
  const label = sourceLabel(message, pair);
  const reasoning =
    typeof message.payload?.reasoning === "string" ? (message.payload.reasoning as string) : null;
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

  return (
    <div className={rowClass} data-message-source={message.source}>
      <div className={bubbleClass}>
        {reasoning ? <ReasoningBlock text={reasoning} /> : null}
        {label ? <span className="msg-source">{label}</span> : null}
        {message.text}
        {message.streaming ? <span className="msg-streaming-caret" aria-hidden /> : null}
      </div>
    </div>
  );
}

/** 消息流：气泡分色、思考折叠、流式光标、近底部自动跟随。 */
export function MessageList({ timeline, pair, emptyText }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  const checkPinned = () => {
    const node = scrollRef.current;
    if (!node) return;
    setPinned(node.scrollHeight - node.scrollTop - node.clientHeight < 80);
  };

  useEffect(() => {
    const node = scrollRef.current;
    if (node && pinned) node.scrollTop = node.scrollHeight;
  }, [timeline.messages, timeline.isStreaming, pinned]);

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
