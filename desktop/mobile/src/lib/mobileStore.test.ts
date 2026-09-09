import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationRecord, DesktopSnapshot, Message, PairRecord } from "@shared/contracts/protocol";
import {
  appendTtsChunk,
  mobileWsClient,
  resetVoiceTerminalStateForTests,
  TTS_MAX_BUFFERED_PCM_BYTES,
  useMobileStore,
  type MobileTtsChunk,
} from "./mobileStore";
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
    const frame = JSON.parse(data) as { id: string; method: string };
    if (frame.method === "remote.claim_control" || frame.method === "remote.release_control") {
      queueMicrotask(() => this.emit({
        kind: "response", id: frame.id, ok: true, result: { active: true },
      }));
    }
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
    queue_items: [],
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
  resetVoiceTerminalStateForTests();
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
    queueItems: [],
    approvals: [],
    resolvedApprovals: [],
    pair: null,
    activeTask: null,
    activeTasks: [],
    turnsByConversation: {},
    summaries: [],
    memories: [],
    remoteControl: null,
    streamId: null,
    lastSequence: 0,
    bootstrapped: false,
    powerStatus: null,
    voice: {
      capture: { state: "idle", sessionId: null, error: null },
      transcript: null,
      playback: { messageId: null, state: "idle", error: null, errorCode: null },
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

describe("mobileStore V0.3.7 电源状态", () => {
  const atRiskPayload = {
    supported: true,
    platform: "windows",
    plan_name: "平衡",
    ac_sleep_timeout_seconds: 600,
    dc_sleep_timeout_seconds: 1800,
    remote_serve_enabled: true,
    threshold_seconds: 900,
    at_risk: true,
    reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
    checked_at: "2026-09-02T10:00:00",
  };

  it("power.status_changed 事件原样写入电源状态切片", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      sequence: 11,
      payload: atRiskPayload,
    });
    // 事件载荷与 power.get_status result 完全同形（冻结 §2.1），原样存储不重算。
    expect(useMobileStore.getState().powerStatus).toEqual(atRiskPayload);
  });

  it("旧序号的电源事件被去重，不覆盖状态", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      sequence: 11,
      payload: atRiskPayload,
    });
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      sequence: 8,
      payload: { ...atRiskPayload, at_risk: false, reason: "旧数据" },
    });
    expect(useMobileStore.getState().powerStatus).toEqual(atRiskPayload);
  });

  it("形状不符的电源事件不入状态并保留日志", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      sequence: 11,
      payload: { broken: true },
    });
    expect(useMobileStore.getState().powerStatus).toBeNull();
    expect(warnSpy).toHaveBeenCalled();
  });

  it("disconnect 清空电源状态", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      sequence: 11,
      payload: atRiskPayload,
    });
    expect(useMobileStore.getState().powerStatus).toEqual(atRiskPayload);

    await useMobileStore.getState().disconnect();
    expect(useMobileStore.getState().powerStatus).toBeNull();
  });

  it("连接代次（stream）变化时清空旧电源状态，等新 stream 重新推送", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      sequence: 11,
      payload: atRiskPayload,
    });
    expect(useMobileStore.getState().powerStatus).toEqual(atRiskPayload);

    // 旧 stream 的电源状态在代次切换时立即作废；serve 启动按冻结 §2.1 会重新 emit。
    lastInstance().emit({
      kind: "event",
      event: "connection.status",
      stream_id: "stream-next",
      sequence: 0,
      payload: { status: "connected" },
    });
    expect(useMobileStore.getState().powerStatus).toBeNull();

    await vi.waitFor(() => {
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
      expect(useMobileStore.getState().bootstrapped).toBe(true);
    });
  });

  it("新 stream 的电源事件属于桌面端新一轮会话，重置后照常入状态", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      sequence: 11,
      payload: atRiskPayload,
    });
    const freshPayload = {
      ...atRiskPayload,
      plan_name: "高性能",
      reason: "DC 睡眠超时 300 秒低于阈值 900 秒",
      checked_at: "2026-09-02T11:00:00",
    };
    lastInstance().emit({
      kind: "event",
      event: "power.status_changed",
      stream_id: "stream-next",
      sequence: 0,
      payload: freshPayload,
    });
    // 旧值被代次重置清掉，随后新 stream 的最新事实照常写入，不残留旧计划名。
    expect(useMobileStore.getState().powerStatus).toEqual(freshPayload);
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
    queue_items: [],
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
    queue_items: [],
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
      // V0.3.8：分片记录解码后 PCM 字节数（"ZAA=" → 2 字节），供容量核算。
      expect(useMobileStore.getState().voice.ttsChunks["m-tts"]![0]).toMatchObject({
        seq: 0,
        bytes: 2,
      });
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

  describe("mobileStore V0.3.8 TTS 缓冲上限与播放失败", () => {
    function emitTtsChunk(sequence: number, payload: { seq: number; data: string }): void {
      lastInstance().emit({
        kind: "event",
        event: "voice.mobile_tts_chunk",
        sequence,
        payload: { message_id: "m-cap", mime: "audio/pcm;rate=24000", ...payload },
      });
    }

    /** data 长度 = bytes*4/3（bytes 可被 3 整除时无 padding），base64PcmByteLength 恰好还原 bytes。 */
    function chunkData(bytes: number): string {
      return "A".repeat((bytes * 4) / 3);
    }

    it("缓冲超上限时整条播放进入 failed（pcm_overflow），不丢旧片段后继续播放", async () => {
      await pairAndBootstrap();
      const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const cap = TTS_MAX_BUFFERED_PCM_BYTES;

      // 两片各 cap/2：都在限内。
      emitTtsChunk(11, { seq: 0, data: chunkData(cap / 2) });
      emitTtsChunk(12, { seq: 1, data: chunkData(cap / 2) });
      expect(useMobileStore.getState().voice.ttsChunks["m-cap"]).toHaveLength(2);

      // 第三片使总量超过上限：整条失败、缓冲清空、真实失败码可见。
      emitTtsChunk(13, { seq: 2, data: chunkData(48) });
      const voice = useMobileStore.getState().voice;
      expect(voice.playback).toMatchObject({
        messageId: "m-cap",
        state: "failed",
        errorCode: "pcm_overflow",
      });
      expect(voice.playback.error).toContain("超过上限");
      expect(voice.ttsChunks["m-cap"]).toBeUndefined();
      expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("pcm_overflow"));
      errorSpy.mockRestore();

      // 迟到分片与迟到 end 都不得复活播放。
      emitTtsChunk(14, { seq: 3, data: "ZAA=" });
      expect(useMobileStore.getState().voice.playback.state).toBe("failed");
      expect(useMobileStore.getState().voice.ttsChunks["m-cap"]).toBeUndefined();
      lastInstance().emit({
        kind: "event",
        event: "voice.mobile_tts_end",
        sequence: 15,
        payload: { message_id: "m-cap" },
      });
      expect(useMobileStore.getState().voice.playback.state).toBe("failed");
    });

    it("appendTtsChunk：去重、按 seq 排序、超限返回 overflow 且清空缓冲", () => {
      const mk = (seq: number, bytes: number): MobileTtsChunk => ({
        seq,
        mime: "audio/pcm;rate=24000",
        data: "",
        bytes,
      });
      // 乱序到达按 seq 排序。
      const sorted = appendTtsChunk([mk(1, 10)], mk(0, 10), 100);
      expect(sorted.chunks.map((item) => item.seq)).toEqual([0, 1]);
      expect(sorted.overflow).toBe(false);
      // 重复 seq 去重，不重复计入容量。
      const deduped = appendTtsChunk(sorted.chunks, mk(1, 10), 100);
      expect(deduped.chunks).toHaveLength(2);
      expect(deduped.overflow).toBe(false);
      // 超限：不再丢旧片段后继续，而是整条失败（chunks 清空）。
      const overflow = appendTtsChunk([mk(0, 60), mk(1, 60)], mk(2, 60), 100);
      expect(overflow.chunks).toEqual([]);
      expect(overflow.overflow).toBe(true);
      // 单条即超限同样判定 overflow。
      const single = appendTtsChunk([mk(0, 60)], mk(1, 200), 100);
      expect(single.chunks).toEqual([]);
      expect(single.overflow).toBe(true);
    });

    it("releaseTtsChunksUpTo 释放已移交引擎的分片，空条目随删", async () => {
      await pairAndBootstrap();
      emitTtsChunk(11, { seq: 0, data: "ZAA=" });
      emitTtsChunk(12, { seq: 1, data: "ZAA=" });

      useMobileStore.getState().releaseTtsChunksUpTo("m-cap", 0);
      expect(
        useMobileStore.getState().voice.ttsChunks["m-cap"]!.map((item) => item.seq),
      ).toEqual([1]);
      useMobileStore.getState().releaseTtsChunksUpTo("m-cap", 1);
      expect(useMobileStore.getState().voice.ttsChunks["m-cap"]).toBeUndefined();
    });

    it("failVoicePlayback 如实置 failed 并保留错误；迟到的 end 不得掩盖失败终态", async () => {
      await pairAndBootstrap();
      emitTtsChunk(11, { seq: 0, data: "ZAA=" });

      useMobileStore
        .getState()
        .failVoicePlayback("m-cap", "播放结束信号超时：300 秒未收到 voice.mobile_tts_end，已中止播放");
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: "m-cap",
        state: "failed",
        error: expect.stringContaining("voice.mobile_tts_end"),
      });
      // 失败消息的分片一并清理，不再驻留。
      expect(useMobileStore.getState().voice.ttsChunks["m-cap"]).toBeUndefined();

      lastInstance().emit({
        kind: "event",
        event: "voice.mobile_tts_end",
        sequence: 12,
        payload: { message_id: "m-cap" },
      });
      expect(useMobileStore.getState().voice.playback.state).toBe("failed");
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

  describe("mobileStore V0.3.8 T5 队列接入", () => {
    function queueItem(overrides: Partial<Record<string, unknown>> = {}) {
      return {
        queue_item_id: "q-1",
        account_id: "acc",
        conversation_id: "c1",
        target: "character",
        text: "排队中的消息",
        intent: "followup",
        position: 0,
        status: "queued",
        created_at: "2026-09-05T00:00:00+00:00",
        source_message_id: null,
        ...overrides,
      };
    }

    async function openConv() {
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
          queue_items: [],
          turns: [],
          active_task: null,
        },
      });
      await openPromise;
    }

    it("queue.changed 更新活跃会话的排队项（仅保留 queued）", async () => {
      await openConv();
      const ws = lastInstance();
      ws.emit({
        kind: "event",
        event: "queue.changed",
        sequence: 12,
        payload: {
          conversation_id: "c1",
          items: [
            queueItem(),
            queueItem({ queue_item_id: "q-2", position: 1, status: "processing" }),
          ],
        },
      });
      const items = useMobileStore.getState().queueItems;
      expect(items).toHaveLength(1);
      expect(items[0].queue_item_id).toBe("q-1");
      expect(items[0].text).toBe("排队中的消息");
    });

    it("其他会话的 queue.changed 不覆盖当前会话排队项", async () => {
      await openConv();
      useMobileStore.setState({
        queueItems: [queueItem()] as never,
      });
      lastInstance().emit({
        kind: "event",
        event: "queue.changed",
        sequence: 12,
        payload: { conversation_id: "c2", items: [] },
      });
      expect(useMobileStore.getState().queueItems).toHaveLength(1);
    });

    it("chat.submit 排队回执立即落地本地排队项", async () => {
      await openConv();
      const submitPromise = useMobileStore.getState().submitMessage("忙时新消息");
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("chat.submit");
      });
      const frame = lastSentFrame();
      lastInstance().emit({
        kind: "response",
        id: frame.id,
        ok: true,
        result: { queued: true, queue_item: queueItem({ text: "忙时新消息" }) },
      });
      await submitPromise;
      const items = useMobileStore.getState().queueItems;
      expect(items).toHaveLength(1);
      expect(items[0].text).toBe("忙时新消息");
    });

    it("withdraw/prioritize/edit 三命令真实下发", async () => {
      await openConv();
      const respond = () => {
        const cmdFrame = lastSentFrame();
        lastInstance().emit({ kind: "response", id: cmdFrame.id, ok: true, result: {} });
        return cmdFrame;
      };
      const withdrawPromise = useMobileStore.getState().withdrawQueueItem("q-1");
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("queue.withdraw");
      });
      const withdrawFrame = respond();
      expect(withdrawFrame.params).toMatchObject({ queue_item_id: "q-1" });
      await withdrawPromise;

      const prioritizePromise = useMobileStore.getState().prioritizeQueueItem("q-2");
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("queue.prioritize");
      });
      const prioritizeFrame = respond();
      expect(prioritizeFrame.params).toMatchObject({ queue_item_id: "q-2" });
      await prioritizePromise;

      const editPromise = useMobileStore.getState().editQueueItem("q-3", "改后的文本");
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("queue.edit");
      });
      const editFrame = respond();
      expect(editFrame.params).toMatchObject({ queue_item_id: "q-3", text: "改后的文本" });
      await editPromise;
    });
  });

  describe("mobileStore V0.3.8 播放防循环与配对互斥 (D1/D2/D4)", () => {
    it("stopVoicePlayback 只在当前消息匹配时置 idle，不冲掉已到达的新消息", async () => {
      await pairAndBootstrap();

      // 设置当前正在播 msg-1
      useMobileStore.setState({
        voice: {
          ...useMobileStore.getState().voice,
          playback: { messageId: "msg-1", state: "playing", error: null },
        },
      });

      const stopPromise = useMobileStore.getState().stopVoicePlayback("msg-1");
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: "msg-1",
        state: "stopping",
      });

      // 在等待 stop 响应期间，msg-2 的 chunk 到达，状态切到了 msg-2
      useMobileStore.setState({
        voice: {
          ...useMobileStore.getState().voice,
          playback: { messageId: "msg-2", state: "buffering", error: null },
        },
      });

      // 响应旧消息 msg-1 的 stop
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("voice.mobile_tts_stop");
      });
      const stopFrame = lastSentFrame();
      expect(stopFrame.params).toMatchObject({ message_id: "msg-1" });
      lastInstance().emit({ kind: "response", id: stopFrame.id, ok: true, result: { stopped: true } });
      await stopPromise;

      // 关键断言：msg-1 的 stop 成功回执绝不能把 msg-2 冲成 idle/null！
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: "msg-2",
        state: "buffering",
      });
    });

    it("已停止的消息分片到达时不复活为 buffering/playing", async () => {
      await pairAndBootstrap();

      useMobileStore.setState({
        voice: {
          ...useMobileStore.getState().voice,
          playback: { messageId: "msg-stopped", state: "playing", error: null },
        },
      });

      const stopPromise = useMobileStore.getState().stopVoicePlayback("msg-stopped");
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("voice.mobile_tts_stop");
      });
      const stopFrame = lastSentFrame();
      lastInstance().emit({ kind: "response", id: stopFrame.id, ok: true, result: { stopped: true } });
      await stopPromise;

      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: null,
        state: "idle",
      });

      // 迟到的已停止分片到达
      lastInstance().emit({
        kind: "event",
        sequence: 101,
        stream_id: "stream-current",
        event: "voice.mobile_tts_chunk",
        payload: { message_id: "msg-stopped", seq: 5, data: "AAAA" },
      });

      // 依然是 idle，绝不复活成 buffering
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: null,
        state: "idle",
      });
    });

    it("D4：auth_failed 且 socket 物理连接 OPEN 时，pairDevice 立即放行并发出 remote.pair", async () => {
      // 先建立物理连接并打开
      mobileWsClient.connect();
      lastInstance().open();

      // 模拟先前的鉴权失败状态，但 socket 物理连接保持 OPEN
      useMobileStore.setState({ connection: "auth_failed" });
      // @ts-expect-error test backdoor
      mobileWsClient.state = "auth_failed";

      const pairPromise = useMobileStore.getState().pairDevice("112233", "测试设备");
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("remote.pair");
      });
      const pairFrame = lastSentFrame();
      expect(pairFrame.params).toMatchObject({ code: "112233", device_name: "测试设备" });
      lastInstance().emit({ kind: "response", id: pairFrame.id, ok: true, result: { token: "tok-new" } });

      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("app.bootstrap");
      });
      const bootstrapFrame = lastSentFrame();
      lastInstance().emit({
        kind: "response",
        id: bootstrapFrame.id,
        ok: true,
        result: snapshotResult(1),
      });

      await pairPromise;
      expect(useMobileStore.getState().deviceName).toBe("测试设备");
    });

    it("新角色回复出现（message.created）立即打断正在播放的旧语音", async () => {
      await pairAndBootstrap();

      useMobileStore.setState({
        activeConversationId: "conv-preempt",
        voice: {
          ...useMobileStore.getState().voice,
          playback: { messageId: "msg-old", state: "playing", error: null },
          ttsChunks: { "msg-old": [{ seq: 0, mime: "audio/pcm;rate=24000", data: "AAAA", bytes: 3 }] },
        },
      });

      lastInstance().emit({
        kind: "event",
        sequence: 11,
        stream_id: "stream-current",
        event: "message.created",
        payload: {
          conversation_id: "conv-preempt",
          tts_ready: true,
          message: {
            message_id: "msg-new",
            conversation_id: "conv-preempt",
            source: "character",
            text: "这是新的回答内容",
          },
        },
      });

      // 旧语音应立即被打断并复位为 idle，本地旧分片被清理
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: null,
        state: "idle",
      });
      expect(useMobileStore.getState().voice.ttsChunks["msg-old"]).toBeUndefined();

      // 服务端应收到停止旧消息的请求
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("voice.mobile_tts_stop");
      });
      expect(lastSentFrame().params).toMatchObject({ message_id: "msg-old" });

      // 新消息的语音分片到达，直接进入播放
      lastInstance().emit({
        kind: "event",
        sequence: 12,
        stream_id: "stream-current",
        event: "voice.mobile_tts_chunk",
        payload: { message_id: "msg-new", seq: 0, data: "BBBB" },
      });

      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: "msg-new",
        state: "buffering",
      });
    });

    it("新语音分片（voice.mobile_tts_chunk）到达时直接抢占打断正在播放的旧语音", async () => {
      await pairAndBootstrap();

      useMobileStore.setState({
        activeConversationId: "conv-preempt",
        voice: {
          ...useMobileStore.getState().voice,
          playback: { messageId: "msg-old-2", state: "playing", error: null },
          ttsChunks: { "msg-old-2": [{ seq: 0, mime: "audio/pcm;rate=24000", data: "AAAA", bytes: 3 }] },
        },
      });

      lastInstance().emit({
        kind: "event",
        sequence: 11,
        stream_id: "stream-current",
        event: "voice.mobile_tts_chunk",
        payload: { message_id: "msg-new-2", seq: 0, data: "CCCC" },
      });

      // 旧语音被抢占打断，新语音立即成为 active
      expect(useMobileStore.getState().voice.playback).toMatchObject({
        messageId: "msg-new-2",
        state: "buffering",
      });
      expect(useMobileStore.getState().voice.ttsChunks["msg-old-2"]).toBeUndefined();

      // 服务端应收到停止旧消息的请求
      await vi.waitFor(() => {
        expect(lastSentFrame().method).toBe("voice.mobile_tts_stop");
      });
      expect(lastSentFrame().params).toMatchObject({ message_id: "msg-old-2" });
    });
  });

describe("mobileStore V0.3.9 契约消费（摘要/记忆/租约/回合/审批终态）", () => {
  it("快照消费全量 active_tasks、回合、摘要、记忆与租约；缺字段即空/ null", async () => {
    const pairPromise = useMobileStore.getState().pairDevice("654321", "我的小米");
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("remote.pair"));
    const pairFrame = lastSentFrame();
    lastInstance().emit({ kind: "response", id: pairFrame.id, ok: true, result: { token: "tok-9" } });
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("app.bootstrap"));
    const bootstrapFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: bootstrapFrame.id,
      ok: true,
      result: {
        ...snapshotResult(10),
        active_tasks: [
          { project_id: "p1", conversation_id: "c1", task_id: "task-1", engine_turn_id: null },
        ],
        turns: [
          {
            turn_id: "turn-1",
            account_id: "acc",
            project_id: "p1",
            conversation_id: "c1",
            target: "character",
            source_message_id: "m1",
            status: "running",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        summaries: [
          {
            summary_id: "s1",
            conversation_id: "c1",
            status: "completed",
            covers_from_message_id: null,
            covers_to_message_id: null,
            covers_message_count: 80,
            content: { text: "摘要" },
            provider: "deepseek",
            model: "deepseek-chat",
            error_code: null,
            error: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        memories: [
          {
            memory_id: "mem-1",
            scope: {
              account_id: "acc",
              project_id: "p1",
              pair_id: "pair-default",
              character_ref: "builtin:phainon",
              assistant_identity: "ancient_machine",
            },
            content: { text: "喜欢安静的训练场" },
            status: "active",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
        remote_control: {
          state: "held",
          device_key: "device-a",
          expires_at: "2026-01-01T00:00:45Z",
          grace_expires_at: null,
          reason: null,
        },
      },
    });
    await pairPromise;

    const state = useMobileStore.getState();
    expect(state.activeTasks).toHaveLength(1);
    expect(state.turnsByConversation["c1"]).toHaveLength(1);
    expect(state.summaries[0]?.model).toBe("deepseek-chat");
    expect(state.memories[0]?.scope.assistant_identity).toBe("ancient_machine");
    expect(state.remoteControl).toEqual({
      state: "held",
      device_key: "device-a",
      expires_at: "2026-01-01T00:00:45Z",
      grace_expires_at: null,
      reason: null,
    });
  });

  it("turn.started/turn.status_changed 按 conversation_id 存放，不退化为单全局任务", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "turn.started",
      sequence: 11,
      stream_id: "stream-current",
      payload: {
        turn: {
          turn_id: "turn-1",
          account_id: "acc",
          project_id: "p1",
          conversation_id: "c1",
          target: "character",
          source_message_id: "m1",
          status: "running",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      },
    });
    lastInstance().emit({
      kind: "event",
      event: "turn.status_changed",
      sequence: 12,
      stream_id: "stream-current",
      payload: {
        turn: {
          turn_id: "turn-1",
          account_id: "acc",
          project_id: "p1",
          conversation_id: "c1",
          target: "character",
          source_message_id: "m1",
          status: "completed",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:01:00Z",
        },
      },
    });

    const turns = useMobileStore.getState().turnsByConversation["c1"];
    expect(turns).toHaveLength(1);
    expect(turns[0]?.status).toBe("completed");
  });

  it("summary.failed 保留原始 error_code，不生成空摘要；memory.deleted 标记 deleted", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "summary.failed",
      sequence: 11,
      stream_id: "stream-current",
      payload: {
        conversation_id: "c1",
        summary_id: "s1",
        status: "failed",
        error_code: "summary_timeout",
        error: "provider timeout",
      },
    });
    const failed = useMobileStore.getState().summaries[0];
    expect(failed?.status).toBe("failed");
    expect(failed?.error_code).toBe("summary_timeout");
    expect(failed?.error).toBe("provider timeout");
    expect(failed?.content).toBeNull();

    lastInstance().emit({
      kind: "event",
      event: "memory.updated",
      sequence: 12,
      stream_id: "stream-current",
      payload: {
        memory: {
          memory_id: "mem-1",
          scope: {
            account_id: "acc",
            project_id: "p1",
            pair_id: "pair-default",
            character_ref: "builtin:phainon",
            assistant_identity: "ancient_machine",
          },
          content: { text: "记忆" },
          status: "active",
          updated_at: "2026-01-01T00:00:00Z",
        },
      },
    });
    lastInstance().emit({
      kind: "event",
      event: "memory.deleted",
      sequence: 13,
      stream_id: "stream-current",
      payload: { memory_id: "mem-1" },
    });
    expect(useMobileStore.getState().memories[0]?.status).toBe("deleted");
  });

  it("remote.control_changed 非法载荷保持 null；remote.control_status 只读查询写入租约", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "remote.control_changed",
      sequence: 11,
      stream_id: "stream-current",
      payload: { state: "not-a-state" },
    });
    expect(useMobileStore.getState().remoteControl).toBeNull();

    const query = useMobileStore.getState().refreshRemoteControl();
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("remote.control_status"));
    const frame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: frame.id,
      ok: true,
      result: {
        remote_control: {
          state: "grace",
          device_key: "device-a",
          expires_at: "2026-01-01T00:00:45Z",
          grace_expires_at: "2026-01-01T00:01:00Z",
          reason: "disconnected",
        },
      },
    });
    await query;
    expect(useMobileStore.getState().remoteControl?.state).toBe("grace");
  });

  it("voice.playback_interrupted 后迟到分片不得复活播放", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "voice.mobile_tts_chunk",
      sequence: 11,
      stream_id: "stream-current",
      payload: { message_id: "m-int", mime: "audio/pcm;rate=24000", seq: 0, data: "ZAA=" },
    });
    expect(useMobileStore.getState().voice.playback.messageId).toBe("m-int");

    lastInstance().emit({
      kind: "event",
      event: "voice.playback_interrupted",
      sequence: 12,
      stream_id: "stream-current",
      payload: { conversation_id: "c1", message_id: "m-int", reason: "user_submit" },
    });
    lastInstance().emit({
      kind: "event",
      event: "voice.mobile_tts_chunk",
      sequence: 13,
      stream_id: "stream-current",
      payload: { message_id: "m-int", mime: "audio/pcm;rate=24000", seq: 1, data: "ZAA=" },
    });
    const voice = useMobileStore.getState().voice;
    expect(voice.ttsChunks["m-int"]).toBeUndefined();
    expect(voice.playback.messageId).not.toBe("m-int");
  });

  it("approval.resolved 超时终态保留 timeout/system/error_code 与 resolved_at", async () => {
    await pairAndBootstrap();
    lastInstance().emit({
      kind: "event",
      event: "approval.requested",
      sequence: 11,
      stream_id: "stream-current",
      payload: {
        approval_id: "a1",
        conversation_id: "c1",
        task_id: "t1",
        operation: {
          tool_kind: "shell",
          command: "ls",
          paths: [],
          patch_file_count: null,
          summary: "列出目录",
        },
        reason: "需要确认",
      },
    });
    expect(useMobileStore.getState().approvals).toHaveLength(1);

    lastInstance().emit({
      kind: "event",
      event: "approval.resolved",
      sequence: 12,
      stream_id: "stream-current",
      payload: {
        approval_id: "a1",
        conversation_id: "c1",
        task_id: "t1",
        decision: "timeout",
        resolved_by: "system",
        actor: "system",
        reason: "等待审批超时",
        resolved_at: "2026-01-01T00:00:00Z",
        error_code: "approval_timeout",
      },
    });

    const state = useMobileStore.getState();
    expect(state.approvals).toHaveLength(0);
    expect(state.resolvedApprovals[0]).toMatchObject({
      approval_id: "a1",
      decision: "timeout",
      resolved_by: "system",
      error_code: "approval_timeout",
      resolved_at: "2026-01-01T00:00:00Z",
    });
  });

  it("summary.get / memory.list 只读查询写入结果；响应缺数组时保持现状", async () => {
    await pairAndBootstrap();
    const summaryQuery = useMobileStore.getState().loadSummaries("c1");
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("summary.get"));
    const summaryFrame = lastSentFrame();
    lastInstance().emit({
      kind: "response",
      id: summaryFrame.id,
      ok: true,
      result: {
        summaries: [
          {
            summary_id: "s9",
            conversation_id: "c1",
            status: "completed",
            covers_from_message_id: "m1",
            covers_to_message_id: "m80",
            covers_message_count: 80,
            content: { text: "摘要内容" },
            provider: "deepseek",
            model: "deepseek-chat",
            error_code: null,
            error: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
      },
    });
    await summaryQuery;
    expect(useMobileStore.getState().summaries[0]?.summary_id).toBe("s9");

    const memoryQuery = useMobileStore.getState().loadMemories("c1");
    await vi.waitFor(() => expect(lastSentFrame().method).toBe("memory.list"));
    const memoryFrame = lastSentFrame();
    lastInstance().emit({ kind: "response", id: memoryFrame.id, ok: true, result: {} });
    await memoryQuery;
    // 缺数组时不合成空列表，也不清空既有结果。
    expect(useMobileStore.getState().memories).toEqual([]);
    expect(useMobileStore.getState().summaries[0]?.summary_id).toBe("s9");
  });
});
