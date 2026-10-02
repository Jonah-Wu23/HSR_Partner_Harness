import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Message, PairRecord } from "../../contracts/protocol";
import type { ConversationTimelineViewModel } from "../../contracts/view-models";
import { MessageList } from "../workspace/MessageList";

const pair: PairRecord = {
  pair_id: "pair-1",
  character: { id: "char", name: "白厄", voice_id: "v-char" },
  assistant: { id: "mech", name: "神秘的古代机械", voice_id: "v-mech" },
  theme: {
    character_text: "#C7D4E3",
    character_primary: "#8AA4D4",
    character_deep: "#3A548C",
    character_active: "#296CE1",
    assistant_primary: "#B08D57",
    assistant_bright: "#C5A059",
    assistant_shadow: "#8C6B3F",
  },
};

function makeMessage(overrides: Partial<Message>): Message {
  return {
    message_id: "m-1",
    conversation_id: "conv-1",
    pair_id: "pair-1",
    engine_turn_id: null,
    source: "character",
    kind: "character.speech",
    text: "示例文本",
    payload: {},
    tts_eligible: true,
    created_at: "2026-08-11T00:00:00Z",
    timeline_order: 1,
    ...overrides,
  };
}

function makeTimeline(
  messages: Message[],
  queueItems: ConversationTimelineViewModel["queueItems"] = [],
): ConversationTimelineViewModel {
  return {
    conversationId: "conv-1",
    messages,
    isStreaming: messages.some((message) => message.streaming === true),
    queueItems,
  };
}

/** 按来源取消息行：行上的 data-message-source 与 data-message-status 是消息身份与状态的标记。 */
function messageRow(container: HTMLElement, source: Message["source"]): HTMLElement {
  const row = container.querySelector<HTMLElement>(`[data-message-source="${source}"]`);
  if (!row) throw new Error(`没有渲染 ${source} 消息`);
  return row;
}

describe("MessageList", () => {
  afterEach(cleanup);

  it("流式消息标记为 streaming，定稿后标记为 done", () => {
    const streaming = makeMessage({ streaming: true, text: "我已经看见了" });
    const { container, rerender } = render(
      <MessageList timeline={makeTimeline([streaming])} pair={pair} emptyText="空" />,
    );
    expect(messageRow(container, "character")).toHaveAttribute("data-message-status", "streaming");

    rerender(
      <MessageList
        timeline={makeTimeline([{ ...streaming, streaming: false }])}
        pair={pair}
        emptyText="空"
      />,
    );
    expect(messageRow(container, "character")).toHaveAttribute("data-message-status", "done");
  });

  it("角色、助手、用户气泡分别标注说话方名字", () => {
    const messages = [
      makeMessage({ message_id: "m-char", source: "character", text: "角色说", timeline_order: 1 }),
      makeMessage({
        message_id: "m-mech",
        source: "assistant",
        kind: "assistant.natural_language",
        text: "助手说",
        timeline_order: 2,
      }),
      makeMessage({ message_id: "m-user", source: "user", kind: "user.text", text: "用户说", timeline_order: 3 }),
    ];
    const { container } = render(
      <MessageList timeline={makeTimeline(messages)} pair={pair} emptyText="空" />,
    );
    expect(within(messageRow(container, "character")).getByText("白厄")).toBeInTheDocument();
    expect(within(messageRow(container, "assistant")).getByText("神秘的古代机械")).toBeInTheDocument();
    expect(within(messageRow(container, "user")).getByText("你")).toBeInTheDocument();
  });

  it.each([
    ["failed", { error: "dialogue provider 返回 500：internal server error" }, "dialogue provider 返回 500：internal server error"],
    ["failed", {}, "执行失败（未返回具体错误）"],
    ["cancelled", { cancelled_reason: "用户取消了任务" }, "用户取消了任务"],
    ["queued", {}, "排队中"],
  ] as const)("%s 消息在气泡内显示状态说明「%s」", (status, payload, text) => {
    const message = makeMessage({ source: "user", kind: "user.text", text: "跑测试", status, payload });
    const { container } = render(
      <MessageList timeline={makeTimeline([message])} pair={pair} emptyText="空" />,
    );
    const row = messageRow(container, "user");
    expect(row).toHaveAttribute("data-message-status", status);
    expect(within(row).getByText(text)).toBeInTheDocument();
  });

  it("失败消息的错误以 alert 呈现", () => {
    const message = makeMessage({ status: "failed", payload: { error: "模型请求超时" } });
    render(<MessageList timeline={makeTimeline([message])} pair={pair} emptyText="空" />);
    expect(screen.getByRole("alert")).toHaveTextContent("模型请求超时");
  });

  it("思考缎带的展开状态由消息流保存：默认折叠为摘要，点击后展开", () => {
    const message = makeMessage({
      payload: { reasoning: "先分析项目结构，再决定修改范围。" },
    });
    render(<MessageList timeline={makeTimeline([message])} pair={pair} emptyText="空" />);
    expect(screen.queryByText(/先分析项目结构/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "思考完成 · 展开" }));
    expect(screen.getByText(/先分析项目结构/)).toBeInTheDocument();
  });

  it.each([
    ["character", "character.speech", "先看看当前对话。"],
    ["assistant", "assistant.reasoning", "先检查项目结构。"],
  ] as const)("%s 的思考与正文共用一个气泡，正文未到达时显示三个点", (source, kind, reasoning) => {
    const message = makeMessage({
      source,
      kind,
      text: "",
      streaming: true,
      payload: { reasoning, reasoning_streaming: true },
    });
    const { container } = render(
      <MessageList timeline={makeTimeline([message])} pair={pair} emptyText="空" />,
    );
    expect(container.querySelectorAll(`[data-message-source="${source}"]`)).toHaveLength(1);
    const row = messageRow(container, source);
    expect(within(row).getByText("...")).toBeInTheDocument();
    expect(within(row).getByText(reasoning)).toBeInTheDocument();
  });

  it("空时间线展示占位文案", () => {
    render(<MessageList timeline={makeTimeline([])} pair={pair} emptyText="和角色聊聊…" />);
    expect(screen.getByText("和角色聊聊…")).toBeInTheDocument();
  });

  it("超过 50 条消息时只挂载虚拟窗口内的行", () => {
    const messages = Array.from({ length: 500 }, (_, index) =>
      makeMessage({ message_id: `m-${index}`, text: `消息 ${index}`, timeline_order: index }),
    );
    const { container } = render(
      <MessageList timeline={makeTimeline(messages)} pair={pair} emptyText="空" />,
    );
    const mounted = container.querySelectorAll("[data-message-source]").length;
    expect(mounted).toBeGreaterThan(0);
    expect(mounted).toBeLessThan(500);
  });

  it("排队项在消息流尾部全文呈现并标注排队中", () => {
    render(
      <MessageList
        timeline={makeTimeline([], [
          {
            queue_item_id: "q-1",
            account_id: "",
            conversation_id: "conv-1",
            target: "assistant",
            text: "排队中的委派任务全文",
            intent: "followup",
            position: 0,
            status: "queued",
            error: null,
            created_at: "2026-08-11T00:00:00+00:00",
            source_message_id: null,
            origin: "desktop",
            remote_device_key: null,
            remote_device_name: null,
          },
        ])}
        pair={pair}
        emptyText="空"
      />,
    );
    const row = screen.getByText("排队中的委派任务全文").closest<HTMLElement>("[data-queue-status]");
    expect(row).toHaveAttribute("data-queue-status", "queued");
    expect(within(row!).getByText("排队中")).toBeInTheDocument();
  });
});
