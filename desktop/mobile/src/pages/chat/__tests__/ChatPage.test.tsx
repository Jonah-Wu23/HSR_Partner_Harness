import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type {
  ConversationRecord,
  Message,
  PendingApproval,
  ToolRun,
} from "@shared/contracts/protocol";
import { mobileWsClient, useMobileStore } from "../../../lib/mobileStore";
import { ChatPage } from "../ChatPage";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;

  readyState = FakeWebSocket.CONNECTING;
  readonly url: string;
  readonly sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  close(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  send(data: string): void {
    this.sent.push(data);
  }

  emit(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
}

const CONVERSATION: ConversationRecord = {
  conversation_id: "c1",
  project_id: "p1",
  pair_id: "pair-1",
  title: "开发架构重构",
  last_mode: "collaboration",
  archived: false,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

const SAMPLE_MESSAGE: Message = {
  message_id: "msg-1",
  conversation_id: "c1",
  pair_id: "pair-1",
  engine_turn_id: null,
  source: "character",
  kind: "character.speech",
  text: "我已经准备好接下来的开发任务了。",
  payload: {},
  tts_eligible: true,
  created_at: "2026-08-20T00:01:00Z",
};

const SAMPLE_TOOL_RUN: ToolRun = {
  tool_call_id: "tr-1",
  conversation_id: "c1",
  task_id: "task-1",
  engine_turn_id: "turn-1",
  sequence: 1,
  status: "succeeded",
  title: "cargo build",
  summary: "编译桌面端",
  details: "Finished release [optimized] target(s) in 4.2s",
};

const SAMPLE_APPROVAL: PendingApproval = {
  approval_id: "app-1",
  conversation_id: "c1",
  operation: {
    tool_kind: "file_write",
    command: null,
    paths: ["src/config.json"],
    patch_file_count: 1,
    summary: "更新项目配置文件",
  },
  reason: "需要确认写入配置",
  task_id: "task-1",
};

function lastInstance(): FakeWebSocket {
  const instance = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
  if (!instance) throw new Error("没有 FakeWebSocket 实例");
  return instance;
}

function lastSentFrame(): Record<string, unknown> {
  const ws = lastInstance();
  const raw = ws.sent[ws.sent.length - 1];
  if (!raw) throw new Error("客户端尚未发出任何帧");
  return JSON.parse(raw) as Record<string, unknown>;
}

describe("ChatPage 移动端聊天页集成测试", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    mobileWsClient.disconnect();
    FakeWebSocket.instances = [];
    window.localStorage.clear();

    useMobileStore.setState({
      connection: "connected",
      deviceName: "测试设备",
      projects: [],
      conversationsById: { c1: CONVERSATION },
      activeConversationId: null,
      messages: [],
      toolRuns: [],
      approvals: [],
      lastSequence: 10,
      bootstrapped: true,
    });

    useMobileStore.getState().start();
    mobileWsClient.connect();
    lastInstance().open();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("挂载时调用 conversation.open 装载消息并渲染", async () => {
    render(<ChatPage conversationId="c1" />);

    // 检查 openConversation 帧发出
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("conversation.open");
    });
    const openFrame = lastSentFrame();
    expect(openFrame.params).toMatchObject({ conversation_id: "c1" });

    // 模拟服务端响应消息与工具调用
    lastInstance().emit({
      kind: "response",
      id: openFrame.id,
      ok: true,
      result: {
        conversation: CONVERSATION,
        project: null,
        pair: null,
        messages: [SAMPLE_MESSAGE],
        tool_runs: [SAMPLE_TOOL_RUN],
        turns: [],
        queue_items: [],
        active_task: null,
      },
    });

    await waitFor(() => {
      expect(screen.getByText("开发架构重构")).toBeInTheDocument();
      expect(screen.getByText("协作模式")).toBeInTheDocument();
      expect(screen.getByText("我已经准备好接下来的开发任务了。")).toBeInTheDocument();
      expect(screen.getByText("工具调用")).toBeInTheDocument();
      expect(screen.getByText("已完成")).toBeInTheDocument();
    });
  });

  it("展示只读等待审批卡片，断言无批准/拒绝按钮并包含「请在电脑端处理」", async () => {
    useMobileStore.setState({
      approvals: [SAMPLE_APPROVAL],
    });

    render(<ChatPage conversationId="c1" />);

    // 验证审批卡片渲染
    expect(screen.getByTestId("approval-card")).toBeInTheDocument();
    expect(screen.getByText("请在电脑端处理")).toBeInTheDocument();
    expect(screen.getByText("更新项目配置文件")).toBeInTheDocument();
    expect(screen.getByText("src/config.json")).toBeInTheDocument();

    // 严格断言：UI 中无批准/拒绝按钮
    expect(screen.queryByRole("button", { name: /允许|批准|通过/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /否决|拒绝/i })).toBeNull();
  });

  it("「交给助手」委派提交，验证 chat.submit 协议帧", async () => {
    render(<ChatPage conversationId="c1" />);

    // 先响应 openConversation
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("conversation.open");
    });
    const openFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: openFrame.id,
      ok: true,
      result: {
        conversation: CONVERSATION,
        project: null,
        pair: null,
        messages: [],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
      },
    });

    const input = screen.getByTestId("delegation-input");
    const submitBtn = screen.getByTestId("delegation-submit-btn");

    await waitFor(() => {
      expect(useMobileStore.getState().activeConversationId).toBe("c1");
    });

    fireEvent.change(input, { target: { value: "把所有单元测试运行一遍" } });
    fireEvent.click(submitBtn);

    // 断言 chat.submit 帧
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("chat.submit");
    });
    const submitFrame = lastSentFrame();
    expect(submitFrame.params).toMatchObject({
      conversation_id: "c1",
      target: "assistant",
      mode: "collaboration",
      text: "把所有单元测试运行一遍",
    });

    // 响应成功
    lastInstance().emit({
      kind: "response",
      id: submitFrame.id,
      ok: true,
      result: {},
    });

    await waitFor(() => {
      expect(input).toHaveValue("");
    });
  });

  it("委派提交失败时如实展示错误", async () => {
    render(<ChatPage conversationId="c1" />);

    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("conversation.open");
    });
    const openFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: openFrame.id,
      ok: true,
      result: {
        conversation: CONVERSATION,
        project: null,
        pair: null,
        messages: [],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
      },
    });

    const input = screen.getByTestId("delegation-input");
    const submitBtn = screen.getByTestId("delegation-submit-btn");

    await waitFor(() => {
      expect(useMobileStore.getState().activeConversationId).toBe("c1");
    });

    fireEvent.change(input, { target: { value: "启动构建" } });
    fireEvent.click(submitBtn);

    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("chat.submit");
    });
    const submitFrame = lastSentFrame();

    // 模拟服务端返回错误
    lastInstance().emit({
      kind: "response",
      id: submitFrame.id,
      ok: false,
      error: { code: "service_busy", message: "桌面端正在执行其他任务" },
    });

    await waitFor(() => {
      expect(screen.getByTestId("delegation-error")).toBeInTheDocument();
      expect(screen.getByText(/桌面端正在执行其他任务/)).toBeInTheDocument();
    });
  });

  it("接收实时 message.delta 与 message.finalized 事件并增量渲染", async () => {
    render(<ChatPage conversationId="c1" />);

    // 初始打开返回空消息
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("conversation.open");
    });
    const openFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: openFrame.id,
      ok: true,
      result: {
        conversation: CONVERSATION,
        project: null,
        pair: null,
        messages: [],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
      },
    });

    await waitFor(() => {
      expect(useMobileStore.getState().activeConversationId).toBe("c1");
    });

    // 推送 delta 事件
    lastInstance().emit({
      kind: "event",
      event: "message.delta",
      sequence: 11,
      payload: {
        message_id: "m-stream-1",
        conversation_id: "c1",
        source: "assistant",
        kind: "assistant.natural_language",
        delta: "正在解析配置...",
      },
    });

    await waitFor(() => {
      expect(screen.getByText("正在解析配置...")).toBeInTheDocument();
    });

    // 推送第二个 delta
    lastInstance().emit({
      kind: "event",
      event: "message.delta",
      sequence: 12,
      payload: {
        message_id: "m-stream-1",
        conversation_id: "c1",
        source: "assistant",
        kind: "assistant.natural_language",
        delta: "解析成功，一切正常。",
      },
    });

    await waitFor(() => {
      expect(screen.getByText("正在解析配置...解析成功，一切正常。")).toBeInTheDocument();
    });

    // 推送 finalized
    lastInstance().emit({
      kind: "event",
      event: "message.finalized",
      sequence: 13,
      payload: {
        message_id: "m-stream-1",
        conversation_id: "c1",
        text: "正在解析配置...解析成功，一切正常。",
      },
    });

    await waitFor(() => {
      expect(screen.getByText("正在解析配置...解析成功，一切正常。")).toBeInTheDocument();
    });
  });
});
