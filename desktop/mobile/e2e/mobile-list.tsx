import { StrictMode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Message, ToolRun } from "../../src/contracts/protocol";
import type { ConversationItemState } from "../../src/ui/conversation/ConversationList";
import { ConversationList } from "../../src/ui/conversation/ConversationList";
import type { TimelineItem } from "../src/pages/chat/useChatTimeline";
import { MessageBubble } from "../src/pages/chat/MessageBubble";
import { ToolCard } from "../src/components/cards/ToolCard";
import "../src/styles.css";
import "../src/pages/chat/chat.css";

function makeMessage(index: number, text?: string): Message {
  return {
    message_id: `mobile-message-${index}`,
    conversation_id: "mobile-simulation",
    pair_id: "pair-playwright",
    engine_turn_id: null,
    source: index % 4 === 0 ? "user" : "character",
    kind: index % 4 === 0 ? "user.text" : "character.speech",
    text: text ?? `手机模拟消息 ${index}${index % 9 === 0 ? "\n" + "不同宽度下会自动换行。 ".repeat(16) : ""}`,
    payload: {},
    tts_eligible: false,
    created_at: new Date(0).toISOString(),
    streaming: index === 40,
  };
}

function makeTool(index: number): ToolRun {
  return {
    tool_call_id: `mobile-tool-${index}`,
    conversation_id: "mobile-simulation",
    task_id: "simulated-task",
    engine_turn_id: "simulated-turn",
    sequence: index,
    status: "succeeded",
    title: `模拟脚本 ${index}`,
    summary: "模拟工具说明",
    details: `模拟命令输出 ${index}\n${"手机端长输出行。 ".repeat(30)}`,
  };
}

function makeItems(count: number): TimelineItem[] {
  return Array.from({ length: count }, (_, index) => index % 13 === 0
    ? { kind: "tool_run" as const, id: `tool:${index / 13}`, toolRun: makeTool(index / 13), order: index }
    : { kind: "message" as const, id: `message:${index}`, message: makeMessage(index), order: index });
}

function renderItem(item: TimelineItem, state: ConversationItemState) {
  if (item.kind === "tool_run") {
    const key = `tool:${item.toolRun.tool_call_id}`;
    return (
      <ToolCard
        run={item.toolRun}
        expanded={state.isExpanded(key)}
        onExpandedChange={(expanded) => state.setExpanded(key, expanded)}
      />
    );
  }
  return <MessageBubble message={item.message} pairNames={{ character: "模拟角色" }} itemState={state} />;
}

function Harness() {
  const [items, setItems] = useState(() => makeItems(41));
  const streamCommitWaiters = useRef<Array<() => void>>([]);

  useLayoutEffect(() => {
    streamCommitWaiters.current.splice(0).forEach((resolve) => resolve());
  }, [items]);

  useEffect(() => {
    (window as typeof window & { conversationHarness?: object }).conversationHarness = {
      setCount: (count: number) => setItems(makeItems(count)),
      growLatest: (suffix: string) => setItems((current) => current.map((item, index) =>
        index === current.length - 1 && item.kind === "message"
          ? { ...item, message: { ...item.message, text: item.message.text + suffix } }
          : item)),
      streamLatest: async (count: number) => {
        for (let index = 0; index < count; index += 1) {
          await new Promise<void>((resolve) => {
            streamCommitWaiters.current.push(resolve);
            setItems((current) => current.map((item, row) =>
              row === current.length - 1 && item.kind === "message"
                ? { ...item, message: { ...item.message, text: `${item.message.text} token-${index} ` } }
                : item));
          });
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
        }
      },
    };
  }, []);

  return (
    <main className="mobile-chat-container simulation-mobile-chat">
      <header className="mobile-chat-header">
        <div className="mobile-chat-title-group"><h1 className="mobile-chat-title">手机消息流模拟</h1></div>
        <span className="mobile-chat-subtitle">本地模拟数据</span>
      </header>
      <ConversationList
        conversationId="mobile-simulation"
        items={items}
        getItemKey={(item) => item.id}
        estimateSize={80}
        scrollClassName="mobile-chat-scroll"
        contentClassName="mobile-virtual-container"
        rowClassName="mobile-virtual-row"
        renderItem={renderItem}
        renderJumpButton={(jump) => <button type="button" className="mobile-jump-latest" onClick={jump}>回到最新</button>}
      />
      <footer className="mobile-composer"><div className="mobile-composer-body">模拟输入区域</div></footer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><Harness /></StrictMode>);
