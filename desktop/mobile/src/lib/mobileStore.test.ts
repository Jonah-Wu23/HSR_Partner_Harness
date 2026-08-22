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
    pair: null,
    activeTask: null,
    lastSequence: 0,
    bootstrapped: false,
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
});
