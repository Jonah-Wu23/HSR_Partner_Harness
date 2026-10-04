import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ConversationRecord, Message, PairRecord } from "@shared/contracts/protocol";
import { useMobileStore } from "../../../lib/mobileStore";
import { ChatTimeline } from "../ChatTimeline";

const PAIR: PairRecord = {
  pair_id: "pair-1",
  character: { id: "phainon", name: "白厄", voice_id: "" },
  assistant: { id: "fourth_mirror", name: "第四面镜", voice_id: "" },
  theme: {
    character_text: "#fff",
    character_primary: "#ffd",
    character_deep: "#aa8",
    character_active: "#ff0",
    assistant_primary: "#aaf",
    assistant_bright: "#ccf",
    assistant_shadow: "#558",
  },
};

function cardConversation(conversationId: string, cardId: string, name: string): ConversationRecord {
  return {
    conversation_id: conversationId,
    project_id: "p1",
    pair_id: PAIR.pair_id,
    title: `${name}的聊天`,
    last_mode: "chat",
    archived: false,
    created_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
    character_card_id: cardId,
    binding_id: `card-bind-${cardId}`,
    character_identity: {
      name,
      avatar_ref: `card-avatar:${cardId}`,
      avatar_version: "v1",
      missing: false,
      source: "card",
    },
  };
}

function characterMessage(conversationId: string, text: string, timelineOrder = 1): Message {
  return {
    message_id: `char-${conversationId}`,
    conversation_id: conversationId,
    pair_id: PAIR.pair_id,
    engine_turn_id: null,
    source: "character",
    kind: "character.speech",
    text,
    payload: {},
    tts_eligible: false,
    created_at: "2026-08-20T00:01:00Z",
    timeline_order: timelineOrder,
  };
}

function delegationMessage(conversationId: string, text: string): Message {
  return {
    message_id: `del-${conversationId}`,
    conversation_id: conversationId,
    pair_id: PAIR.pair_id,
    engine_turn_id: null,
    source: "user",
    kind: "user.text",
    text,
    payload: {},
    tts_eligible: false,
    created_at: "2026-08-20T00:02:00Z",
    timeline_order: 1,
    origin: "character_delegation",
    delegation_id: `task-${conversationId}`,
    status: "processing",
  };
}

describe("ChatTimeline 角色身份展示", () => {
  beforeEach(() => {
    useMobileStore.setState({
      activeConversationId: null,
      conversationsById: {},
      messages: [],
      toolRuns: [],
      queueItems: [],
      pair: null,
      activeTask: null,
      timelineLoading: false,
    });
  });

  afterEach(cleanup);

  it("角色消息署名取正在查看会话的 character_identity，不显示基础搭档的内置角色名", () => {
    useMobileStore.setState({
      activeConversationId: "c1",
      conversationsById: { c1: cardConversation("c1", "card-a", "卡芙卡") },
      pair: PAIR,
      messages: [characterMessage("c1", "本姑娘出马当然拍到啦")],
    });
    render(<ChatTimeline conversationId="c1" />);

    const badge = screen.getByTestId("msg-source-badge");
    expect(badge).toHaveTextContent("卡芙卡");
    expect(screen.queryByText("白厄")).toBeNull();
  });

  it("委派卡来源用正在查看会话的角色名", () => {
    useMobileStore.setState({
      activeConversationId: "c1",
      conversationsById: { c1: cardConversation("c1", "card-a", "卡芙卡") },
      pair: PAIR,
      messages: [delegationMessage("c1", "查看项目目录结构")],
    });
    render(<ChatTimeline conversationId="c1" />);

    const card = screen.getByTestId("delegation-card");
    expect(within(card).getByText("来自 卡芙卡 的委派")).toBeInTheDocument();
    expect(card).not.toHaveTextContent("白厄");
  });

  it("旧会话没有 character_identity 时维持搭档角色名回退", () => {
    const legacy = cardConversation("c1", "", "白厄");
    delete legacy.character_identity;
    useMobileStore.setState({
      activeConversationId: "c1",
      conversationsById: { c1: legacy },
      pair: PAIR,
      messages: [characterMessage("c1", "旧会话的消息")],
    });
    render(<ChatTimeline conversationId="c1" />);

    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent("白厄");
  });

  it("切换会话时各自显示各自的名字，互不串扰", () => {
    useMobileStore.setState({
      activeConversationId: "c1",
      conversationsById: {
        c1: cardConversation("c1", "card-a", "卡芙卡"),
        c2: cardConversation("c2", "card-b", "银狼"),
      },
      pair: PAIR,
      messages: [characterMessage("c1", "卡芙卡的消息")],
    });
    const { rerender } = render(<ChatTimeline conversationId="c1" />);
    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent("卡芙卡");

    useMobileStore.setState({
      activeConversationId: "c2",
      messages: [characterMessage("c2", "银狼的消息")],
    });
    rerender(<ChatTimeline conversationId="c2" />);

    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent("银狼");
    expect(screen.queryByText("卡芙卡")).toBeNull();
  });
});
