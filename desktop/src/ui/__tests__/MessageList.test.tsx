import { cleanup, fireEvent, render } from "@testing-library/react";
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
    ...overrides,
  };
}

function makeTimeline(messages: Message[]): ConversationTimelineViewModel {
  return {
    conversationId: "conv-1",
    messages,
    isStreaming: messages.some((message) => message.streaming === true),
  };
}

describe("MessageList 流式与身份展示", () => {
  afterEach(cleanup);

  it("流式消息渲染打字光标，定稿后光标消失", () => {
    const streaming = makeMessage({ streaming: true, text: "我已经看见了" });
    const { container, rerender } = render(
      <MessageList timeline={makeTimeline([streaming])} pair={pair} emptyText="空" />,
    );
    expect(container.querySelector(".msg-streaming-caret")).not.toBeNull();

    rerender(
      <MessageList
        timeline={makeTimeline([{ ...streaming, streaming: false }])}
        pair={pair}
        emptyText="空"
      />,
    );
    expect(container.querySelector(".msg-streaming-caret")).toBeNull();
  });

  it("角色、助手、用户气泡分别带身份标签与分色类名", () => {
    const messages = [
      makeMessage({ message_id: "m-char", source: "character", text: "角色说" }),
      makeMessage({
        message_id: "m-mech",
        source: "assistant",
        kind: "assistant.natural_language",
        text: "助手说",
      }),
      makeMessage({ message_id: "m-user", source: "user", kind: "user.text", text: "用户说" }),
    ];
    const { container } = render(
      <MessageList timeline={makeTimeline(messages)} pair={pair} emptyText="空" />,
    );
    expect(container.querySelector(".msg-character")).not.toBeNull();
    expect(container.querySelector(".msg-assistant")).not.toBeNull();
    expect(container.querySelector(".msg-user")).not.toBeNull();
    expect(container.querySelector('[data-message-source="character"] .msg-source')?.textContent).toBe("白厄");
    expect(container.querySelector('[data-message-source="assistant"] .msg-source')?.textContent).toBe("神秘的古代机械");
    expect(container.querySelector('[data-message-source="user"] .msg-source')?.textContent).toBe("你");
  });

  it("思考缎带默认折叠为摘要，点击后展开", () => {
    const message = makeMessage({
      payload: { reasoning: "先分析项目结构，再决定修改范围。" },
    });
    const { container, getByRole } = render(
      <MessageList timeline={makeTimeline([message])} pair={pair} emptyText="空" />,
    );
    expect(container.querySelector(".reasoning-ribbon-body")).toBeNull();
    fireEvent.click(getByRole("button", { name: /思考完成 · 展开/ }));
    expect(container.querySelector(".reasoning-ribbon-body")?.textContent).toContain("先分析项目结构");
  });

  it("空时间线展示占位文案", () => {
    const { getByText } = render(
      <MessageList timeline={makeTimeline([])} pair={pair} emptyText="和角色聊聊…" />,
    );
    expect(getByText("和角色聊聊…")).toBeInTheDocument();
  });

  it("超过 50 条消息时只挂载虚拟列表视口", () => {
    const messages = Array.from({ length: 500 }, (_, index) =>
      makeMessage({ message_id: `m-${index}`, text: `消息 ${index}` }),
    );
    const { container } = render(
      <MessageList timeline={makeTimeline(messages)} pair={pair} emptyText="空" />,
    );
    expect(container.querySelector(".message-column-virtual")).not.toBeNull();
    expect(container.querySelectorAll("[data-message-source]").length).toBeLessThan(500);
  });
});
