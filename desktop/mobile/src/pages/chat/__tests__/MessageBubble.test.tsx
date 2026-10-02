import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Message } from "@shared/contracts/protocol";
import { MessageBubble } from "../MessageBubble";

describe("MessageBubble", () => {
  afterEach(() => {
    cleanup();
  });

  const baseMessage: Message = {
    message_id: "msg-1",
    conversation_id: "c1",
    pair_id: "p1",
    engine_turn_id: null,
    source: "user",
    kind: "user.text",
    text: "你好，请帮我分析一下项目代码",
    payload: {},
    tts_eligible: false,
    created_at: "2026-08-20T10:00:00Z",
    timeline_order: 1,
  };

  it.each([
    { source: "user", kind: "user.text", badge: "你" },
    { source: "character", kind: "character.speech", badge: "白厄" },
    { source: "assistant", kind: "assistant.natural_language", badge: "第四面镜" },
    { source: "system", kind: "system.status", badge: "系统" },
  ] as const)("$source 消息显示来源标记「$badge」与正文", ({ source, kind, badge }) => {
    render(
      <MessageBubble
        message={{ ...baseMessage, source, kind }}
        characterName="白厄"
        assistantName="第四面镜"
      />,
    );
    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent(badge);
    expect(screen.getByText("你好，请帮我分析一下项目代码")).toBeInTheDocument();
  });

  it("带思考内容的消息显示折叠的思考段与耗时", () => {
    const assistantMsg: Message = {
      ...baseMessage,
      source: "assistant",
      kind: "assistant.natural_language",
      text: "已完成架构分析，建议分三步进行重构。",
      payload: {
        reasoning: "正在阅读目录树，识别出核心模块与边界...",
        reasoning_seconds: 3,
      },
    };
    render(<MessageBubble message={assistantMsg} />);
    expect(screen.getByTestId("reasoning-ribbon")).toHaveTextContent("思考了 3 秒");
    expect(screen.getByText("已完成架构分析，建议分三步进行重构。")).toBeInTheDocument();
  });

  // 历史消息（装载结果与快照）不带 tts_ready，同样不可朗读。
  it.each([
    { ttsReady: true, readable: true },
    { ttsReady: false, readable: false },
    { ttsReady: undefined, readable: false },
  ])("角色消息 tts_ready=$ttsReady 时朗读入口可见：$readable", ({ ttsReady, readable }) => {
    const characterMsg: Message = {
      ...baseMessage,
      source: "character",
      kind: "character.speech",
      text: "今天想聊些什么？",
      tts_eligible: true,
      ...(ttsReady === undefined ? {} : { tts_ready: ttsReady }),
    };
    render(<MessageBubble message={characterMsg} />);
    expect(screen.queryByTestId("msg-tts-badge") !== null).toBe(readable);
  });
});
