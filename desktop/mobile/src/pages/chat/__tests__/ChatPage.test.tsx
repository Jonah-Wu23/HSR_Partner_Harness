import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  ConversationOpenResult,
  ConversationRecord,
  Message,
  PairRecord,
  PendingApproval,
  ProjectRecord,
  ToolRun,
} from "@shared/contracts/protocol";
import {
  mobileWsClient,
  TTS_MAX_BUFFERED_PCM_BYTES,
  useMobileStore,
} from "../../../lib/mobileStore";
import { navigate } from "../../../lib/router";
import { installFakeWebSocket, latestSocket } from "../../../test/fakeWebSocket";
import { ChatPage } from "../ChatPage";

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

const PROJECT: Omit<ProjectRecord, "conversations"> = {
  project_id: "p1",
  name: "桌面端",
  root_path: "D:/work/desktop",
  approval_mode: "request_approval",
  reasoning_effort: "medium",
  archived: false,
  created_at: "2026-08-20T00:00:00Z",
  last_opened_at: "2026-08-20T00:00:00Z",
  path_available: true,
};

const PAIR: PairRecord = {
  pair_id: "pair-1",
  character: { id: "phainon", name: "白厄", voice_id: "" },
  assistant: { id: "fourth_mirror", name: "第四面镜", voice_id: "" },
  theme: {
    character_text: "#3b2a14",
    character_primary: "#c8922a",
    character_deep: "#7a5418",
    character_active: "#e0a93c",
    assistant_primary: "#3d7bd8",
    assistant_bright: "#6aa0ef",
    assistant_shadow: "#1f3f73",
  },
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
  timeline_order: 1,
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
  timeline_order: 2,
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

/** approval.resolved 载荷中与裁决结果无关的字段。 */
const RESOLVED_BASE = {
  approval_id: "app-1",
  conversation_id: "c1",
  task_id: "task-1",
  actor: "user",
  request_reason: "需要确认写入配置",
  resolution_reason: null,
  resolved_at: "2026-08-20T00:03:00Z",
  error_code: null,
} as const;

function openResult(overrides: Partial<ConversationOpenResult> = {}): ConversationOpenResult {
  return {
    conversation: CONVERSATION,
    project: PROJECT,
    pair: PAIR,
    messages: [],
    tool_runs: [],
    turns: [],
    queue_items: [],
    active_task: null,
    sequence: 10,
    stream_id: "stream-current",
    ...overrides,
  };
}

/** 渲染聊天页并回放 conversation.open 的响应；装载结果的序号是 10，之后的事件从 11 起。 */
async function renderOpenedChat(result: ConversationOpenResult = openResult()): Promise<void> {
  render(<ChatPage conversationId="c1" />);
  const socket = latestSocket();
  await vi.waitFor(() => socket.lastFrame("conversation.open"));
  socket.respond(socket.lastFrame("conversation.open"), result);
  await waitFor(() => expect(useMobileStore.getState().timelineLoading).toBe(false));
}

function emitEvent(event: string, sequence: number, payload: unknown): void {
  latestSocket().emit({ kind: "event", event, sequence, payload });
}

/** 已打开的聊天收到一条待审批请求。 */
async function renderChatWithPendingApproval(): Promise<void> {
  await renderOpenedChat();
  emitEvent("approval.requested", 11, SAMPLE_APPROVAL);
  await screen.findByTestId("approval-card");
}

/** 点击批准，返回发出的 approval.resolve 请求帧。 */
async function clickApprove() {
  fireEvent.click(screen.getByTestId("approval-approve"));
  const socket = latestSocket();
  await vi.waitFor(() => socket.lastFrame("approval.resolve"));
  return socket.lastFrame("approval.resolve");
}

/** 在输入框填入文本并提交，返回发出的 chat.submit 请求帧。 */
async function submitText(text: string) {
  fireEvent.change(screen.getByTestId("chat-input"), { target: { value: text } });
  fireEvent.click(screen.getByTestId("chat-submit-btn"));
  const socket = latestSocket();
  await vi.waitFor(() => socket.lastFrame("chat.submit"));
  return socket.lastFrame("chat.submit");
}

describe("ChatPage 聊天页", () => {
  beforeEach(async () => {
    installFakeWebSocket();
    window.localStorage.clear();
    // disconnect 把会话级状态复位到初值；会话记录在生产中由 app.bootstrap 快照写入，这里作为前置条件。
    await useMobileStore.getState().disconnect();
    useMobileStore.setState({ conversationsById: { c1: CONVERSATION } });
    useMobileStore.getState().start();
    mobileWsClient.connect();
    latestSocket().open();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("挂载时发出 conversation.open，装载结果中的消息与工具卡进入时间线", async () => {
    await renderOpenedChat(openResult({ messages: [SAMPLE_MESSAGE], tool_runs: [SAMPLE_TOOL_RUN] }));

    expect(latestSocket().lastFrame("conversation.open").params).toMatchObject({
      conversation_id: "c1",
    });
    await waitFor(() => {
      expect(screen.getByText("开发架构重构")).toBeInTheDocument();
      expect(screen.getByText("协作模式")).toBeInTheDocument();
      expect(screen.getByText("我已经准备好接下来的开发任务了。")).toBeInTheDocument();
      expect(screen.getByText("工具调用")).toBeInTheDocument();
      expect(screen.getByText("已完成")).toBeInTheDocument();
    });
  });

  it("装载失败时展示原始错误，点击重试重新发出 conversation.open", async () => {
    render(<ChatPage conversationId="c1" />);
    const socket = latestSocket();
    await vi.waitFor(() => socket.lastFrame("conversation.open"));
    socket.respondError(socket.lastFrame("conversation.open"), "conversation_not_found", "会话不存在：c1");

    expect(await screen.findByTestId("chat-open-error")).toHaveTextContent(
      "会话装载失败：会话不存在：c1",
    );
    fireEvent.click(screen.getByTestId("chat-open-retry"));
    await vi.waitFor(() => expect(socket.sentFrames("conversation.open")).toHaveLength(2));
  });

  it("批准待审批操作发出 approval.resolve，approval.resolved 到达后卡片显示终态", async () => {
    await renderChatWithPendingApproval();
    expect(screen.getByText("更新项目配置文件")).toBeInTheDocument();

    const frame = await clickApprove();
    expect(frame.params).toEqual({ approval_id: "app-1", decision: "allow" });
    latestSocket().respond(frame, {
      approval_id: "app-1",
      accepted: true,
      resolved_by: "remote",
      decision: "allow",
    });
    emitEvent("approval.resolved", 12, { ...RESOLVED_BASE, decision: "allow", resolved_by: "remote" });

    await waitFor(() => {
      expect(screen.getByTestId("approval-status")).toHaveTextContent("已批准");
      expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent("由 手机端 已批准");
    });
    expect(screen.queryByTestId("approval-approve")).toBeNull();
  });

  it("审批提交失败时在页内展示错误码与原文，不显示终态", async () => {
    await renderChatWithPendingApproval();
    latestSocket().respondError(
      await clickApprove(),
      "approval_not_found",
      "审批请求不存在或已经完成：app-1",
    );

    await waitFor(() => {
      expect(screen.getByTestId("approval-resolve-error")).toHaveTextContent(
        "审批提交失败：approval_not_found：审批请求不存在或已经完成：app-1",
      );
    });
    expect(screen.queryByTestId("approval-status")).toBeNull();
  });

  it("审批已被另一端裁决时按错误 details 中的终态收敛并展示服务端原文", async () => {
    await renderChatWithPendingApproval();
    const frame = await clickApprove();
    latestSocket().emit({
      kind: "response",
      id: frame.id,
      ok: false,
      error: {
        code: "approval_already_resolved",
        message: "审批已由 desktop 应答（deny），不能重复应答",
        details: { ...RESOLVED_BASE, decision: "deny", resolved_by: "desktop" },
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("approval-resolve-notice")).toHaveTextContent(
        "审批已由服务端终态收敛：审批已由 desktop 应答（deny），不能重复应答",
      );
    });
    expect(screen.queryByTestId("approval-resolve-error")).toBeNull();
    expect(screen.getByTestId("approval-status")).toHaveTextContent("已拒绝");
    expect(screen.getByTestId("approval-resolved-by")).toHaveTextContent("由 桌面端 已拒绝");
  });

  it.each([
    { button: "target-btn-character", target: "character", text: "今天好累，陪我聊聊" },
    { button: "target-btn-assistant", target: "assistant", text: "把所有单元测试运行一遍" },
  ])("目标 $target 提交 chat.submit 且不带 mode，成功后清空输入", async ({ button, target, text }) => {
    await renderOpenedChat();
    fireEvent.click(screen.getByTestId(button));

    const frame = await submitText(text);
    // 模式以服务端会话记录为准，提交不带 mode。
    expect(frame.params).toEqual({ conversation_id: "c1", target, text });
    latestSocket().respond(frame, {
      message_id: "m-user-1",
      conversation_id: "c1",
      status: "received",
      target,
      turn_id: "turn-1",
    });

    await waitFor(() => expect(screen.getByTestId("chat-input")).toHaveValue(""));
  });

  it("委派被服务端拒绝时如实展示错误并保留输入", async () => {
    await renderOpenedChat();
    fireEvent.click(screen.getByTestId("target-btn-assistant"));

    latestSocket().respondError(
      await submitText("启动构建"),
      "assistant_not_allowed_in_chat_mode",
      "聊天模式不能直接交给助手，请先切换到协作模式",
    );

    await waitFor(() => {
      expect(screen.getByTestId("chat-composer-error")).toHaveTextContent(
        "委派失败：聊天模式不能直接交给助手，请先切换到协作模式",
      );
    });
    expect(screen.getByTestId("chat-input")).toHaveValue("启动构建");
  });

  it("对话模式下交给助手被前置禁用；切到协作模式发 conversation.set_mode，conversation.changed 到达后解锁", async () => {
    const chatModeConversation = { ...CONVERSATION, last_mode: "chat" };
    useMobileStore.setState({ conversationsById: { c1: chatModeConversation } });
    await renderOpenedChat(openResult({ conversation: chatModeConversation }));

    fireEvent.click(screen.getByTestId("target-btn-assistant"));
    expect(screen.getByTestId("chat-input")).toBeDisabled();
    expect(screen.getByTestId("chat-submit-btn")).toBeDisabled();
    expect(screen.getByTestId("chat-composer-hint")).toHaveTextContent(
      /对话模式下助手不接收委派/,
    );

    fireEvent.click(screen.getByTestId("mode-btn-collaboration"));
    const socket = latestSocket();
    await vi.waitFor(() => socket.lastFrame("conversation.set_mode"));
    const modeFrame = socket.lastFrame("conversation.set_mode");
    expect(modeFrame.params).toEqual({ conversation_id: "c1", mode: "collaboration" });
    socket.respond(modeFrame, { conversation_id: "c1", mode: "collaboration" });

    // 响应回来后仍按旧模式禁用：模式以 conversation.changed 为准，不做乐观更新。
    await waitFor(() => expect(screen.getByTestId("mode-btn-collaboration")).toBeEnabled());
    expect(screen.getByTestId("chat-input")).toBeDisabled();

    emitEvent("conversation.changed", 11, { conversation: CONVERSATION });

    await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
    expect(screen.getByText("协作模式")).toBeInTheDocument();
  });

  it("message.delta 增量拼进同一个气泡，message.finalized 后正文保持完整", async () => {
    await renderOpenedChat();
    const segment = {
      message_id: "m-stream-1",
      conversation_id: "c1",
      source: "assistant",
      kind: "assistant.natural_language",
      task_id: "task-1",
      segment_index: 0,
      timeline_order: 1,
      reasoning_streaming: false,
    };

    emitEvent("message.delta", 11, { ...segment, delta: "正在解析配置..." });
    expect(await screen.findByText("正在解析配置...")).toBeInTheDocument();

    emitEvent("message.delta", 12, { ...segment, delta: "解析成功，一切正常。" });
    expect(await screen.findByText("正在解析配置...解析成功，一切正常。")).toBeInTheDocument();

    emitEvent("message.finalized", 13, {
      conversation_id: "c1",
      task_id: "task-1",
      message_id: "m-stream-1",
    });
    await waitFor(() => expect(useMobileStore.getState().messages[0]?.streaming).toBe(false));
    expect(screen.getAllByTestId("message-bubble")).toHaveLength(1);
    expect(screen.getByText("正在解析配置...解析成功，一切正常。")).toBeInTheDocument();
  });

  it("角色 reasoning 通道的增量进入折叠思考段，正文增量单独成文", async () => {
    await renderOpenedChat();
    const speech = {
      message_id: "speech:c1:msg-user-1",
      conversation_id: "c1",
      pair_id: "pair-1",
      source: "character",
      kind: "character.speech",
      timeline_order: 2,
    };

    emitEvent("message.delta", 11, {
      ...speech,
      channel: "reasoning",
      reasoning_streaming: true,
      started: true,
      delta: "他今天似乎很累，我先关心一下。",
    });
    await waitFor(() => {
      expect(screen.getByTestId("reasoning-body")).toHaveTextContent(
        "他今天似乎很累，我先关心一下。",
      );
    });

    emitEvent("message.delta", 12, {
      ...speech,
      channel: "reasoning",
      reasoning_streaming: false,
      completed: true,
      delta: "",
    });
    emitEvent("message.delta", 13, { ...speech, delta: "辛苦了，今天想聊些什么？" });

    // 正文按原文精确匹配：思考文本没有拼进正文。
    expect(await screen.findByText("辛苦了，今天想聊些什么？")).toBeInTheDocument();
    const ribbon = screen.getByTestId("reasoning-ribbon");
    fireEvent.click(within(ribbon).getByRole("button"));
    expect(within(ribbon).getByTestId("reasoning-body")).toHaveTextContent(
      "他今天似乎很累，我先关心一下。",
    );
  });

  it("角色发起的委派渲染为「来自 <角色名> 的委派」卡片，不显示成用户气泡", async () => {
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
      timeline_order: 3,
      origin: "character_delegation",
      delegation_id: "task-del-1",
      status: "processing",
    };

    await renderOpenedChat(openResult({ messages: [SAMPLE_MESSAGE, delegationMessage] }));

    const card = await screen.findByTestId("delegation-card");
    expect(card).toHaveTextContent("来自 白厄 的委派");
    expect(card).toHaveTextContent("查看项目目录结构");
    expect(card).toHaveTextContent("运行中");
    expect(screen.queryByText("你")).toBeNull();
  });

  it("从列表进入聊天后点返回，回退既有历史条目，不压入新条目", async () => {
    // 模拟真实进入路径：列表 →（应用内压栈）→ 聊天
    window.location.hash = "#/list";
    navigate({ name: "chat", conversationId: "c1" });
    await vi.waitFor(() => expect(window.location.hash).toBe("#/chat/c1"));

    render(<ChatPage conversationId="c1" />);
    const lengthBeforeBack = window.history.length;

    fireEvent.click(screen.getByRole("button", { name: "返回聊天列表" }));

    await vi.waitFor(() => expect(window.location.hash).toBe("#/list"));
    expect(window.history.length).toBe(lengthBeforeBack);
  });

  it("深链直接落在聊天页时点返回，替换为列表页，不新增历史条目", () => {
    window.location.hash = "#/chat/c1";
    const lengthBeforeBack = window.history.length;

    render(<ChatPage conversationId="c1" />);
    fireEvent.click(screen.getByRole("button", { name: "返回聊天列表" }));

    expect(window.location.hash).toBe("#/list");
    expect(window.history.length).toBe(lengthBeforeBack);
  });

  it("voice.mobile_tts_failed 的供应商错误原文进入页级错误条，事件没有错误码时不显示错误码", async () => {
    await renderOpenedChat();

    // 只发给手机的语音事件不带序号。
    latestSocket().emit({
      kind: "event",
      event: "voice.mobile_tts_failed",
      payload: {
        conversation_id: "c1",
        message_id: "m-tts-failed-1",
        error: "InvalidParameter: voice not found",
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("playback-error-bar")).toHaveTextContent(
        "InvalidParameter: voice not found",
      );
    });
    expect(screen.queryByTestId("playback-error-code")).toBeNull();
  });

  it("播放失败带错误码时页级错误条一并展示错误码", async () => {
    // 与 store 处理 PCM 缓冲超限时写入的播放状态同形。
    const error = `播放缓冲超过上限（${TTS_MAX_BUFFERED_PCM_BYTES} 字节，约 300 秒音频），已中止播放`;
    useMobileStore.setState({
      voice: {
        ...useMobileStore.getState().voice,
        playback: { messageId: "m-tts-overflow", state: "failed", error, errorCode: "pcm_overflow" },
      },
    });
    await renderOpenedChat();

    expect(screen.getByTestId("playback-error-code")).toHaveTextContent("pcm_overflow");
    expect(screen.getByTestId("playback-error-text")).toHaveTextContent(error);
  });

  it("voice.playback_interrupted 到达后展示打断提示与服务端原因", async () => {
    await renderOpenedChat();
    expect(screen.queryByTestId("playback-interrupted")).toBeNull();

    emitEvent("voice.playback_interrupted", 11, {
      conversation_id: "c1",
      message_id: "m-old",
      reason: "new_message",
    });

    await waitFor(() => {
      expect(screen.getByTestId("playback-interrupted")).toHaveTextContent(
        "已被新回复打断 / 已停止",
      );
      expect(screen.getByTestId("playback-interrupted-reason")).toHaveTextContent("new_message");
    });
  });

  it("软键盘占位时聊天容器高度贴合 visualViewport，收起后交回 CSS", async () => {
    const listeners: Array<() => void> = [];
    const viewport = {
      height: 800,
      offsetTop: 0,
      scale: 1,
      addEventListener: (_type: string, cb: () => void) => {
        listeners.push(cb);
      },
      removeEventListener: (_type: string, cb: () => void) => {
        const index = listeners.indexOf(cb);
        if (index >= 0) listeners.splice(index, 1);
      },
    };
    Object.defineProperty(window, "visualViewport", {
      value: viewport,
      configurable: true,
      writable: true,
    });

    try {
      render(<ChatPage conversationId="c1" />);
      const page = screen.getByTestId("chat-page");
      expect(page).not.toHaveAttribute("data-keyboard");

      // 键盘弹出：可视高度明显小于布局视口，容器高度经 CSS 变量贴合可视视口
      viewport.height = 400;
      listeners.forEach((cb) => cb());
      await waitFor(() => {
        expect(page).toHaveAttribute("data-keyboard", "open");
        expect(page.style.getPropertyValue("--chat-viewport-height")).toBe("400px");
      });

      // 键盘收起：交回 CSS 的 dvh / vh 回退
      viewport.height = 800;
      listeners.forEach((cb) => cb());
      await waitFor(() => {
        expect(page).not.toHaveAttribute("data-keyboard");
        expect(page.style.getPropertyValue("--chat-viewport-height")).toBe("");
      });
    } finally {
      delete (window as unknown as { visualViewport?: unknown }).visualViewport;
    }
  });
});
