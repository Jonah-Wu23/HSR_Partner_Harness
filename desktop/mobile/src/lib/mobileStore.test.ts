import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ActiveTask,
  ApprovalResolvedPayload,
  ConversationOpenResult,
  ConversationRecord,
  DesktopSnapshot,
  Message,
  PairRecord,
  PendingApproval,
  PowerStatusPayload,
  ProjectRecord,
  QueueItem,
} from "@shared/contracts/protocol";
import {
  FakeWebSocket,
  installFakeWebSocket,
  latestSocket,
  type SentFrame,
} from "../test/fakeWebSocket";
import {
  appendTtsChunk,
  mobileWsClient,
  TTS_MAX_BUFFERED_PCM_BYTES,
  useMobileStore,
  type MobileTtsChunk,
} from "./mobileStore";
import { getStoredToken } from "./wsClient";

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

const PROJECT: Omit<ProjectRecord, "conversations"> = {
  project_id: "p1",
  name: "演示项目",
  root_path: "D:/demo",
  approval_mode: "request_approval",
  reasoning_effort: "medium",
  archived: false,
  created_at: null,
  last_opened_at: null,
  path_available: true,
};

const PAIR: PairRecord = {
  pair_id: "pair-default",
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

const APPROVAL: PendingApproval = {
  approval_id: "a1",
  conversation_id: "c1",
  task_id: "t1",
  operation: { tool_kind: "shell", command: "ls", paths: [], patch_file_count: null, summary: "列出目录" },
  reason: "需要确认",
};

const POWER_STATUS: PowerStatusPayload = {
  supported: true,
  platform: "windows",
  plan_name: "平衡",
  ac_sleep_timeout_seconds: 0,
  dc_sleep_timeout_seconds: 0,
  remote_serve_enabled: true,
  threshold_seconds: 900,
  at_risk: false,
  reason: "",
  checked_at: "2026-09-02T09:00:00",
  warnings: [],
};

function activeTask(conversationId: string, taskId: string): ActiveTask {
  return { project_id: "p1", conversation_id: conversationId, task_id: taskId, engine_turn_id: null };
}

/** app.bootstrap 快照；手机端不读取的账号、语音等字段从略。 */
function snapshotResult(sequence: number): DesktopSnapshot {
  return {
    projects: [{ ...PROJECT, conversations: [CONVERSATION] }],
    current_conversation_id: "",
    messages: [],
    tool_runs: [],
    queue_items: [],
    approvals: [],
    active_task: null,
    active_tasks: [],
    remote_control: {
      state: "free",
      device_key: null,
      expires_at: null,
      grace_expires_at: null,
      reason: null,
    },
    sequence,
    stream_id: "stream-current",
  } as unknown as DesktopSnapshot;
}

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

function message(overrides: Partial<Message> = {}): Message {
  return {
    message_id: "m1",
    conversation_id: "c1",
    pair_id: "pair-default",
    engine_turn_id: null,
    source: "character",
    kind: "character.speech",
    text: "正文",
    payload: {},
    tts_eligible: true,
    created_at: "2026-08-22T00:00:00Z",
    timeline_order: 1,
    ...overrides,
  };
}

/** 等客户端在当前连接上发出第 count 个该方法的请求，返回该请求帧。 */
function sentRequest(method: string, count = 1): Promise<SentFrame> {
  return vi.waitFor(() => {
    const frame = latestSocket().sentFrames(method)[count - 1];
    if (!frame) throw new Error(`客户端尚未发出第 ${count} 个 ${method}`);
    return frame;
  });
}

function emitEvent(event: string, sequence: number, payload: object, streamId = "stream-current"): void {
  latestSocket().emit({ kind: "event", event, sequence, stream_id: streamId, payload });
}

/** 只发给手机的事件（朗读分片与结束、合成失败、转写）不带序号。 */
function emitRemoteOnly(event: string, payload: object): void {
  latestSocket().emit({ kind: "event", event, payload });
}

function ttsChunk(messageId: string, seq = 0, data = "ZAA="): void {
  emitRemoteOnly("voice.mobile_tts_chunk", {
    conversation_id: "c1",
    message_id: messageId,
    seq,
    mime: "audio/pcm;rate=24000",
    data,
  });
}

function ttsEnd(messageId: string): void {
  emitRemoteOnly("voice.mobile_tts_end", { conversation_id: "c1", message_id: messageId });
}

/** 走通配对与首次同步；默认快照的序号为 10。 */
async function pairAndBootstrap(snapshot: DesktopSnapshot = snapshotResult(10)): Promise<void> {
  const pairing = useMobileStore.getState().pairDevice("654321", "我的小米");
  // 配对总在新连接上进行，握手完成后才发 remote.pair。
  latestSocket().open();
  latestSocket().respond(await sentRequest("remote.pair"), { token: "tok-9" });
  latestSocket().respond(await sentRequest("app.bootstrap"), snapshot);
  await pairing;
}

/** 打开聊天 c1 并回放装载结果。 */
async function openConversation(result: ConversationOpenResult = openResult()): Promise<void> {
  const opening = useMobileStore.getState().openConversation("c1");
  latestSocket().respond(await sentRequest("conversation.open"), result);
  await opening;
}

beforeEach(async () => {
  installFakeWebSocket();
  // 同步流程里的控制声明、电源状态拉取与解绑时的控制释放按真实结果自动应答。
  FakeWebSocket.autoResults.set("remote.claim_control", { claimed: true, active_controllers: 1 });
  FakeWebSocket.autoResults.set("power.get_status", POWER_STATUS);
  FakeWebSocket.autoResults.set("remote.release_control", { released: true, active_controllers: 0 });
  window.localStorage.clear();
  // disconnect 把会话级状态（含朗读终态集合与聊天缓存）复位到初值。
  await useMobileStore.getState().disconnect();
  useMobileStore.getState().start();
  mobileWsClient.connect();
  latestSocket().open();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("mobileStore 配对与同步", () => {
  it("配对成功后保存凭据，按 bootstrap 快照建立会话索引并拉取电源状态", async () => {
    await pairAndBootstrap();
    expect(getStoredToken()).toBe("tok-9");
    const state = useMobileStore.getState();
    expect(state.deviceName).toBe("我的小米");
    expect(state.bootstrapped).toBe(true);
    expect(state.projects).toHaveLength(1);
    expect(state.conversationsById.c1?.title).toBe("测试聊天");
    expect(state.lastSequence).toBe(10);
    await vi.waitFor(() => expect(useMobileStore.getState().powerStatus).toEqual(POWER_STATUS));
  });

  it("bootstrap 快照写入全账号活动任务与远程控制租约", async () => {
    const task = activeTask("c1", "task-1");
    const lease = {
      state: "held",
      device_key: "device-a",
      expires_at: "2026-01-01T00:00:45Z",
      grace_expires_at: null,
      reason: "claimed",
    } as const;
    await pairAndBootstrap({ ...snapshotResult(10), active_tasks: [task], remote_control: lease });

    expect(useMobileStore.getState()).toMatchObject({ activeTasks: [task], remoteControl: lease });
  });
});

describe("mobileStore 事件序号与连接代次", () => {
  it("旧序号事件被去重，会话变更按序合并", async () => {
    await pairAndBootstrap();
    emitEvent("conversation.changed", 11, { conversation: { ...CONVERSATION, title: "改名后" } });
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("改名后");

    // 同一序号再次投递时换了标题，不再合并。
    emitEvent("conversation.changed", 11, { conversation: { ...CONVERSATION, title: "过期标题" } });
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("改名后");
  });

  it("事件序号出现缺口时重新 bootstrap，缺口事件本身不合并", async () => {
    await pairAndBootstrap();
    emitEvent("conversation.changed", 15, { conversation: { ...CONVERSATION, title: "缺口后标题" } });

    const bootstrapFrame = await sentRequest("app.bootstrap", 2);
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("测试聊天");
    latestSocket().respond(bootstrapFrame, snapshotResult(15));
    await vi.waitFor(() => expect(useMobileStore.getState().lastSequence).toBe(15));
  });

  it("bootstrap 等待期间收到的新事件在快照之后按序重放", async () => {
    await pairAndBootstrap();
    emitEvent("conversation.changed", 12, { conversation: { ...CONVERSATION, title: "触发缺口" } });
    const bootstrapFrame = await sentRequest("app.bootstrap", 2);

    emitEvent("conversation.changed", 11, { conversation: { ...CONVERSATION, title: "实时标题" } });
    latestSocket().respond(bootstrapFrame, snapshotResult(10));

    await vi.waitFor(() => {
      expect(useMobileStore.getState().lastSequence).toBe(12);
      expect(useMobileStore.getState().conversationsById.c1?.title).toBe("触发缺口");
    });
  });

  it("重连后 bootstrap 响应来自新代次时采用新代次", async () => {
    await pairAndBootstrap();
    mobileWsClient.disconnect();
    mobileWsClient.connect();
    latestSocket().open();
    latestSocket().respond(await sentRequest("app.bootstrap"), {
      ...snapshotResult(0),
      stream_id: "stream-next",
    });

    await vi.waitFor(() => {
      expect(useMobileStore.getState()).toMatchObject({
        streamId: "stream-next",
        lastSequence: 0,
        bootstrapped: true,
      });
    });
  });

  it("收到新代次的事件时立即请求该代次的快照", async () => {
    await pairAndBootstrap();
    emitEvent("queue.changed", 1, { conversation_id: "c9", items: [] }, "stream-next");

    latestSocket().respond(await sentRequest("app.bootstrap", 2), {
      ...snapshotResult(1),
      stream_id: "stream-next",
    });
    await vi.waitFor(() => {
      expect(useMobileStore.getState()).toMatchObject({
        streamId: "stream-next",
        bootstrapped: true,
      });
    });
  });

  it("state.snapshot 不改写当前聊天的配对，活动任务按当前聊天从 active_tasks 选取", async () => {
    await pairAndBootstrap();
    const taskC1 = activeTask("c1", "task-c1");
    await openConversation(openResult({ active_task: taskC1 }));

    // 快照属于桌面端当前聊天 c9，带着另一个配对与任务。
    const otherPair: PairRecord = {
      ...PAIR,
      pair_id: "pair-B",
      character: { id: "firefly", name: "流萤", voice_id: "" },
    };
    const taskB = activeTask("c9", "task-B");
    emitEvent("state.snapshot", 11, {
      ...snapshotResult(11),
      current_conversation_id: "c9",
      pair: otherPair,
      pairs: [otherPair],
      active_task: taskB,
      active_tasks: [taskB, taskC1],
    });
    expect(useMobileStore.getState().pair).toEqual(PAIR);
    expect(useMobileStore.getState().activeTask).toEqual(taskC1);

    emitEvent("state.snapshot", 12, { ...snapshotResult(12), active_tasks: [] });
    expect(useMobileStore.getState().activeTask).toBeNull();
  });
});

describe("mobileStore 电源状态", () => {
  const atRiskPayload: PowerStatusPayload = {
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
    warnings: [],
  };

  it("power.status_changed 载荷原样写入电源状态", async () => {
    await pairAndBootstrap();
    emitEvent("power.status_changed", 11, atRiskPayload);
    expect(useMobileStore.getState().powerStatus).toEqual(atRiskPayload);
  });

  it("disconnect 清空电源状态", async () => {
    await pairAndBootstrap();
    emitEvent("power.status_changed", 11, atRiskPayload);
    expect(useMobileStore.getState().powerStatus).toEqual(atRiskPayload);

    await useMobileStore.getState().disconnect();
    expect(useMobileStore.getState().powerStatus).toBeNull();
  });

  it("收到新代次的事件时清空上一代次的电源状态", async () => {
    await pairAndBootstrap();
    emitEvent("power.status_changed", 11, atRiskPayload);

    emitEvent("queue.changed", 1, { conversation_id: "c9", items: [] }, "stream-next");
    expect(useMobileStore.getState().powerStatus).toBeNull();
  });

  it("新代次的电源事件在会话复位后照常写入", async () => {
    await pairAndBootstrap();
    emitEvent("power.status_changed", 11, atRiskPayload);
    const freshPayload: PowerStatusPayload = {
      ...atRiskPayload,
      plan_name: "高性能",
      reason: "DC 睡眠超时 300 秒低于阈值 900 秒",
      checked_at: "2026-09-02T11:00:00",
    };

    emitEvent("power.status_changed", 1, freshPayload, "stream-next");
    expect(useMobileStore.getState().powerStatus).toEqual(freshPayload);
  });
});

describe("mobileStore 打开聊天", () => {
  it("conversation.open 带手机视图 id，装载结果写入消息、配对与活动任务", async () => {
    await pairAndBootstrap();
    const task = activeTask("c1", "task-7");
    const opening = useMobileStore.getState().openConversation("c1");
    const frame = await sentRequest("conversation.open");
    expect(frame.params).toEqual({
      conversation_id: "c1",
      view_id: expect.stringMatching(/^mobile-/),
    });
    latestSocket().respond(frame, openResult({ messages: [message()], active_task: task }));
    await opening;

    expect(useMobileStore.getState()).toMatchObject({
      activeConversationId: "c1",
      messages: [message()],
      pair: PAIR,
      activeTask: task,
      timelineLoading: false,
    });
  });

  it("WS 握手完成前打开聊天时等连接就绪再发请求", async () => {
    // 刷新后直接落在聊天页：连接尚未建立。
    mobileWsClient.disconnect();
    const opening = useMobileStore.getState().openConversation("c1");
    expect(latestSocket().readyState).toBe(FakeWebSocket.CONNECTING);
    expect(latestSocket().sent).toEqual([]);

    latestSocket().open();
    latestSocket().respond(await sentRequest("conversation.open"), openResult());
    await opening;
    expect(useMobileStore.getState().activeConversationId).toBe("c1");
  });

  it("装载失败时停在目标聊天并记录 openError，等待期间的事件照常生效", async () => {
    await pairAndBootstrap();
    await openConversation(openResult({ messages: [message({ message_id: "previous" })] }));

    const opening = useMobileStore.getState().openConversation("c2");
    const frame = await sentRequest("conversation.open", 2);
    emitEvent("conversation.changed", 11, { conversation: { ...CONVERSATION, title: "等待期更新" } });
    latestSocket().respondError(frame, "conversation_not_found", "聊天不存在");

    await expect(opening).rejects.toThrow("聊天不存在");
    expect(useMobileStore.getState()).toMatchObject({
      activeConversationId: "c2",
      messages: [],
      lastSequence: 11,
      openError: { conversationId: "c2", message: "聊天不存在" },
    });
    expect(useMobileStore.getState().conversationsById.c1?.title).toBe("等待期更新");
  });

  it("装载等待期间收到的事件按装载结果的序号重放，不被装载结果覆盖", async () => {
    await pairAndBootstrap();
    const opening = useMobileStore.getState().openConversation("c1");
    const frame = await sentRequest("conversation.open");

    emitEvent("message.delta", 11, {
      message_id: "live",
      conversation_id: "c1",
      pair_id: "pair-default",
      source: "character",
      kind: "character.speech",
      delta: "实时内容",
      timeline_order: 1,
    });
    latestSocket().respond(frame, openResult());
    await opening;

    expect(useMobileStore.getState().messages[0]?.text).toBe("实时内容");
    expect(useMobileStore.getState().lastSequence).toBe(11);
  });

  it("连续打开两个聊天时忽略先发请求的迟到响应", async () => {
    await pairAndBootstrap();
    const c2 = { ...CONVERSATION, conversation_id: "c2", title: "第二个聊天" };
    const first = useMobileStore.getState().openConversation("c1");
    const firstFrame = await sentRequest("conversation.open");
    const second = useMobileStore.getState().openConversation("c2");
    const secondFrame = await sentRequest("conversation.open", 2);

    latestSocket().respond(
      secondFrame,
      openResult({ conversation: c2, messages: [message({ message_id: "m2", conversation_id: "c2" })] }),
    );
    await second;
    latestSocket().respond(firstFrame, openResult({ messages: [message({ message_id: "m1" })] }));
    await first;

    expect(useMobileStore.getState().activeConversationId).toBe("c2");
    expect(useMobileStore.getState().messages.map((item) => item.message_id)).toEqual(["m2"]);
  });
});

describe("mobileStore 提交与设置", () => {
  it.each([
    ["submitMessage", "character"],
    ["submitDelegation", "assistant"],
  ] as const)("%s 发 chat.submit target=%s，不带 mode", async (action, target) => {
    await pairAndBootstrap();
    const submitting = useMobileStore.getState()[action]("c1", "今天好累");
    const frame = await sentRequest("chat.submit");
    // 模式以服务端会话记录为准，提交不带 mode。
    expect(frame.params).toEqual({ conversation_id: "c1", target, text: "今天好累" });
    latestSocket().respond(frame, {
      message_id: "m-user",
      conversation_id: "c1",
      status: "received",
      target,
      turn_id: "turn-1",
    });
    await submitting;
  });

  it("setConversationMode 发 conversation.set_mode，last_mode 等 conversation.changed 到达才更新", async () => {
    await pairAndBootstrap();
    emitEvent("conversation.changed", 11, { conversation: { ...CONVERSATION, last_mode: "chat" } });

    const switching = useMobileStore.getState().setConversationMode("c1", "collaboration");
    const frame = await sentRequest("conversation.set_mode");
    expect(frame.params).toEqual({ conversation_id: "c1", mode: "collaboration" });
    latestSocket().respond(frame, { conversation_id: "c1", mode: "collaboration" });
    await switching;
    expect(useMobileStore.getState().conversationsById.c1?.last_mode).toBe("chat");

    emitEvent("conversation.changed", 12, { conversation: CONVERSATION });
    expect(useMobileStore.getState().conversationsById.c1?.last_mode).toBe("collaboration");
  });

  it("setApprovalMode 发 project.update_settings 并按返回的项目记录更新审批模式", async () => {
    await pairAndBootstrap();
    const updating = useMobileStore.getState().setApprovalMode("p1", "full_auto");
    const frame = await sentRequest("project.update_settings");
    expect(frame.params).toEqual({ project_id: "p1", approval_mode: "full_auto" });
    latestSocket().respond(frame, { project: { ...PROJECT, approval_mode: "full_auto" } });
    await updating;

    expect(useMobileStore.getState().projects[0]?.approval_mode).toBe("full_auto");
  });
});

describe("mobileStore 当前聊天的事件", () => {
  it("message.status_changed 按 id 原位更新消息状态", async () => {
    await pairAndBootstrap();
    const delegation = message({
      message_id: "msg-del",
      source: "user",
      kind: "user.text",
      text: "把 README 翻成英文",
      tts_eligible: false,
      origin: "character_delegation",
      delegation_id: "task-1",
      status: "processing",
    });
    await openConversation(openResult({ messages: [delegation] }));

    emitEvent("message.status_changed", 11, { message: { ...delegation, status: "done" } });
    expect(useMobileStore.getState().messages).toEqual([{ ...delegation, status: "done" }]);
  });

  it("task.busy_changed 以完整 active_tasks 替换，当前聊天的任务随之结束", async () => {
    await pairAndBootstrap();
    await openConversation(openResult({ active_task: activeTask("c1", "task-1") }));

    emitEvent("task.busy_changed", 11, {
      busy: false,
      conversation_id: "c1",
      active_task: null,
      active_tasks: [],
    });
    expect(useMobileStore.getState()).toMatchObject({ activeTask: null, activeTasks: [] });
  });

  it("其他聊天的消息与任务事件不改写当前聊天", async () => {
    await pairAndBootstrap();
    const current = message({
      message_id: "current",
      source: "user",
      kind: "user.text",
      text: "当前消息",
      tts_eligible: false,
    });
    const task = activeTask("c1", "task-c1");
    await openConversation(openResult({ messages: [current], active_task: task }));

    emitEvent("message.status_changed", 11, {
      message: { ...current, message_id: "other", conversation_id: "c2" },
    });
    emitEvent("task.busy_changed", 12, {
      busy: false,
      conversation_id: "c2",
      active_task: null,
      active_tasks: [task],
    });

    expect(useMobileStore.getState().messages).toEqual([current]);
    expect(useMobileStore.getState().activeTask).toEqual(task);
  });

  it("同一序号的思考增量只归并一次，且不写入正文", async () => {
    await pairAndBootstrap();
    await openConversation(openResult({ messages: [message({ message_id: "m-stream" })] }));
    const delta = {
      message_id: "m-stream",
      conversation_id: "c1",
      pair_id: "pair-default",
      source: "character",
      kind: "character.speech",
      delta: "思考",
      channel: "reasoning",
      reasoning_streaming: true,
      timeline_order: 1,
    };

    emitEvent("message.delta", 11, delta);
    emitEvent("message.delta", 11, delta);
    // 增量按动画帧合并写入 store。
    await new Promise((resolve) => requestAnimationFrame(resolve));

    const updated = useMobileStore.getState().messages[0]!;
    expect(updated.text).toBe("正文");
    expect(updated.payload.reasoning).toBe("思考");
  });
});

describe("mobileStore 语音输入", () => {
  async function startRecording(): Promise<void> {
    const starting = useMobileStore.getState().startVoiceCapture("c1");
    latestSocket().respond(await sentRequest("voice.mobile_ptt_start"), {
      session_id: "sess-1",
      conversation_id: "c1",
    });
    await starting;
  }

  it("startVoiceCapture 发 voice.mobile_ptt_start，进入 recording 并记下 session_id", async () => {
    await pairAndBootstrap();
    const starting = useMobileStore.getState().startVoiceCapture("c1");
    const frame = await sentRequest("voice.mobile_ptt_start");
    expect(frame.params).toEqual({ conversation_id: "c1" });
    latestSocket().respond(frame, { session_id: "sess-1", conversation_id: "c1" });

    await expect(starting).resolves.toMatchObject({ session_id: "sess-1" });
    expect(useMobileStore.getState().voice.capture).toEqual({
      state: "recording",
      sessionId: "sess-1",
      error: null,
    });
  });

  it("录音进行中再次开始时拒绝并记录原因，不发请求", async () => {
    await pairAndBootstrap();
    await startRecording();

    await expect(useMobileStore.getState().startVoiceCapture("c1")).rejects.toThrow(
      "语音采集正在进行中",
    );
    expect(latestSocket().sentFrames("voice.mobile_ptt_start")).toHaveLength(1);
    expect(useMobileStore.getState().voice.capture).toMatchObject({
      state: "recording",
      error: "语音采集正在进行中",
    });
  });

  it("sendAudioChunk 按当前录音会话发送分片", async () => {
    FakeWebSocket.autoResults.set("voice.mobile_audio_chunk", { accepted: true });
    await pairAndBootstrap();
    await startRecording();

    await useMobileStore.getState().sendAudioChunk(0, "ZmFrZS0w");
    await useMobileStore.getState().sendAudioChunk(1, "ZmFrZS0x");

    expect(latestSocket().sentFrames("voice.mobile_audio_chunk").map((frame) => frame.params)).toEqual([
      { session_id: "sess-1", seq: 0, data: "ZmFrZS0w" },
      { session_id: "sess-1", seq: 1, data: "ZmFrZS0x" },
    ]);
  });

  it("音频分片被拒时错误写入 capture.error 并抛出，录音状态保持", async () => {
    await pairAndBootstrap();
    await startRecording();

    const sending = useMobileStore.getState().sendAudioChunk(3, "ZmFrZS0z");
    latestSocket().respondError(
      await sentRequest("voice.mobile_audio_chunk"),
      "voice_audio_seq_gap",
      "音频分片序号跳号：期望 0，实际 3",
    );

    await expect(sending).rejects.toThrow(/跳号/);
    expect(useMobileStore.getState().voice.capture).toMatchObject({
      state: "recording",
      error: expect.stringContaining("跳号"),
    });
  });

  it("voice.mobile_transcript 更新转写，is_final 后录音回到空闲", async () => {
    await pairAndBootstrap();
    await startRecording();

    emitRemoteOnly("voice.mobile_transcript", {
      conversation_id: "c1",
      session_id: "sess-1",
      text: "partial",
      is_final: false,
    });
    expect(useMobileStore.getState().voice.transcript).toEqual({
      sessionId: "sess-1",
      text: "partial",
      isFinal: false,
    });

    emitRemoteOnly("voice.mobile_transcript", {
      conversation_id: "c1",
      session_id: "sess-1",
      text: "final text",
      is_final: true,
    });
    const voice = useMobileStore.getState().voice;
    expect(voice.transcript).toEqual({ sessionId: "sess-1", text: "final text", isFinal: true });
    expect(voice.capture).toMatchObject({ state: "idle", sessionId: null });
  });
});

describe("mobileStore 朗读", () => {
  it("语音分片缓冲并进入 buffering，结束信号到达后进入 playing", async () => {
    await pairAndBootstrap();
    ttsChunk("m-tts");
    expect(useMobileStore.getState().voice.ttsChunks["m-tts"]).toEqual([
      { seq: 0, mime: "audio/pcm;rate=24000", data: "ZAA=", bytes: 2 },
    ]);
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "m-tts",
      state: "buffering",
    });

    ttsEnd("m-tts");
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "m-tts",
      state: "playing",
    });
  });

  it("缓冲超过上限时整条朗读失败（pcm_overflow），迟到的分片与结束信号不再恢复播放", async () => {
    await pairAndBootstrap();
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    // 字节数可被 3 整除时 base64 不带填充，长度为字节数的 4/3。
    const chunkData = (bytes: number) => "A".repeat((bytes * 4) / 3);
    const cap = TTS_MAX_BUFFERED_PCM_BYTES;

    ttsChunk("m-cap", 0, chunkData(cap / 2));
    ttsChunk("m-cap", 1, chunkData(cap / 2));
    expect(useMobileStore.getState().voice.ttsChunks["m-cap"]).toHaveLength(2);

    ttsChunk("m-cap", 2, chunkData(48));
    const voice = useMobileStore.getState().voice;
    expect(voice.playback).toMatchObject({
      messageId: "m-cap",
      state: "failed",
      errorCode: "pcm_overflow",
    });
    expect(voice.playback.error).toContain("超过上限");
    expect(voice.ttsChunks["m-cap"]).toBeUndefined();
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("pcm_overflow"));

    ttsChunk("m-cap", 3);
    ttsEnd("m-cap");
    expect(useMobileStore.getState().voice.playback.state).toBe("failed");
    expect(useMobileStore.getState().voice.ttsChunks["m-cap"]).toBeUndefined();
  });

  it("appendTtsChunk 按 seq 排序、重复 seq 去重，超过上限时清空并返回 overflow", () => {
    const mk = (seq: number, bytes: number): MobileTtsChunk => ({
      seq,
      mime: "audio/pcm;rate=24000",
      data: "",
      bytes,
    });
    const sorted = appendTtsChunk([mk(1, 10)], mk(0, 10), 100);
    expect(sorted).toEqual({ chunks: [mk(0, 10), mk(1, 10)], overflow: false });
    // 重复 seq 不重复计入容量。
    expect(appendTtsChunk(sorted.chunks, mk(1, 10), 100)).toEqual(sorted);
    expect(appendTtsChunk([mk(0, 60), mk(1, 60)], mk(2, 60), 100)).toEqual({
      chunks: [],
      overflow: true,
    });
    expect(appendTtsChunk([mk(0, 60)], mk(1, 200), 100)).toEqual({ chunks: [], overflow: true });
  });

  it("releaseTtsChunksUpTo 释放已移交播放引擎的分片，释放完的消息条目随之删除", async () => {
    await pairAndBootstrap();
    ttsChunk("m-cap", 0);
    ttsChunk("m-cap", 1);

    useMobileStore.getState().releaseTtsChunksUpTo("m-cap", 0);
    expect(useMobileStore.getState().voice.ttsChunks["m-cap"]!.map((item) => item.seq)).toEqual([1]);
    useMobileStore.getState().releaseTtsChunksUpTo("m-cap", 1);
    expect(useMobileStore.getState().voice.ttsChunks["m-cap"]).toBeUndefined();
  });

  it("播放失败后保留错误，迟到的结束信号不覆盖失败，下一条朗读照常开始", async () => {
    await pairAndBootstrap();
    vi.spyOn(console, "error").mockImplementation(() => {});
    ttsChunk("m-fail");

    useMobileStore
      .getState()
      .failVoicePlayback("m-fail", "播放结束信号超时：300 秒未收到 voice.mobile_tts_end，已中止播放", null);
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "m-fail",
      state: "failed",
      error: expect.stringContaining("voice.mobile_tts_end"),
    });
    expect(useMobileStore.getState().voice.ttsChunks["m-fail"]).toBeUndefined();

    ttsEnd("m-fail");
    expect(useMobileStore.getState().voice.playback.state).toBe("failed");

    ttsChunk("m-next");
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "m-next",
      state: "buffering",
    });
  });

  it("已播完的朗读迟到的合成失败不影响正在缓冲的下一条", async () => {
    await pairAndBootstrap();
    vi.spyOn(console, "error").mockImplementation(() => {});
    ttsChunk("m-old");
    ttsEnd("m-old");
    useMobileStore.getState().finishVoicePlayback("m-old");
    ttsChunk("m-new");

    emitRemoteOnly("voice.mobile_tts_failed", {
      conversation_id: "c1",
      message_id: "m-old",
      error: "synthesis failed",
    });
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "m-new",
      state: "buffering",
    });
  });

  it("其他消息合成失败只清理它自己，正在缓冲的朗读不受影响", async () => {
    await pairAndBootstrap();
    vi.spyOn(console, "error").mockImplementation(() => {});
    ttsChunk("m-active");

    emitRemoteOnly("voice.mobile_tts_failed", {
      conversation_id: "c1",
      message_id: "m-other",
      error: "synthesis failed",
    });
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "m-active",
      state: "buffering",
    });
    expect(Object.keys(useMobileStore.getState().voice.ttsChunks)).toEqual(["m-active"]);
  });

  it("停止请求在途时到达的新朗读不被停止回执改写", async () => {
    await pairAndBootstrap();
    ttsChunk("msg-1");
    ttsEnd("msg-1");

    const stopping = useMobileStore.getState().stopVoicePlayback("msg-1");
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "msg-1",
      state: "stopping",
    });
    ttsChunk("msg-2");
    ttsEnd("msg-2");

    const frame = await sentRequest("voice.mobile_tts_stop");
    expect(frame.params).toEqual({ message_id: "msg-1" });
    latestSocket().respond(frame, { message_id: "msg-1", stopped: true });
    await stopping;

    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "msg-2",
      state: "playing",
    });
  });

  it("已停止的朗读迟到的分片不再恢复播放", async () => {
    await pairAndBootstrap();
    ttsChunk("msg-stopped");
    const stopping = useMobileStore.getState().stopVoicePlayback("msg-stopped");
    latestSocket().respond(await sentRequest("voice.mobile_tts_stop"), {
      message_id: "msg-stopped",
      stopped: true,
    });
    await stopping;
    expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: null, state: "idle" });

    ttsChunk("msg-stopped", 5);
    expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: null, state: "idle" });
  });

  it("当前聊天出现新的角色回复时打断正在播放的朗读，并请求服务端停止合成", async () => {
    await pairAndBootstrap();
    await openConversation();
    ttsChunk("msg-old");
    ttsEnd("msg-old");

    emitEvent("message.created", 11, {
      message: message({ message_id: "msg-new", text: "这是新的回答内容" }),
      tts_ready: true,
    });
    expect(useMobileStore.getState().voice.playback).toMatchObject({ messageId: null, state: "idle" });
    expect(useMobileStore.getState().voice.ttsChunks["msg-old"]).toBeUndefined();
    expect((await sentRequest("voice.mobile_tts_stop")).params).toEqual({ message_id: "msg-old" });

    ttsChunk("msg-new");
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "msg-new",
      state: "buffering",
    });
  });

  it("另一条消息的语音分片到达时抢占正在播放的朗读，并请求服务端停止合成", async () => {
    await pairAndBootstrap();
    ttsChunk("msg-old");
    ttsEnd("msg-old");

    ttsChunk("msg-new");
    expect(useMobileStore.getState().voice.playback).toMatchObject({
      messageId: "msg-new",
      state: "buffering",
    });
    expect(useMobileStore.getState().voice.ttsChunks["msg-old"]).toBeUndefined();
    expect((await sentRequest("voice.mobile_tts_stop")).params).toEqual({ message_id: "msg-old" });
  });

  it("voice.playback_interrupted 停止被打断的朗读并记录打断，迟到分片不再恢复", async () => {
    await pairAndBootstrap();
    vi.spyOn(console, "warn").mockImplementation(() => {});
    ttsChunk("m-int");
    expect(useMobileStore.getState().voice.playback.messageId).toBe("m-int");

    emitEvent("voice.playback_interrupted", 11, {
      conversation_id: "c1",
      message_id: "m-int",
      reason: "user_submit",
    });
    ttsChunk("m-int", 1);

    const voice = useMobileStore.getState().voice;
    expect(voice.ttsChunks["m-int"]).toBeUndefined();
    expect(voice.playback).toMatchObject({ messageId: null, state: "idle" });
    expect(voice.lastInterruption).toEqual({
      conversationId: "c1",
      messageId: "m-int",
      reason: "user_submit",
    });
  });
});

describe("mobileStore 审批", () => {
  /** 桌面端用户先裁决为 deny；approval.resolved 载荷与 approval_already_resolved 的 details 同形。 */
  const DESKTOP_DENY: ApprovalResolvedPayload = {
    approval_id: "a1",
    conversation_id: "c1",
    task_id: "t1",
    decision: "deny",
    resolved_by: "desktop",
    actor: "user",
    request_reason: "需要确认",
    resolution_reason: null,
    resolved_at: "2026-09-30T00:00:00+00:00",
    error_code: null,
  };

  function respondAlreadyResolved(frame: SentFrame): void {
    latestSocket().emit({
      kind: "response",
      id: frame.id,
      ok: false,
      error: {
        code: "approval_already_resolved",
        message: "审批已由 desktop 应答（deny），不能重复应答",
        details: DESKTOP_DENY,
      },
    });
  }

  it("approval.requested 加入待审批，approval.resolved 移入已决记录并带上原操作", async () => {
    await pairAndBootstrap();
    emitEvent("approval.requested", 11, APPROVAL);
    expect(useMobileStore.getState().approvals).toEqual([APPROVAL]);

    const timeout: ApprovalResolvedPayload = {
      ...DESKTOP_DENY,
      decision: "timeout",
      resolved_by: "system",
      actor: "system",
      resolution_reason: "等待审批超时",
      error_code: "approval_timeout",
    };
    emitEvent("approval.resolved", 12, timeout);

    const state = useMobileStore.getState();
    expect(state.approvals).toEqual([]);
    expect(state.resolvedApprovals).toEqual([{ ...timeout, operation: APPROVAL.operation }]);
  });

  it("resolveApproval 遇 approval_already_resolved 时按 details 记录先到者的裁决并抛出", async () => {
    await pairAndBootstrap();
    emitEvent("approval.requested", 11, APPROVAL);

    const resolving = useMobileStore.getState().resolveApproval("a1", "allow");
    const frame = await sentRequest("approval.resolve");
    expect(frame.params).toEqual({ approval_id: "a1", decision: "allow" });
    respondAlreadyResolved(frame);

    await expect(resolving).rejects.toThrow(/不能重复应答/);
    const state = useMobileStore.getState();
    expect(state.approvals).toEqual([]);
    expect(state.resolvedApprovals).toEqual([{ ...DESKTOP_DENY, operation: APPROVAL.operation }]);
  });

  it("approval.resolved 先到时，随后的 approval_already_resolved 不重复记录", async () => {
    await pairAndBootstrap();
    emitEvent("approval.requested", 11, APPROVAL);
    emitEvent("approval.resolved", 12, DESKTOP_DENY);

    const resolving = useMobileStore.getState().resolveApproval("a1", "allow");
    respondAlreadyResolved(await sentRequest("approval.resolve"));

    await expect(resolving).rejects.toThrow(/不能重复应答/);
    expect(useMobileStore.getState().resolvedApprovals).toEqual([
      { ...DESKTOP_DENY, operation: APPROVAL.operation },
    ]);
  });
});

describe("mobileStore 排队", () => {
  function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
    return {
      queue_item_id: "q-1",
      account_id: "acc",
      conversation_id: "c1",
      target: "character",
      text: "排队中的消息",
      intent: "followup",
      position: 0,
      status: "queued",
      error: null,
      created_at: "2026-09-05T00:00:00+00:00",
      source_message_id: null,
      origin: "remote",
      remote_device_key: null,
      remote_device_name: null,
      ...overrides,
    };
  }

  it("queue.changed 只更新当前聊天的排队项，保留 queued 与 failed", async () => {
    await pairAndBootstrap();
    await openConversation();

    emitEvent("queue.changed", 11, {
      conversation_id: "c1",
      items: [
        queueItem(),
        queueItem({ queue_item_id: "q-2", position: 1, status: "processing" }),
        queueItem({ queue_item_id: "q-3", position: 2, status: "failed", error: "派发失败" }),
      ],
    });
    const items = useMobileStore.getState().queueItems;
    expect(items.map((item) => item.queue_item_id)).toEqual(["q-1", "q-3"]);
    expect(items[1].error).toBe("派发失败");

    emitEvent("queue.changed", 12, { conversation_id: "c2", items: [] });
    expect(useMobileStore.getState().queueItems.map((item) => item.queue_item_id)).toEqual([
      "q-1",
      "q-3",
    ]);
  });

  it("chat.submit 回执为排队时立即写入当前聊天的排队项", async () => {
    await pairAndBootstrap();
    await openConversation();

    const submitting = useMobileStore.getState().submitMessage("c1", "忙时新消息");
    latestSocket().respond(await sentRequest("chat.submit"), {
      queue_item: queueItem({ text: "忙时新消息" }),
      queued: true,
      conversation_id: "c1",
    });
    await submitting;

    expect(useMobileStore.getState().queueItems.map((item) => item.text)).toEqual(["忙时新消息"]);
  });

  it.each([
    ["queue.withdraw", () => useMobileStore.getState().withdrawQueueItem("q-1"), { queue_item_id: "q-1" }],
    ["queue.prioritize", () => useMobileStore.getState().prioritizeQueueItem("q-1"), { queue_item_id: "q-1" }],
    [
      "queue.edit",
      () => useMobileStore.getState().editQueueItem("q-1", "改后的文本"),
      { queue_item_id: "q-1", text: "改后的文本" },
    ],
  ] as const)("排队项命令发 %s", async (method, run, params) => {
    await pairAndBootstrap();
    const pending = run();
    const frame = await sentRequest(method);
    expect(frame.params).toEqual(params);
    latestSocket().respond(frame, { queue_item: queueItem() });
    await pending;
  });
});
