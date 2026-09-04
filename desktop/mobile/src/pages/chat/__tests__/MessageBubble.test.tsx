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
  };

  it("渲染用户消息与来源标记「你」", () => {
    render(<MessageBubble message={baseMessage} />);
    const bubble = screen.getByTestId("message-bubble");
    expect(bubble).toHaveAttribute("data-message-source", "user");
    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent("你");
    expect(screen.getByText("你好，请帮我分析一下项目代码")).toBeInTheDocument();
  });

  it("渲染角色消息与来源标记", () => {
    const charMsg: Message = {
      ...baseMessage,
      message_id: "msg-2",
      source: "character",
      kind: "character.speech",
      text: "嗯？今天有什么任务交给我？",
    };
    render(<MessageBubble message={charMsg} pairNames={{ character: "白厄" }} />);
    const bubble = screen.getByTestId("message-bubble");
    expect(bubble).toHaveAttribute("data-message-source", "character");
    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent("白厄");
    expect(screen.getByText("嗯？今天有什么任务交给我？")).toBeInTheDocument();
  });

  it("渲染助手消息与思考段", () => {
    const assistantMsg: Message = {
      ...baseMessage,
      message_id: "msg-3",
      source: "assistant",
      kind: "assistant.natural_language",
      text: "已完成架构分析，建议分三步进行重构。",
      payload: {
        reasoning: "正在阅读目录树，识别出核心模块与边界...",
        reasoning_seconds: 3,
      },
    };
    render(<MessageBubble message={assistantMsg} pairNames={{ assistant: "古代机械" }} />);
    const bubble = screen.getByTestId("message-bubble");
    expect(bubble).toHaveAttribute("data-message-source", "assistant");
    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent("古代机械");
    expect(screen.getByText("已完成架构分析，建议分三步进行重构。")).toBeInTheDocument();
    // 思考折叠缎带渲染
    expect(screen.getByTestId("reasoning-ribbon")).toBeInTheDocument();
    expect(screen.getByText("思考了 3 秒")).toBeInTheDocument();
  });

  it("渲染工具消息为 ToolCard", () => {
    const toolMsg: Message = {
      ...baseMessage,
      message_id: "msg-4",
      source: "tool",
      kind: "tool.record",
      text: "cargo test",
      payload: {
        tool_call_id: "tc-2",
        status: "succeeded",
        title: "cargo test",
        details: "test result: ok. 12 passed",
      },
    };
    render(<MessageBubble message={toolMsg} />);
    expect(screen.getByTestId("tool-card")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });

  it("渲染系统通知消息", () => {
    const sysMsg: Message = {
      ...baseMessage,
      message_id: "msg-5",
      source: "system",
      kind: "system.status",
      text: "会话已就绪，当前模式：协作模式",
    };
    render(<MessageBubble message={sysMsg} />);
    const bubble = screen.getByTestId("message-bubble");
    expect(bubble).toHaveAttribute("data-message-source", "system");
    expect(screen.getByTestId("msg-source-badge")).toHaveTextContent("系统");
    expect(screen.getByText("会话已就绪，当前模式：协作模式")).toBeInTheDocument();
  });

  it("角色消息 tts_ready=true 时展示朗读入口", () => {
    const charMsg: Message = {
      ...baseMessage,
      message_id: "msg-tts-1",
      source: "character",
      kind: "character.speech",
      text: "这条可以朗读。",
      tts_eligible: true,
      tts_ready: true,
    };
    render(<MessageBubble message={charMsg} />);
    expect(screen.getByTestId("msg-tts-badge")).toBeInTheDocument();
  });

  it("角色消息 tts_ready=false（账号音色未生成）时不展示朗读入口", () => {
    const charMsg: Message = {
      ...baseMessage,
      message_id: "msg-tts-2",
      source: "character",
      kind: "character.speech",
      text: "这条点了也不会有声音。",
      tts_eligible: true,
      tts_ready: false,
    };
    render(<MessageBubble message={charMsg} />);
    expect(screen.queryByTestId("msg-tts-badge")).toBeNull();
    expect(screen.getByText("这条点了也不会有声音。")).toBeInTheDocument();
  });

  it("旧消息/快照无 tts_ready 字段时按不可朗读保守处理，不展示假入口", () => {
    const legacyMsg: Message = {
      ...baseMessage,
      message_id: "msg-tts-3",
      source: "character",
      kind: "character.speech",
      text: "历史消息。",
      tts_eligible: true,
    };
    render(<MessageBubble message={legacyMsg} />);
    expect(screen.queryByTestId("msg-tts-badge")).toBeNull();
  });
});
