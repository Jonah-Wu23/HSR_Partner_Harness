import { StrictMode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Message, PairRecord, ToolRun } from "../src/contracts/protocol";
import type { WorkspaceViewModel } from "../src/contracts/view-models";
import { Workspace } from "../src/ui/workspace/Workspace";
import "../src/styles/tokens.css";
import "../src/styles/base.css";
import "../src/styles/app.css";
import "./harness.css";

const pair: PairRecord = {
  pair_id: "pair-playwright",
  character: { id: "character", name: "模拟角色", voice_id: "" },
  assistant: { id: "assistant", name: "模拟助手", voice_id: "" },
  theme: {
    character_text: "#dce5f5",
    character_primary: "#86a2d5",
    character_deep: "#30436f",
    character_active: "#296ce1",
    assistant_primary: "#b08d57",
    assistant_bright: "#c5a059",
    assistant_shadow: "#8c6b3f",
  },
};

function makeMessage(index: number, text?: string): Message {
  return {
    message_id: `message-${index}`,
    conversation_id: "desktop-simulation",
    pair_id: pair.pair_id,
    engine_turn_id: null,
    source: index % 4 === 0 ? "user" : "character",
    kind: index % 4 === 0 ? "user.text" : "character.speech",
    text: text ?? `模拟消息 ${index}${index % 9 === 0 ? "\n" + "随消息增长的真实排版内容。 ".repeat(18) : ""}`,
    payload: {},
    tts_eligible: false,
    created_at: new Date(0).toISOString(),
    streaming: index === 38,
  };
}

function makeTool(index: number): ToolRun {
  return {
    tool_call_id: `tool-${index}`,
    conversation_id: "desktop-simulation",
    task_id: "simulated-task",
    engine_turn_id: "simulated-turn",
    sequence: index,
    status: index % 3 === 0 ? "running" : "succeeded",
    title: `模拟命令 ${index}`,
    summary: "模拟状态说明",
    details: `模拟工具输出 ${index}\n${"编译与测试输出行。 ".repeat(index % 4 === 0 ? 25 : 3)}`,
  };
}

function Harness() {
  const [messages, setMessages] = useState(() => Array.from({ length: 39 }, (_, index) => makeMessage(index)));
  const streamCommitWaiters = useRef<Array<() => void>>([]);
  const [assistantItems, setAssistantItems] = useState<WorkspaceViewModel["assistant"]["items"]>(() =>
    Array.from({ length: 84 }, (_, index) => index % 2 === 0
      ? { kind: "tool" as const, order: index, run: makeTool(index / 2) }
      : { kind: "message" as const, order: index, message: makeMessage(index, `助手模拟记录 ${index}`) }),
  );

  useLayoutEffect(() => {
    streamCommitWaiters.current.splice(0).forEach((resolve) => resolve());
  }, [messages]);

  useEffect(() => {
    (window as typeof window & { conversationHarness?: object }).conversationHarness = {
      setCharacterCount: (count: number) => setMessages(Array.from({ length: count }, (_, index) => makeMessage(index))),
      growLatest: (suffix: string) => setMessages((current) => current.map((message, index) =>
        index === current.length - 1 ? { ...message, text: message.text + suffix } : message)),
      streamLatest: async (count: number) => {
        for (let index = 0; index < count; index += 1) {
          await new Promise<void>((resolve) => {
            streamCommitWaiters.current.push(resolve);
            setMessages((current) => current.map((message, row) =>
              row === current.length - 1 ? { ...message, text: `${message.text} token-${index} ` } : message));
          });
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
        }
      },
      setAssistantCount: (count: number) => setAssistantItems(Array.from({ length: count }, (_, index) => index % 2 === 0
        ? { kind: "tool" as const, order: index, run: makeTool(index / 2) }
        : { kind: "message" as const, order: index, message: makeMessage(index, `助手模拟记录 ${index}`) })),
    };
  }, []);

  const timeline = {
    conversationId: "desktop-simulation",
    messages,
    isStreaming: messages.at(-1)?.streaming === true,
    queueItems: [],
  };
  const assistantMessages = assistantItems.filter((item) => item.kind === "message").map((item) => item.message);
  const toolRuns = assistantItems.filter((item) => item.kind === "tool").map((item) => item.run);
  const workspace = {
    mode: "collaboration",
    character: timeline,
    assistant: {
      conversationId: "desktop-simulation",
      messages: assistantMessages,
      toolRuns,
      items: assistantItems,
      busy: true,
      activeTask: null,
    },
    delegation: null,
  } as WorkspaceViewModel;

  return (
    <main className="simulation-page">
      <header className="simulation-toolbar">桌面消息流模拟 · 仅使用本地生成数据</header>
      <div className="workspace">
        <Workspace workspace={workspace} pair={pair} />
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><Harness /></StrictMode>);
