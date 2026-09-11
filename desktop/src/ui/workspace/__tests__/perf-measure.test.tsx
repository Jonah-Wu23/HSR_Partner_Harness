import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Message, PairRecord } from "../../../contracts/protocol";
import type { ConversationTimelineViewModel } from "../../../contracts/view-models";
import { MessageList } from "../MessageList";

const pair: PairRecord = {
  pair_id: "pair-1",
  character: { id: "char", name: "白厄", voice_id: "v-char" },
  assistant: { id: "mech", name: "机械", voice_id: "v-mech" },
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

function makeMessage(index: number, text: string): Message {
  return {
    message_id: `m-${index}`,
    conversation_id: "conv-1",
    pair_id: "pair-1",
    engine_turn_id: null,
    source: index % 2 === 0 ? "user" : "character",
    kind: index % 2 === 0 ? "user.text" : "character.speech",
    text,
    payload: {},
    tts_eligible: false,
    created_at: "2026-08-11T00:00:00Z",
  };
}

function timeline(messages: Message[]): ConversationTimelineViewModel {
  return {
    conversationId: "conv-1",
    messages,
    isStreaming: messages.some((message) => message.streaming === true),
    queueItems: [],
  };
}

/** virtualizer.measure() 会 clear() 测量缓存 Map；用它计数全量重测次数。 */
function countCacheClears() {
  const counter = { clears: 0 };
  const original = Map.prototype.clear;
  Map.prototype.clear = function (this: Map<unknown, unknown>) {
    counter.clears += 1;
    console.log(`[clear] size=${this.size}`);
    return original.call(this);
  };
  return {
    counter,
    restore: () => {
      Map.prototype.clear = original;
    },
  };
}

describe("MessageList measure() 调用次数（jsdom 离线计数）", () => {
  afterEach(cleanup);

  it("流式 delta 重渲染不应清空测量缓存", () => {
    const messages = Array.from({ length: 500 }, (_, index) =>
      makeMessage(index, `消息 ${index}`),
    );
    const probe = countCacheClears();
    let initial = 0;
    let afterStreaming = 0;
    let afterAppend = 0;
    try {
      const { rerender } = render(
        <MessageList timeline={timeline(messages)} pair={pair} emptyText="空" />,
      );
      initial = probe.counter.clears;
      for (let i = 0; i < 10; i += 1) {
        const next = messages.map((message, index) =>
          index === messages.length - 1
            ? { ...message, streaming: true, text: `${message.text}…` }
            : message,
        );
        rerender(<MessageList timeline={timeline(next)} pair={pair} emptyText="空" />);
      }
      afterStreaming = probe.counter.clears;
      const appended = [...messages, makeMessage(500, "新消息")];
      rerender(<MessageList timeline={timeline(appended)} pair={pair} emptyText="空" />);
      afterAppend = probe.counter.clears;
    } finally {
      probe.restore();
    }
    console.log(
      `[measure] initial=${initial} streamingDeltaClears=${afterStreaming - initial} appendClears=${afterAppend - afterStreaming}`,
    );
    expect(afterStreaming - initial).toBe(0);
    expect(afterAppend - afterStreaming).toBeGreaterThan(0);
  });

  it("切换会话时应当触发 measure() 重测清空缓存", () => {
    const messages = Array.from({ length: 500 }, (_, index) =>
      makeMessage(index, `消息 ${index}`),
    );
    const probe = countCacheClears();
    try {
      const { rerender } = render(
        <MessageList timeline={timeline(messages)} pair={pair} emptyText="空" />,
      );
      const initial = probe.counter.clears;
      rerender(
        <MessageList
          timeline={{ ...timeline(messages), conversationId: "conv-2" }}
          pair={pair}
          emptyText="空"
        />,
      );
      const afterSwitch = probe.counter.clears;
      expect(afterSwitch - initial).toBeGreaterThan(0);
    } finally {
      probe.restore();
    }
  });
});
