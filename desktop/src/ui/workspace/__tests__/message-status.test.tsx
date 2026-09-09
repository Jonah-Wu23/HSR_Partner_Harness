import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Message, PairRecord } from "../../../contracts/protocol";
import type { ConversationTimelineViewModel } from "../../../contracts/view-models";
import { MessageList } from "../MessageList";

const pair: PairRecord = {
  pair_id: "pair-1",
  character: { id: "phainon", name: "白厄", voice_id: "v-phainon" },
  assistant: { id: "ancient_machine", name: "古代机械", voice_id: "v-mech" },
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

function message(
  id: string,
  source: Message["source"],
  text: string,
  overrides: Partial<Message> = {},
): Message {
  return {
    message_id: id,
    conversation_id: "conv-1",
    pair_id: "pair-1",
    engine_turn_id: null,
    source,
    kind: source === "user" ? "user.text" : "character.speech",
    text,
    payload: {},
    tts_eligible: false,
    created_at: "2026-09-09T00:00:00Z",
    ...overrides,
  };
}

function timeline(messages: Message[]): ConversationTimelineViewModel {
  return {
    conversationId: "conv-1",
    messages,
    isStreaming: false,
    queueItems: [],
  };
}

describe("V0.3.9 V01 Message.status 真实终态渲染", () => {
  afterEach(cleanup);

  it("failed 状态渲染错误原文且带 is-failed / alert 标记，不与正常完成同貌", () => {
    const errorText = "dialogue provider 返回 500：internal server error";
    const failedMsg = message("m-failed-1", "user", "跑测试", {
      status: "failed",
      payload: { error: errorText },
    });
    const { container } = render(<MessageList timeline={timeline([failedMsg])} pair={pair} emptyText="空" />);

    expect(screen.getByTestId("msg-status-failed")).toBeInTheDocument();
    expect(screen.getByText(errorText)).toBeInTheDocument();
    expect(container.querySelector(".msg-bubble.is-failed")).not.toBeNull();
    expect(container.querySelector(".msg-row.is-failed")).not.toBeNull();
  });

  it("failed 但无具体错误详情时显示兜底失败提示，暴露失败状态", () => {
    const failedMsg = message("m-failed-2", "character", "（失败消息）", {
      status: "failed",
      payload: {},
    });
    render(<MessageList timeline={timeline([failedMsg])} pair={pair} emptyText="空" />);

    expect(screen.getByTestId("msg-status-failed")).toBeInTheDocument();
    expect(screen.getByText("执行失败（未返回具体错误）")).toBeInTheDocument();
  });

  it("cancelled 状态渲染已取消标签与取消原因", () => {
    const reasonText = "用户取消了任务";
    const cancelledMsg = message("m-cancel-1", "character", "（取消消息）", {
      status: "cancelled",
      payload: { cancelled_reason: reasonText },
    });
    const { container } = render(<MessageList timeline={timeline([cancelledMsg])} pair={pair} emptyText="空" />);

    expect(screen.getByTestId("msg-status-cancelled")).toBeInTheDocument();
    expect(screen.getByText(reasonText)).toBeInTheDocument();
    expect(container.querySelector(".msg-bubble.is-cancelled")).not.toBeNull();
  });

  it("queued 状态渲染排队中标记与虚线边框修饰类", () => {
    const queuedMsg = message("m-queued-1", "user", "排队消息", {
      status: "queued",
    });
    const { container } = render(<MessageList timeline={timeline([queuedMsg])} pair={pair} emptyText="空" />);

    expect(screen.getByText("排队中")).toBeInTheDocument();
    expect(container.querySelector(".msg-bubble.is-queued")).not.toBeNull();
  });
});
