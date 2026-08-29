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
      pair: null,
      activeTask: null,
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

  it("V0.3.5：审批卡片可操作；点击批准发送 approval.resolve", async () => {
    useMobileStore.setState({
      approvals: [SAMPLE_APPROVAL],
    });

    render(<ChatPage conversationId="c1" />);

    // 验证审批卡片渲染
    expect(screen.getByTestId("approval-card")).toBeInTheDocument();
    expect(screen.getByText("更新项目配置文件")).toBeInTheDocument();
    expect(screen.getByText("src/config.json")).toBeInTheDocument();

    // V0.3.5 P1：手机端展示审批按钮且可用。
    const approveButton = screen.getByTestId("approval-approve");
    const rejectButton = screen.getByTestId("approval-reject");
    expect(approveButton).toBeInTheDocument();
    expect(rejectButton).toBeInTheDocument();
    expect(approveButton).not.toBeDisabled();
    expect(rejectButton).not.toBeDisabled();

    // 点击批准后发出 approval.resolve 帧
    fireEvent.click(approveButton);
    await vi.waitFor(() => {
      const resolveFrame = lastInstance()
        .sent.map((raw) => JSON.parse(raw))
        .find((frame) => frame.method === "approval.resolve");
      expect(resolveFrame).toBeDefined();
      expect(resolveFrame.params).toMatchObject({
        approval_id: "app-1",
        decision: "approve",
      });
    });
    const resolveFrame = lastInstance()
      .sent.map((raw) => JSON.parse(raw))
      .find((frame) => frame.method === "approval.resolve");
    lastInstance().emit({ kind: "response", id: resolveFrame.id, ok: true, result: {} });

    // 服务端返回 resolved 事件后，卡片进入已决状态
    lastInstance().emit({
      kind: "event",
      event: "approval.resolved",
      sequence: 11,
      payload: { approval_id: "app-1", decision: "approve", resolved_by: "mobile", conversation_id: "c1" },
    });

    await waitFor(() => {
      expect(screen.getByTestId("approval-status")).toHaveTextContent("已批准");
      expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent(/手机端/);
    });
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

    await waitFor(() => {
      expect(useMobileStore.getState().activeConversationId).toBe("c1");
    });

    // V0.3.4：切到「交给助手」目标（协作模式下可用）
    fireEvent.click(screen.getByTestId("target-btn-assistant"));
    const input = screen.getByTestId("chat-input");
    const submitBtn = screen.getByTestId("chat-submit-btn");

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

    await waitFor(() => {
      expect(useMobileStore.getState().activeConversationId).toBe("c1");
    });

    fireEvent.click(screen.getByTestId("target-btn-assistant"));
    const input = screen.getByTestId("chat-input");
    const submitBtn = screen.getByTestId("chat-submit-btn");

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
      expect(screen.getByTestId("chat-composer-error")).toBeInTheDocument();
      expect(screen.getByText(/桌面端正在执行其他任务/)).toBeInTheDocument();
    });
  });

  it("V0.3.4 缺陷 3：「发给角色」提交 target=character 的 chat.submit", async () => {
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

    await waitFor(() => {
      expect(useMobileStore.getState().activeConversationId).toBe("c1");
    });

    // 默认目标即「发给角色」
    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "今天好累，陪我聊聊" } });
    fireEvent.click(screen.getByTestId("chat-submit-btn"));

    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("chat.submit");
    });
    const submitFrame = lastSentFrame();
    expect(submitFrame.params).toMatchObject({
      conversation_id: "c1",
      target: "character",
      text: "今天好累，陪我聊聊",
    });
    expect(submitFrame.params).not.toHaveProperty("mode");
  });

  it("V0.3.4 缺陷 4：对话模式下助手输入前置禁用，切换模式发 conversation.set_mode", async () => {
    useMobileStore.setState({
      conversationsById: { c1: { ...CONVERSATION, last_mode: "chat" } },
    });
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
        conversation: { ...CONVERSATION, last_mode: "chat" },
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

    // 对话模式：切到助手目标后前置禁用并说明
    fireEvent.click(screen.getByTestId("target-btn-assistant"));
    expect(screen.getByTestId("chat-input")).toBeDisabled();
    expect(screen.getByTestId("chat-submit-btn")).toBeDisabled();
    expect(screen.getByTestId("chat-composer-hint")).toHaveTextContent(
      /对话模式下助手不接收委派/,
    );

    // 切换到协作模式：发出 conversation.set_mode
    fireEvent.click(screen.getByTestId("mode-btn-collaboration"));
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("conversation.set_mode");
    });
    const modeFrame = lastSentFrame();
    expect(modeFrame.params).toMatchObject({
      conversation_id: "c1",
      mode: "collaboration",
    });

    // conversation.changed 到达前 UI 仍是禁用（不乐观更新）
    expect(screen.getByTestId("chat-input")).toBeDisabled();

    lastInstance().emit({
      kind: "response",
      id: modeFrame.id,
      ok: true,
      result: { conversation_id: "c1", mode: "collaboration" },
    });
    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      sequence: 11,
      payload: { conversation: CONVERSATION },
    });

    // 协作模式生效后助手输入解锁
    await waitFor(() => {
      expect(screen.getByTestId("chat-input")).not.toBeDisabled();
    });
    expect(screen.getByText("协作模式")).toBeInTheDocument();
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

  it("V0.3.4 缺陷 8：角色思考流（character.speech + channel=reasoning）进折叠思考段，不混入正文", async () => {
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
    await waitFor(() => {
      expect(useMobileStore.getState().activeConversationId).toBe("c1");
    });

    // 角色思考增量：kind=character.speech + channel=reasoning
    lastInstance().emit({
      kind: "event",
      event: "message.delta",
      sequence: 11,
      payload: {
        message_id: "m-char-think",
        conversation_id: "c1",
        source: "character",
        kind: "character.speech",
        channel: "reasoning",
        delta: "他今天似乎很累，我先关心一下。",
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("reasoning-ribbon")).toBeInTheDocument();
      expect(screen.getByTestId("reasoning-body")).toHaveTextContent(
        "他今天似乎很累，我先关心一下。",
      );
    });
    // 思考文本不得拼进正文气泡（.mobile-msg-text）
    const bodyTexts = Array.from(document.querySelectorAll(".mobile-msg-text"));
    expect(
      bodyTexts.some((el) => el.textContent?.includes("他今天似乎很累")),
    ).toBe(false);

    // 同消息的正文增量与思考分开
    lastInstance().emit({
      kind: "event",
      event: "message.delta",
      sequence: 12,
      payload: {
        message_id: "m-char-think",
        conversation_id: "c1",
        source: "character",
        kind: "character.speech",
        delta: "辛苦了，今天想聊些什么？",
      },
    });

    await waitFor(() => {
      expect(screen.getByText("辛苦了，今天想聊些什么？")).toBeInTheDocument();
    });
    // 思考段仍然独立存在
    expect(screen.getByTestId("reasoning-body")).toHaveTextContent(
      "他今天似乎很累，我先关心一下。",
    );
  });

  it("V0.3.4 缺陷 2：角色委派消息渲染为「来自 <角色名> 的委派」卡片而非用户气泡", async () => {
    const delegationMessage: Message = {
      message_id: "msg-del-1",
      conversation_id: "c1",
      pair_id: "pair-1",
      engine_turn_id: null,
      source: "user",
      kind: "user.text",
      text: "查看项目目录结构",
      payload: {},
      tts_eligible: false,
      created_at: "2026-08-20T00:02:00Z",
      origin: "character_delegation",
      delegation_id: "task-del-1",
      status: "processing",
    };
    const pairRecord = {
      pair_id: "pair-1",
      character: { id: "phainon", name: "白厄", voice_id: "" },
      assistant: { id: "fourth_mirror", name: "第四面镜", voice_id: "" },
      theme: { id: "ancient_machine", name: "古代机械" },
    };

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
        pair: pairRecord,
        messages: [SAMPLE_MESSAGE, delegationMessage],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("delegation-card")).toBeInTheDocument();
    });
    const card = screen.getByTestId("delegation-card");
    // 来自角色（白厄）的委派，运行中（status=processing），而非「你」的用户气泡
    expect(card).toHaveTextContent("来自 白厄 的委派");
    expect(card).toHaveTextContent("查看项目目录结构");
    expect(card).toHaveAttribute("data-delegation-status", "running");
    expect(screen.queryByText("你")).toBeNull();
  });
});
