import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationRecord, DesktopSnapshot, Message, PairRecord } from "@shared/contracts/protocol";
import { mobileWsClient, useMobileStore } from "./mobileStore";
import { getStoredToken } from "./wsClient";

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
  pair_id: "pair-default",
  title: "测试聊天",
  last_mode: "collaboration",
  archived: false,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

function snapshotResult(sequence: number): DesktopSnapshot {
  return {
    projects: [
      {
        project_id: "p1",
        name: "演示项目",
        conversations: [CONVERSATION],
      },
    ],
    messages: [],
    tool_runs: [],
    approvals: [],
    sequence,
    stream_id: "stream-current",
  } as unknown as DesktopSnapshot;
}

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

/** 走通 pair 流程并留下已水合状态（lastSequence=10）。 */
async function pairAndBootstrap(): Promise<void> {
  const pairPromise = useMobileStore.getState().pairDevice("654321", "我的小米");
  // pairDevice() 内部先 await 连接就绪，remote.pair 帧在 microtask 后才发出。
  await vi.waitFor(() => {
    expect(lastSentFrame().method).toBe("remote.pair");
  });
  const pairFrame = lastSentFrame();
  lastInstance().emit({ kind: "response", id: pairFrame.id, ok: true, result: { token: "tok-9" } });
  await vi.waitFor(() => {
    expect(lastSentFrame().method).toBe("app.bootstrap");
  });
  const bootstrapFrame = lastSentFrame();
  lastInstance().emit({
    kind: "response",
    id: bootstrapFrame.id,
    ok: true,
    result: snapshotResult(10),
  });
  await pairPromise;
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  mobileWsClient.disconnect();
  FakeWebSocket.instances = [];
  window.localStorage.clear();
  useMobileStore.setState({
    connection: "disconnected",
    deviceName: null,
    projects: [],
    conversationsById: {},
    activeConversationId: null,
    messages: [],
    toolRuns: [],
    approvals: [],
    resolvedApprovals: [],
    pair: null,
    activeTask: null,
    streamId: null,
    lastSequence: 0,
    bootstrapped: false,
    voice: {
      capture: { state: "idle", sessionId: null, error: null },
      transcript: null,
      playback: { messageId: null, state: "idle", error: null },
      availability: { secureContext: false, micPermission: "unknown", supported: false },
      ttsChunks: {},
    },
  });
  useMobileStore.getState().start();
  mobileWsClient.connect();
  lastInstance().open();
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("mobileStore 配对与水合", () => {
  it("pair 成功后保存凭证并 bootstrap 水合索引", async () => {
    await pairAndBootstrap();
    expect(getStoredToken()).toBe("tok-9");
    const state = useMobileStore.getState();
    expect(state.deviceName).toBe("我的小米");
    expect(state.bootstrapped).toBe(true);
    expect(state.projects).toHaveLength(1);
    expect(state.conversationsById.c1?.title).toBe("测试聊天");
    expect(state.lastSequence).toBe(10);
  });

  it("bootstrap 请求携带配对 token", async () => {
    await pairAndBootstrap();
    // pairAndBootstrap 内部已断言 remote.pair 无 auth；这里补查 bootstrap 帧。
    // 帧序列：remote.pair → app.bootstrap
    const bootstrapRaw = lastInstance().sent[1];
    expect(JSON.parse(bootstrapRaw)).toMatchObject({
      method: "app.bootstrap",
      auth: { token: "tok-9" },
    });
  });
});

describe("mobileStore 事件一致性", () => {
  it("旧序号事件被去重，会话变更按序合并", async () => {
    await pairAndBootstrap();
    const renamed = { ...CONVERSATION, title: "改名后" };
    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      sequence: 11,
      payload: { conversation: renamed },
    });
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("改名后");

    // 重复投递同一序号：payload 换成别的标题，不应再合并。
    const stale = { ...CONVERSATION, title: "过期标题" };
    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      sequence: 11,
      payload: { conversation: stale },
    });
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("改名后");
  });

  it("事件序号缺口触发重新 bootstrap，不猜中间态", async () => {
    await pairAndBootstrap();
    const sentBefore = lastInstance().sent.length;
    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      sequence: 15,
      payload: { conversation: { ...CONVERSATION, title: "缺口后标题" } },
    });
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("app.bootstrap");
    });
    expect(lastInstance().sent.length).toBe(sentBefore + 1);
    // 缺口事件本身未被合并。
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("测试聊天");
    const reBootstrap = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: reBootstrap.id,
      ok: true,
      result: snapshotResult(15),
    });
    await vi.waitFor(() => {
      expect(useMobileStore.getState().lastSequence).toBe(15);
    });
  });

  it("approval.requested 与 approval.resolved 维护审批列表", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "approval.requested",
      sequence: 11,
      // 真实协议：payload 平铺即为 PendingApproval（非 {"approval": {...}} 嵌套）。
      payload: {
        approval_id: "a1",
        conversation_id: "c1",
        task_id: "t1",
        operation: { tool_kind: "shell", command: "npm test", paths: [], patch_file_count: null, summary: "跑测试" },
        reason: "风险规则",
      },
    });
    expect(useMobileStore.getState().approvals).toHaveLength(1);
    lastInstance().emit({
      kind: "event",
      event: "approval.resolved",
      sequence: 12,
      payload: { approval_id: "a1" },
    });
    expect(useMobileStore.getState().approvals).toHaveLength(0);
  });
});

describe("mobileStore 会话操作", () => {
  it("openConversation 装载消息，submitDelegation 用会话 last_mode", async () => {
    await pairAndBootstrap();
    const openPromise = useMobileStore.getState().openConversation("c1");
    // openConversation 先 await 连接就绪，帧在 microtask 后才发出。
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("conversation.open");
    });
    const openFrame = lastSentFrame();
    expect(openFrame).toMatchObject({
      method: "conversation.open",
      params: { conversation_id: "c1" },
    });
    expect((openFrame.params as { view_id?: string }).view_id).toMatch(/^mobile-/);
    lastInstance().emit({
      kind: "response",
      id: openFrame.id,
      ok: true,
      result: {
        conversation: CONVERSATION,
        project: null,
        pair: null,
        messages: [{ message_id: "m1", conversation_id: "c1" }],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
      },
    });
    await openPromise;
    expect(useMobileStore.getState().messages).toHaveLength(1);
    expect(useMobileStore.getState().activeConversationId).toBe("c1");

    const submitPromise = useMobileStore.getState().submitDelegation("去把 README 翻成英文");
    const submitFrame = lastSentFrame();
    expect(submitFrame).toMatchObject({
      method: "chat.submit",
      params: {
        conversation_id: "c1",
        target: "assistant",
        mode: "collaboration",
        text: "去把 README 翻成英文",
      },
    });
    lastInstance().emit({ kind: "response", id: submitFrame.id, ok: true, result: {} });
    await submitPromise;
  });

  it("openConversation 在 WS 握手未完成时等待连接就绪再发请求", async () => {
    // 模拟刷新后直接落在聊天页：连接尚未建立，装载不许报「WebSocket 未连接」。
    mobileWsClient.disconnect();
    FakeWebSocket.instances = [];

    const openPromise = useMobileStore.getState().openConversation("c1");
    // connect() 已触发但握手未完成，此时不应发出任何帧。
    expect(lastInstance().readyState).toBe(FakeWebSocket.CONNECTING);
    expect(lastInstance().sent).toEqual([]);

    lastInstance().open();
    await vi.waitFor(() => {
      expect(lastSentFrame().method).toBe("conversation.open");
    });
    const openFrame = lastSentFrame();
    expect(openFrame.params).toMatchObject({ conversation_id: "c1" });
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
    await openPromise;
    expect(useMobileStore.getState().activeConversationId).toBe("c1");
  });

  it("openConversation 失败时恢复原会话时间线", async () => {
    await pairAndBootstrap();
    const previousMessage = {
      message_id: "previous-message",
      conversation_id: "c1",
      text: "原会话消息",
    } as Message;
    useMobileStore.setState({
      activeConversationId: "c1",
      messages: [previousMessage],
    });

    const openPromise = useMobileStore.getState().openConversation("c2");
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("conversation.open"));
    const openFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: openFrame.id,
      ok: false,
      error: { code: "conversation_not_found", message: "聊天不存在" },
    });

    await expect(openPromise).rejects.toThrow("聊天不存在");
    expect(useMobileStore.getState()).toMatchObject({
      activeConversationId: "c1",
      messages: [previousMessage],
    });
  });

  it("openConversation 失败后重放等待期间的事件并标记未完成水合", async () => {
    await pairAndBootstrap();
    useMobileStore.setState({ activeConversationId: "c1" });
    const openPromise = useMobileStore.getState().openConversation("c2");
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("conversation.open"));
    const openFrame = lastSentFrame();

    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      stream_id: "stream-current",
      sequence: 11,
      payload: { conversation: { ...CONVERSATION, title: "等待期更新" } },
    });
    lastInstance().emit({
      kind: "response",
      id: openFrame.id,
      ok: false,
      error: { code: "conversation_not_found", message: "聊天不存在" },
    });

    await expect(openPromise).rejects.toThrow("聊天不存在");
    expect(useMobileStore.getState()).toMatchObject({
      activeConversationId: "c1",
      lastSequence: 11,
      bootstrapped: false,
    });
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("等待期更新");
  });

  it("V0.3.4 submitMessage 发 target=character 且不带 mode 参数", async () => {
    await pairAndBootstrap();
    const openPromise = useMobileStore.getState().openConversation("c1");
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
    await openPromise;

    const submitPromise = useMobileStore.getState().submitMessage("今天好累");
    const submitFrame = lastSentFrame();
    expect(submitFrame).toMatchObject({
      method: "chat.submit",
      params: {
        conversation_id: "c1",
        target: "character",
        text: "今天好累",
      },
    });
    // 角色消息不带 mode：避免顺带切换会话模式。
    expect(submitFrame.params).not.toHaveProperty("mode");
    lastInstance().emit({ kind: "response", id: submitFrame.id, ok: true, result: {} });
    await submitPromise;
  });

  it("V0.3.4 setConversationMode 发 conversation.set_mode 且不做乐观更新", async () => {
    await pairAndBootstrap();
    // 用 chat 模式的会话验证：切换请求成功后 last_mode 仍等 conversation.changed。
    useMobileStore.setState({
      conversationsById: { c1: { ...CONVERSATION, last_mode: "chat" } },
    });
    const modePromise = useMobileStore.getState().setConversationMode("c1", "collaboration");
    const frame = lastSentFrame();
    expect(frame).toMatchObject({
      method: "conversation.set_mode",
      params: { conversation_id: "c1", mode: "collaboration" },
    });
    lastInstance().emit({ kind: "response", id: frame.id, ok: true, result: { conversation_id: "c1", mode: "collaboration" } });
    await modePromise;
    // 不做乐观更新：response 成功也不改 last_mode。
    expect(useMobileStore.getState().conversationsById.c1?.last_mode).toBe("chat");

    // conversation.changed 事件到达后才更新。
    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      sequence: 11,
      payload: { conversation: CONVERSATION },
    });
    expect(useMobileStore.getState().conversationsById.c1?.last_mode).toBe("collaboration");
  });

  it("V0.3.4 openConversation 水合 pair 与 active_task（委派卡数据源）", async () => {
    await pairAndBootstrap();
    const pairRecord = {
      pair_id: "pair-default",
      character: { id: "phainon", name: "白厄", voice_id: "" },
      assistant: { id: "fourth_mirror", name: "第四面镜", voice_id: "" },
      theme: { id: "ancient_machine", name: "古代机械" },
    };
    const activeTask = {
      project_id: "p1",
      conversation_id: "c1",
      task_id: "task-7",
      engine_turn_id: null,
    };
    const openPromise = useMobileStore.getState().openConversation("c1");
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
        messages: [],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: activeTask,
      },
    });
    await openPromise;
    expect(useMobileStore.getState().pair).toEqual(pairRecord);
    expect(useMobileStore.getState().activeTask).toEqual(activeTask);
  });

  it("V0.3.4 Codex 建议 A：message.status_changed 推进委派消息状态", async () => {
    await pairAndBootstrap();
    const delegationMsg: Message = {
      message_id: "msg-del",
      conversation_id: "c1",
      pair_id: "pair-1",
      engine_turn_id: null,
      source: "user",
      kind: "user.text",
      text: "把 README 翻成英文",
      payload: {},
      tts_eligible: false,
      created_at: "2026-08-20T00:02:00Z",
      origin: "character_delegation",
      delegation_id: "task-1",
      status: "processing",
    };
    useMobileStore.setState({ activeConversationId: "c1", messages: [delegationMsg] });

    lastInstance().emit({
      kind: "event",
      event: "message.status_changed",
      sequence: 11,
      payload: { message: { ...delegationMsg, status: "done" } },
    });
    expect(useMobileStore.getState().messages).toHaveLength(1);
    expect(useMobileStore.getState().messages[0]!.status).toBe("done");
  });

  it("V0.3.4 Codex 建议 A：task.busy_changed 结束当前会话活动任务", async () => {
    await pairAndBootstrap();
    const activeTask = {
      project_id: "p1",
      conversation_id: "c1",
      task_id: "task-1",
      engine_turn_id: null,
    };
    useMobileStore.setState({ activeConversationId: "c1", activeTask });

    // 任务结束：busy=false（无归属字段的旧语义清空当前会话）
    lastInstance().emit({
      kind: "event",
      event: "task.busy_changed",
      sequence: 11,
      payload: { busy: false, conversation_id: "c1" },
    });
    expect(useMobileStore.getState().activeTask).toBeNull();
  });

  it("V0.3.4 Codex 建议 B：重新 bootstrap 不覆盖当前会话的 pair，activeTask 按会话选取", async () => {
    await pairAndBootstrap();
    const pairA: PairRecord = {
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
    const taskC1 = {
      project_id: "p1",
      conversation_id: "c1",
      task_id: "task-c1",
      engine_turn_id: null,
    };
    useMobileStore.setState({
      activeConversationId: "c1",
      conversationsById: { c1: CONVERSATION },
      pair: pairA,
      activeTask: taskC1,
    });

    // 重连/缺口重 bootstrap：全局快照属于桌面当前会话 B，携带不同的 pair 与任务
    const otherPair: PairRecord = {
      pair_id: "pair-B",
      character: { id: "firefly", name: "流萤", voice_id: "" },
      assistant: { id: "sam", name: "萨姆", voice_id: "" },
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
    const snapshot = {
      projects: [{ project_id: "p1", name: "演示项目", conversations: [CONVERSATION] }],
      messages: [],
      tool_runs: [],
      approvals: [],
      sequence: 20,
      pair: otherPair,
      pairs: [otherPair],
      active_task: { project_id: "p9", conversation_id: "c9", task_id: "task-B", engine_turn_id: null },
    } as unknown as DesktopSnapshot;
    lastInstance().emit({ kind: "event", event: "state.snapshot", sequence: 11, payload: snapshot });

    // 快照不含当前会话（c1）的配对：保留既有 pairA，不被桌面会话 B 覆盖
    expect(useMobileStore.getState().pair).toEqual(pairA);
    // 快照没有本会话任务信息：保留既有 activeTask
    expect(useMobileStore.getState().activeTask).toEqual(taskC1);
  });

  it("流式消息只归并一次，角色思考不会复制正文", async () => {
    await pairAndBootstrap();
    const message: Message = {
      message_id: "m-stream",
      conversation_id: "c1",
      pair_id: "pair-default",
      engine_turn_id: null,
      source: "character",
      kind: "character.speech",
      text: "正文",
      payload: {},
      tts_eligible: true,
      created_at: "2026-08-22T00:00:00Z",
    };
    useMobileStore.setState({ activeConversationId: "c1", messages: [message] });

    lastInstance().emit({
      kind: "event",
      event: "message.delta",
      sequence: 11,
      payload: {
        message_id: "m-stream",
        conversation_id: "c1",
        source: "character",
        kind: "character.speech",
        channel: "reasoning",
        delta: "思考",
      },
    });
    lastInstance().emit({
      kind: "event",
      event: "message.delta",
      sequence: 11,
      payload: {
        message_id: "m-stream",
        conversation_id: "c1",
        source: "character",
        kind: "character.speech",
        channel: "reasoning",
        delta: "思考",
      },
    });

    const updated = useMobileStore.getState().messages[0]!;
    expect(updated.text).toBe("正文");
    expect(updated.payload.reasoning).toBe("思考");
  });

  it("其他会话的状态事件不会污染当前会话", async () => {
    await pairAndBootstrap();
    const current: Message = {
      message_id: "current",
      conversation_id: "c1",
      pair_id: "pair-default",
      engine_turn_id: null,
      source: "user",
      kind: "user.text",
      text: "当前消息",
      payload: {},
      tts_eligible: false,
      created_at: "2026-08-22T00:00:00Z",
    };
    const task = {
      project_id: "p1",
      conversation_id: "c1",
      task_id: "task-c1",
      engine_turn_id: null,
    };
    useMobileStore.setState({
      activeConversationId: "c1",
      messages: [current],
      activeTask: task,
    });

    lastInstance().emit({
      kind: "event",
      event: "message.status_changed",
      sequence: 11,
      payload: { message: { ...current, message_id: "other", conversation_id: "c2" } },
    });
    lastInstance().emit({
      kind: "event",
      event: "task.busy_changed",
      sequence: 12,
      payload: { busy: false, conversation_id: "c2" },
    });

    expect(useMobileStore.getState().messages).toEqual([current]);
    expect(useMobileStore.getState().activeTask).toEqual(task);
  });

  it("bootstrap 响应可直接把旧 stream 切换到新 stream", async () => {
    await pairAndBootstrap();
    useMobileStore.setState({ streamId: "stream-old", lastSequence: 10 });

    mobileWsClient.disconnect();
    mobileWsClient.connect();
    lastInstance().open();
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("app.bootstrap"));
    const bootstrapFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: bootstrapFrame.id,
      ok: true,
      result: { ...snapshotResult(0), stream_id: "stream-next" },
    });

    await vi.waitFor(() => {
      expect(useMobileStore.getState()).toMatchObject({
        streamId: "stream-next",
        lastSequence: 0,
        bootstrapped: true,
      });
    });
  });

  it("连接代次变化时立即请求新 stream 的权威快照", async () => {
    await pairAndBootstrap();
    const sentBefore = lastInstance().sent.length;

    lastInstance().emit({
      kind: "event",
      event: "connection.status",
      stream_id: "stream-next",
      sequence: 0,
      payload: { status: "connected" },
    });

    await vi.waitFor(() => {
      expect(lastInstance().sent.length).toBe(sentBefore + 1);
      expect(lastSentFrame().method).toBe("app.bootstrap");
    });
    const bootstrapFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: bootstrapFrame.id,
      ok: true,
      result: { ...snapshotResult(0), stream_id: "stream-next" },
    });
    await vi.waitFor(() => {
      expect(useMobileStore.getState()).toMatchObject({
        streamId: "stream-next",
        bootstrapped: true,
      });
    });
  });

  it("bootstrap 等待期间收到的新事件在旧快照后重放", async () => {
    await pairAndBootstrap();

    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      stream_id: "stream-current",
      sequence: 12,
      payload: { conversation: { ...CONVERSATION, title: "触发缺口" } },
    });
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("app.bootstrap"));
    const bootstrapFrame = lastSentFrame();

    lastInstance().emit({
      kind: "event",
      event: "conversation.changed",
      stream_id: "stream-current",
      sequence: 11,
      payload: { conversation: { ...CONVERSATION, title: "实时标题" } },
    });
    lastInstance().emit({
      kind: "response",
      id: bootstrapFrame.id,
      ok: true,
      result: snapshotResult(10),
    });

    await vi.waitFor(() => {
      expect(useMobileStore.getState().lastSequence).toBe(12);
      expect(useMobileStore.getState().conversationsById.c1?.title).toBe("触发缺口");
    });
  });

  it("打开会话等待期间收到事件时按会话快照游标重放，不覆盖实时内容", async () => {
    await pairAndBootstrap();
    const openPromise = useMobileStore.getState().openConversation("c1");
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("conversation.open"));
    const openFrame = lastSentFrame();

    lastInstance().emit({
      kind: "event",
      event: "message.delta",
      stream_id: "stream-current",
      sequence: 11,
      payload: {
        message_id: "live",
        conversation_id: "c1",
        pair_id: "pair-default",
        source: "character",
        kind: "character.speech",
        channel: "speech",
        delta: "实时内容",
      },
    });
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
        sequence: 10,
        stream_id: "stream-current",
      },
    });
    await openPromise;

    expect(useMobileStore.getState().messages[0]?.text).toBe("实时内容");
    expect(useMobileStore.getState().lastSequence).toBe(11);
  });

  it("并发打开会话时忽略迟到的旧响应", async () => {
    await pairAndBootstrap();
    const c2 = { ...CONVERSATION, conversation_id: "c2", title: "第二个聊天" };
    useMobileStore.setState({
      conversationsById: { c1: CONVERSATION, c2 },
    });

    const first = useMobileStore.getState().openConversation("c1");
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("conversation.open"));
    const firstFrame = lastSentFrame();
    const second = useMobileStore.getState().openConversation("c2");
    await vi.waitFor(() => {
      expect(lastInstance().sent.length).toBeGreaterThan(3);
    });
    const secondFrame = lastSentFrame();

    lastInstance().emit({
      kind: "response",
      id: secondFrame.id,
      ok: true,
      result: {
        conversation: c2,
        project: null,
        pair: null,
        messages: [{ ...({} as Message), message_id: "m2", conversation_id: "c2" }],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
        sequence: 10,
        stream_id: "stream-current",
      },
    });
    await second;
    lastInstance().emit({
      kind: "response",
      id: firstFrame.id,
      ok: true,
      result: {
        conversation: CONVERSATION,
        project: null,
        pair: null,
        messages: [{ ...({} as Message), message_id: "m1", conversation_id: "c1" }],
        tool_runs: [],
        turns: [],
        queue_items: [],
        active_task: null,
        sequence: 10,
        stream_id: "stream-current",
      },
    });
    await first;

    expect(useMobileStore.getState().activeConversationId).toBe("c2");
    expect(useMobileStore.getState().messages[0]?.message_id).toBe("m2");
  });

  it("V0.3.4 Codex 建议 B：快照权威 active_tasks 为空时清空残留任务", async () => {
    await pairAndBootstrap();
    const staleTask = {
      project_id: "p1",
      conversation_id: "c1",
      task_id: "task-c1",
      engine_turn_id: null,
    };
    useMobileStore.setState({
      activeConversationId: "c1",
      conversationsById: { c1: CONVERSATION },
      activeTask: staleTask,
    });

    // 新协议：active_tasks 是完整权威集合，空数组 → 当前会话任务已结束，清空
    const snapshot = {
      projects: [{ project_id: "p1", name: "演示项目", conversations: [CONVERSATION] }],
      messages: [],
      tool_runs: [],
      approvals: [],
      sequence: 20,
      pair: null,
      pairs: [],
      active_task: null,
      active_tasks: [],
    } as unknown as DesktopSnapshot;
    lastInstance().emit({ kind: "event", event: "state.snapshot", sequence: 11, payload: snapshot });
    expect(useMobileStore.getState().activeTask).toBeNull();
  });

  describe("mobileStore V0.3.5 手机语音", () => {
    it("startVoiceCapture 进入 recording 状态并保存 session_id", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({ activeConversationId: "c1" });

      const startPromise = useMobileStore.getState().startVoiceCapture("c1");
      await vi.waitFor(() => expect(lastSentFrame().method).toBe("voice.mobile_ptt_start"));
      const frame = lastSentFrame();
      lastInstance().emit({ kind: "response", id: frame.id, ok: true, result: { session_id: "sess-1" } });
      // 契约：必须返回服务端会话（useVoiceCapture 依赖 result.session_id 才能采集）。
      await expect(startPromise).resolves.toEqual({ session_id: "sess-1" });

      const voice = useMobileStore.getState().voice;
      expect(voice.capture.state).toBe("recording");
      expect(voice.capture.sessionId).toBe("sess-1");
      expect(voice.capture.error).toBeNull();
    });

    it("sendAudioChunk 携带递增 seq", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({
        activeConversationId: "c1",
        voice: {
          ...useMobileStore.getState().voice,
          capture: { state: "recording", sessionId: "sess-1", error: null },
        },
      });

      const p1 = useMobileStore.getState().sendAudioChunk(0, "ZmFrZS0w");
      const p2 = useMobileStore.getState().sendAudioChunk(1, "ZmFrZS0x");

      // FakeWebSocket 不会自动回复，需要为每个 voice.mobile_audio_chunk 请求 emit response。
      const ws = lastInstance();
      ws.sent
        .map((raw) => JSON.parse(raw))
        .filter((frame) => frame.method === "voice.mobile_audio_chunk")
        .forEach((frame) => ws.emit({ kind: "response", id: frame.id, ok: true, result: {} }));

      await Promise.all([p1, p2]);
      const frames = ws.sent
        .map((raw) => JSON.parse(raw))
        .filter((frame) => frame.method === "voice.mobile_audio_chunk");
      expect(frames).toHaveLength(2);
      expect(frames[0].params).toMatchObject({ session_id: "sess-1", seq: 0, data: "ZmFrZS0w" });
      expect(frames[1].params).toMatchObject({ session_id: "sess-1", seq: 1, data: "ZmFrZS0x" });
    });

    it("voice.mobile_transcript 更新 transcript slice", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({
        activeConversationId: "c1",
        voice: {
          ...useMobileStore.getState().voice,
          capture: { state: "recording", sessionId: "sess-1", error: null },
        },
      });

      lastInstance().emit({
        kind: "event",
        event: "voice.mobile_transcript",
        sequence: 11,
        payload: { session_id: "sess-1", text: "partial", is_final: false },
      });
      expect(useMobileStore.getState().voice.transcript).toMatchObject({
        sessionId: "sess-1",
        text: "partial",
        isFinal: false,
      });

      lastInstance().emit({
        kind: "event",
        event: "voice.mobile_transcript",
        sequence: 12,
        payload: { session_id: "sess-1", text: "final text", is_final: true },
      });
      const voice = useMobileStore.getState().voice;
      expect(voice.transcript).toMatchObject({ sessionId: "sess-1", text: "final text", isFinal: true });
      expect(voice.capture.state).toBe("idle");
      expect(voice.capture.sessionId).toBeNull();
    });

    it("voice.mobile_tts_chunk 与 tts_end 缓冲并标记播放状态", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({ activeConversationId: "c1" });

      lastInstance().emit({
        kind: "event",
        event: "voice.mobile_tts_chunk",
        sequence: 11,
        payload: { message_id: "m-tts", seq: 0, mime: "audio/pcm;rate=24000", data: "ZAA=" },
      });
      expect(useMobileStore.getState().voice.ttsChunks["m-tts"]).toHaveLength(1);
      expect(useMobileStore.getState().voice.playback.state).toBe("buffering");

      lastInstance().emit({
        kind: "event",
        event: "voice.mobile_tts_end",
        sequence: 12,
        payload: { message_id: "m-tts" },
      });
      expect(useMobileStore.getState().voice.playback.state).toBe("playing");
      expect(useMobileStore.getState().voice.playback.messageId).toBe("m-tts");
    });
  });

  describe("mobileStore V0.3.5 审批仲裁", () => {
    it("approval.resolved 事件收敛 approvals 并记录 resolved_by/decision", async () => {
      await pairAndBootstrap();
      lastInstance().emit({
        kind: "event",
        event: "approval.requested",
        sequence: 11,
        payload: {
          approval_id: "a1",
          conversation_id: "c1",
          task_id: "t1",
          operation: { tool_kind: "shell", command: "npm test", paths: [], patch_file_count: null, summary: "跑测试" },
          reason: "风险规则",
        },
      });
      expect(useMobileStore.getState().approvals).toHaveLength(1);

      lastInstance().emit({
        kind: "event",
        event: "approval.resolved",
        sequence: 12,
        payload: { approval_id: "a1", decision: "allow", resolved_by: "desktop" },
      });
      const state = useMobileStore.getState();
      expect(state.approvals).toHaveLength(0);
      expect(state.resolvedApprovals).toHaveLength(1);
      expect(state.resolvedApprovals[0]).toMatchObject({
        approval_id: "a1",
        decision: "allow",
        resolved_by: "desktop",
      });
    });

    it("resolveApproval 遇 approval_already_resolved 时按先到者真实结果收敛", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({ activeConversationId: "c1" });
      lastInstance().emit({
        kind: "event",
        event: "approval.requested",
        sequence: 11,
        payload: {
          approval_id: "a2",
          conversation_id: "c1",
          task_id: "t2",
          operation: { tool_kind: "shell", command: "ls", paths: [], patch_file_count: null, summary: "列目录" },
          reason: "需要确认",
        },
      });

      // 本端尝试 allow，但先到者（桌面端）的真实决策是 deny
      const resolvePromise = useMobileStore.getState().resolveApproval("a2", "allow");
      const frame = lastSentFrame();
      expect(frame.method).toBe("approval.resolve");
      // 真实后端文案（application_service.py ApprovalBroker.resolve）：
      // 「审批已由 <resolved_by> 应答（<decision>），不能重复应答」
      lastInstance().emit({
        kind: "response",
        id: frame.id,
        ok: false,
        error: { code: "approval_already_resolved", message: "审批已由 desktop 应答（deny），不能重复应答" },
      });

      await expect(resolvePromise).rejects.toThrow(/不能重复应答/);
      const state = useMobileStore.getState();
      expect(state.approvals).toHaveLength(0);
      expect(state.resolvedApprovals).toHaveLength(1);
      expect(state.resolvedApprovals[0]).toMatchObject({
        approval_id: "a2",
        // 必须记录先到者的真实决策 deny，严禁用本端入参 allow 顶替
        decision: "deny",
        resolved_by: "desktop",
        operation: { tool_kind: "shell", command: "ls" },
        reason: "需要确认",
      });
    });

    it("V0.3.5 already_resolved 时优先消费结构化 details，文案正则仅作后备", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({ activeConversationId: "c1" });
      lastInstance().emit({
        kind: "event",
        event: "approval.requested",
        sequence: 21,
        payload: {
          approval_id: "a3",
          conversation_id: "c1",
          task_id: "t3",
          operation: { tool_kind: "shell", command: "ls", paths: [], patch_file_count: null, summary: "列目录" },
          reason: "需要确认",
        },
      });
      const resolvePromise = useMobileStore.getState().resolveApproval("a3", "allow");
      const frame = lastSentFrame();
      // 契约 §6：error.details={decision, resolved_by}（application_service.py 49c5a39）
      lastInstance().emit({
        kind: "response",
        id: frame.id,
        ok: false,
        error: {
          code: "approval_already_resolved",
          message: "审批已由 desktop 应答（deny），不能重复应答",
          details: { decision: "allow_for_conversation", resolved_by: "desktop" },
        },
      });
      await expect(resolvePromise).rejects.toThrow(/不能重复应答/);
      const state = useMobileStore.getState();
      expect(state.resolvedApprovals[0]).toMatchObject({
        approval_id: "a3",
        // details 结构化字段优先于 message 文案（文案里的 deny 不是真实决策）
        decision: "allow_for_conversation",
        resolved_by: "desktop",
      });
    });

    it("V0.3.5 setApprovalMode 发 project.update_settings 并以真实快照更新本地", async () => {
      await pairAndBootstrap();
      const project = useMobileStore.getState().projects[0];
      expect(project).toBeTruthy();
      const modePromise = useMobileStore
        .getState()
        .setApprovalMode(project.project_id, "full_auto");
      const frame = lastSentFrame();
      expect(frame).toMatchObject({
        method: "project.update_settings",
        params: { project_id: project.project_id, approval_mode: "full_auto" },
      });
      lastInstance().emit({
        kind: "response",
        id: frame.id,
        ok: true,
        result: { project: { project_id: project.project_id, approval_mode: "full_auto" } },
      });
      await modePromise;
      expect(
        useMobileStore.getState().projects.find((item) => item.project_id === project.project_id)
          ?.approval_mode,
      ).toBe("full_auto");
    });

    it("startVoiceCapture 非空闲状态如实拒绝且不发帧", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({
        activeConversationId: "c1",
        voice: {
          ...useMobileStore.getState().voice,
          capture: { state: "recording", sessionId: "sess-1", error: null },
        },
      });

      await expect(useMobileStore.getState().startVoiceCapture("c1")).rejects.toThrow(
        "语音采集正在进行中",
      );
      expect(
        lastInstance()
          .sent.map((raw) => JSON.parse(raw))
          .filter((frame) => frame.method === "voice.mobile_ptt_start"),
      ).toHaveLength(0);
    });

    it("sendAudioChunk 失败时错误写入 capture.error 并如实抛出", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({
        activeConversationId: "c1",
        voice: {
          ...useMobileStore.getState().voice,
          capture: { state: "recording", sessionId: "sess-1", error: null },
        },
      });

      const p = useMobileStore.getState().sendAudioChunk(3, "ZmFrZS0z");
      const ws = lastInstance();
      const frame = ws.sent
        .map((raw) => JSON.parse(raw))
        .find((f) => f.method === "voice.mobile_audio_chunk");
      ws.emit({
        kind: "response",
        id: frame.id,
        ok: false,
        error: { code: "voice_audio_seq_gap", message: "音频分片序号跳号：期望 0，实际 3" },
      });

      await expect(p).rejects.toThrow(/跳号/);
      // 错误必须留在界面上，状态保持 recording，不得伪造复位
      expect(useMobileStore.getState().voice.capture.error).toContain("跳号");
      expect(useMobileStore.getState().voice.capture.state).toBe("recording");
    });

    it("approval.resolved 事件先到时，already_resolved 失败不覆盖真实记录", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({ activeConversationId: "c1" });
      lastInstance().emit({
        kind: "event",
        event: "approval.requested",
        sequence: 11,
        payload: {
          approval_id: "a4",
          conversation_id: "c1",
          task_id: "t4",
          operation: { tool_kind: "shell", command: "ls", paths: [], patch_file_count: null, summary: "列目录" },
          reason: "需要确认",
        },
      });
      // 事件先到：真实决策 deny（桌面端）
      lastInstance().emit({
        kind: "event",
        event: "approval.resolved",
        sequence: 12,
        payload: { approval_id: "a4", decision: "deny", resolved_by: "desktop", conversation_id: "c1" },
      });

      const p = useMobileStore.getState().resolveApproval("a4", "allow");
      const frame = lastSentFrame();
      lastInstance().emit({
        kind: "response",
        id: frame.id,
        ok: false,
        error: { code: "approval_already_resolved", message: "审批已由 desktop 应答（deny），不能重复应答" },
      });
      await expect(p).rejects.toThrow(/不能重复应答/);

      const state = useMobileStore.getState();
      expect(state.approvals).toHaveLength(0);
      const resolved = state.resolvedApprovals.find((item) => item.approval_id === "a4");
      // 事件写入的真实记录不得被本端失败路径覆盖
      expect(resolved).toMatchObject({ decision: "deny", resolved_by: "desktop" });
    });

    it("approval.resolved 事件缺少 conversation_id 时回退到当前会话", async () => {
      await pairAndBootstrap();
      useMobileStore.setState({ activeConversationId: "c1" });
      lastInstance().emit({
        kind: "event",
        event: "approval.requested",
        sequence: 11,
        payload: {
          approval_id: "a3",
          conversation_id: "c1",
          task_id: "t3",
          operation: { tool_kind: "file_delete", command: null, paths: ["a.txt"], patch_file_count: null, summary: "删文件" },
          reason: "高风险",
        },
      });

      lastInstance().emit({
        kind: "event",
        event: "approval.resolved",
        sequence: 12,
        payload: { approval_id: "a3", decision: "deny", resolved_by: "mobile" },
      });

      expect(useMobileStore.getState().resolvedApprovals[0]?.conversation_id).toBe("c1");
    });
  });
});
