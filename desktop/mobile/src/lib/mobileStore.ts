import { create } from "zustand";
import type {
  ActiveTask,
  ApprovalMode,
  ApprovalResolvedPayload,
  ConversationMode,
  ConversationOpenResult,
  ConversationRecord,
  DesktopSnapshot,
  Message,
  MessageDeltaPayload,
  QueueItem,
  PairRecord,
  PendingApproval,
  PowerStatusPayload,
  ProjectRecord,
  RemoteControlState,
  ToolRun,
} from "@shared/contracts/protocol";
import { applyMessageDelta, isReasoningDelta } from "@shared/stores/messageDelta";
import type { AuthFailureReason, MobileConnectionState, WireEvent } from "./wsClient";
import {
  getStoredDeviceName,
  getStoredToken,
  MobileWsClient,
  RemoteCommandError,
  saveCredentials,
  clearCredentials,
} from "./wsClient";
import { navigate } from "./router";

// 手机端业务 store：归并连接代次、事件序号、会话消息、工具与审批状态。
// 序号缺口或连接代次变化时重新 bootstrap。

export interface MobileVoiceCapture {
  state: "idle" | "starting" | "recording" | "stopping";
  sessionId: string | null;
  error: string | null;
}

export interface MobileVoiceTranscript {
  sessionId: string;
  text: string;
  isFinal: boolean;
}

export interface MobileVoicePlayback {
  messageId: string | null;
  state: "idle" | "buffering" | "playing" | "stopping" | "failed";
  error: string | null;
  /** 失败码（如 pcm_overflow）；没有失败码时为 null。 */
  errorCode: string | null;
}

const IDLE_PLAYBACK: MobileVoicePlayback = {
  messageId: null,
  state: "idle",
  error: null,
  errorCode: null,
};

export interface MobileVoiceAvailability {
  secureContext: boolean;
  micPermission: "unknown" | "granted" | "denied" | "prompt";
  supported: boolean;
}

/** 最近一次朗读被服务端打断（voice.playback_interrupted 载荷原值）。 */
export interface MobilePlaybackInterruption {
  conversationId: string | null;
  messageId: string | null;
  reason: string | null;
}

/**
 * 已决审批：终态字段取自 approval.resolved 载荷或 approval_already_resolved 的 details（两者同形）；
 * operation 来自本端见过的待审批记录，没见过时为 null。
 */
export interface MobileResolvedApproval extends ApprovalResolvedPayload {
  operation: PendingApproval["operation"] | null;
}

/** 聊天页装载失败：保留目标会话，页面据此提供重试。 */
export interface MobileOpenError {
  conversationId: string;
  message: string;
}

/** voice.mobile_tts_chunk 载荷（只发给手机，不带序号）。 */
interface MobileTtsChunkPayload {
  conversation_id: string;
  message_id: string;
  seq: number;
  mime: string;
  data: string;
}

/** 下行 TTS 分片的缓冲形态。 */
export interface MobileTtsChunk {
  seq: number;
  mime: string;
  data: string;
  /** 解码后 PCM 字节数，容量核算用，避免重复解码。 */
  bytes: number;
}

/** 服务端下行 PCM 规格：24kHz mono s16le（2 字节/采样）。 */
export const TTS_SAMPLE_RATE = 24000;
const TTS_BYTES_PER_SAMPLE = 2;

/**
 * 未播分片缓冲上限约 300 秒音频（14.4MB）。正常播放边收边放，只留网络突发量；
 * 超限出现在播放停滞或结束信号丢失时。
 */
export const TTS_MAX_BUFFERED_PCM_BYTES = TTS_SAMPLE_RATE * TTS_BYTES_PER_SAMPLE * 300;

/** 按标准 base64 长度换算解码后字节数（只做容量核算，不解码）。 */
export function base64PcmByteLength(base64: string): number {
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.floor((base64.length * 3) / 4) - padding;
}

/**
 * 有界追加 TTS 分片。返回 overflow=true 时整条播放进入 failed（pcm_overflow），
 * 调用方清空该消息缓冲、记录终态并请求服务端停止合成。
 */
export function appendTtsChunk(
  chunks: MobileTtsChunk[],
  chunk: MobileTtsChunk,
  maxBytes: number,
): { chunks: MobileTtsChunk[]; overflow: boolean } {
  if (chunks.some((item) => item.seq === chunk.seq)) {
    return { chunks, overflow: false };
  }
  const merged = [...chunks, chunk].sort((a, b) => a.seq - b.seq);
  const total = merged.reduce((sum, item) => sum + item.bytes, 0);
  if (total > maxBytes) {
    return { chunks: [], overflow: true };
  }
  return { chunks: merged, overflow: false };
}

export interface MobileState {
  connection: MobileConnectionState;
  /** 最近一次鉴权失败的原因；连接不在 auth_failed 时为 null。 */
  authFailureReason: AuthFailureReason | null;
  deviceName: string | null;
  projects: ProjectRecord[];
  conversationsById: Record<string, ConversationRecord>;
  activeConversationId: string | null;
  messages: Message[];
  toolRuns: ToolRun[];
  /** 当前聊天的待派发与派发失败排队项（queue.changed 与装载结果驱动）。 */
  queueItems: QueueItem[];
  approvals: PendingApproval[];
  /** 已决审批记录，界面据此展示双端仲裁结果。 */
  resolvedApprovals: MobileResolvedApproval[];
  /** 当前聊天的配对，委派卡显示「来自 <角色名> 的委派」。 */
  pair: PairRecord | null;
  /** 当前聊天的活动任务，委派卡据 delegation_id 判断运行中。 */
  activeTask: ActiveTask | null;
  /** 全账号活动任务集合；activeTask 是其中当前聊天的条目。 */
  activeTasks: ActiveTask[];
  /** 远程控制租约；首次同步前为 null。 */
  remoteControl: RemoteControlState | null;
  streamId: string | null;
  /** 最近处理的带序号事件；-1 表示本代次尚未收到事件。 */
  lastSequence: number;
  bootstrapped: boolean;
  /** 最近一次状态同步（app.bootstrap）的原始错误；同步成功或重新开始时清空。 */
  syncError: string | null;
  /** 当前聊天页装载（conversation.open）失败的原始错误。 */
  openError: MobileOpenError | null;
  /** 桌面端电源状态（power.status_changed 与 power.get_status）；未取得时为 null。 */
  powerStatus: PowerStatusPayload | null;
  voice: {
    capture: MobileVoiceCapture;
    transcript: MobileVoiceTranscript | null;
    playback: MobileVoicePlayback;
    availability: MobileVoiceAvailability;
    /** 下行 TTS 分片缓冲：message_id 到有序分片，总量受 TTS_MAX_BUFFERED_PCM_BYTES 限制。 */
    ttsChunks: Record<string, MobileTtsChunk[]>;
    /** 最近一次朗读被打断；下一条朗读开始时清空。 */
    lastInterruption: MobilePlaybackInterruption | null;
  };

  start: () => void;
  /** 手动重连（unreachable、disconnected 后由界面的重试按钮调用）。 */
  reconnect: () => void;
  /** 状态同步失败后的重试入口。 */
  retrySync: () => Promise<void>;
  pairDevice: (code: string, deviceName: string) => Promise<void>;
  openConversation: (conversationId: string) => Promise<void>;
  /** 委派给助手；不带 mode，模式以服务端会话记录为准。 */
  submitDelegation: (conversationId: string, text: string) => Promise<void>;
  /** 普通角色消息（target=character，任何模式可用）。 */
  submitMessage: (conversationId: string, text: string) => Promise<void>;
  /** 排队项命令：撤回、编辑文本、置顶（只对 queued 项）。 */
  withdrawQueueItem: (queueItemId: string) => Promise<void>;
  editQueueItem: (queueItemId: string, text: string) => Promise<void>;
  prioritizeQueueItem: (queueItemId: string) => Promise<void>;
  /** 会话模式切换（chat / collaboration），委派只在协作模式可用。 */
  setConversationMode: (conversationId: string, mode: ConversationMode) => Promise<void>;
  resolveApproval: (approvalId: string, decision: string) => Promise<void>;
  /** 切换项目审批模式：request_approval 请求批准、review 帮我审核、full_auto 完全允许运行。 */
  setApprovalMode: (projectId: string, mode: ApprovalMode) => Promise<void>;
  startVoiceCapture: (conversationId: string) => Promise<{ session_id: string }>;
  sendAudioChunk: (seq: number, base64: string) => Promise<void>;
  /** 停止语音采集；传入 sessionId 时以它覆盖 store 里的会话（用于补发停止）。 */
  stopVoiceCapture: (sessionId?: string) => Promise<void>;
  /** 采集端（麦克风、音频引擎）失败写入 capture.error。 */
  reportVoiceCaptureError: (message: string) => void;
  stopVoicePlayback: (messageId: string) => Promise<void>;
  /** 播放引擎把该消息最后一个分片播完后复位 playback。 */
  finishVoicePlayback: (messageId: string) => void;
  /** 序号不超过 uptoSeq 的分片已交给播放引擎，从 store 释放。 */
  releaseTtsChunksUpTo: (messageId: string, uptoSeq: number) => void;
  /** 播放引擎失败（resume 失败、结束信号超时、PCM 超限）时置 failed 并保留错误与失败码。 */
  failVoicePlayback: (messageId: string, error: string, errorCode: string | null) => void;
  refreshVoiceAvailability: () => Promise<void>;
  disconnect: () => Promise<void>;
}

const client = new MobileWsClient();
// crypto.randomUUID 只在安全上下文可用，局域网 HTTP 访问时改用时间戳生成视图 id。
const mobileViewId =
  typeof crypto.randomUUID === "function"
    ? `mobile-${crypto.randomUUID()}`
    : `mobile-${Date.now().toString(36)}`;

function indexConversations(projects: ProjectRecord[]): Record<string, ConversationRecord> {
  const map: Record<string, ConversationRecord> = {};
  for (const project of projects) {
    for (const conversation of project.conversations) {
      map[conversation.conversation_id] = conversation;
    }
  }
  return map;
}

/** 按 key 原位替换；不存在时追加到末尾（新条目按到达顺序排在最后）。 */
function upsertBy<T>(list: T[], item: T, isSame: (existing: T) => boolean): T[] {
  const index = list.findIndex(isSame);
  if (index === -1) return [...list, item];
  const next = list.slice();
  next[index] = item;
  return next;
}

/** 时间线展示的排队项：待派发与派发失败（失败项带 error）。 */
function visibleQueueItems(items: QueueItem[]): QueueItem[] {
  return items.filter((item) => item.status === "queued" || item.status === "failed");
}

/** 局域网 HTTP 不是安全上下文，浏览器不提供 navigator.mediaDevices。 */
function microphoneSupported(): boolean {
  return navigator.mediaDevices?.getUserMedia !== undefined;
}

function detectVoiceAvailability(): MobileVoiceAvailability {
  return {
    secureContext: window.isSecureContext,
    micPermission: "unknown",
    supported: microphoneSupported(),
  };
}

type MobileSessionState = Pick<
  MobileState,
  | "projects"
  | "conversationsById"
  | "messages"
  | "toolRuns"
  | "queueItems"
  | "approvals"
  | "resolvedApprovals"
  | "pair"
  | "activeTask"
  | "activeTasks"
  | "remoteControl"
  | "streamId"
  | "lastSequence"
  | "bootstrapped"
  | "syncError"
  | "openError"
  | "powerStatus"
  | "voice"
>;

/**
 * 会话级状态初值：首次装载、桌面端新代次（stream_id 变化）与解绑共用。
 * 连接状态、设备名与当前打开的聊天不属于会话级状态；麦克风可用性是本机环境，沿用传入值。
 */
function initialSessionState(availability: MobileVoiceAvailability): MobileSessionState {
  return {
    projects: [],
    conversationsById: {},
    messages: [],
    toolRuns: [],
    queueItems: [],
    approvals: [],
    resolvedApprovals: [],
    pair: null,
    activeTask: null,
    activeTasks: [],
    remoteControl: null,
    streamId: null,
    lastSequence: -1,
    bootstrapped: false,
    syncError: null,
    openError: null,
    powerStatus: null,
    voice: {
      capture: { state: "idle", sessionId: null, error: null },
      transcript: null,
      playback: IDLE_PLAYBACK,
      availability,
      ttsChunks: {},
      lastInterruption: null,
    },
  };
}

function toResolvedApproval(
  payload: ApprovalResolvedPayload,
  pending: PendingApproval | undefined,
): MobileResolvedApproval {
  return { ...payload, operation: pending?.operation ?? null };
}

/** chat.submit 回执：聊天忙时消息进入队列，回执带 queued=true 与排队项。 */
interface SubmitReceipt {
  queued?: true;
  queue_item?: QueueItem;
}

function applySubmitReceipt(
  set: (partial: Partial<MobileState>) => void,
  get: () => MobileState,
  conversationId: string,
  receipt: SubmitReceipt,
): void {
  const item = receipt.queue_item;
  if (!receipt.queued || !item || get().activeConversationId !== conversationId) return;
  // queue.changed 通常先于回执到达，已在列表里就不重复追加。
  if (get().queueItems.some((existing) => existing.queue_item_id === item.queue_item_id)) return;
  set({ queueItems: [...get().queueItems, item] });
}

/**
 * 快照的消息、工具与排队项属于桌面当前聊天，只在它就是手机打开的聊天时采用；
 * 配对由 conversation.open 装载，快照不改写。
 */
function applySnapshot(
  set: (partial: Partial<MobileState>) => void,
  snapshot: DesktopSnapshot,
  get: () => MobileState,
): void {
  const activeConversationId = get().activeConversationId;
  const snapshotIsActive = snapshot.current_conversation_id === activeConversationId;
  set({
    projects: snapshot.projects,
    conversationsById: indexConversations(snapshot.projects),
    messages: snapshotIsActive ? snapshot.messages : get().messages,
    toolRuns: snapshotIsActive ? snapshot.tool_runs : get().toolRuns,
    queueItems: snapshotIsActive ? visibleQueueItems(snapshot.queue_items) : get().queueItems,
    approvals: snapshot.approvals,
    activeTask:
      snapshot.active_tasks.find((task) => task.conversation_id === activeConversationId) ?? null,
    activeTasks: snapshot.active_tasks,
    remoteControl: snapshot.remote_control,
    streamId: snapshot.stream_id,
    lastSequence: snapshot.sequence,
    bootstrapped: true,
  });
}

/** 已停止、已失败或已播完的朗读：迟到的分片与结束信号不得复活播放状态。 */
const stoppedOrTerminalMessages = new Set<string>();
/** 已收到 voice.mobile_tts_end 的朗读。 */
const endedTtsMessages = new Set<string>();

export const useMobileStore = create<MobileState>((set, get) => {
  let wired = false;
  let bootstrapping: Promise<void> | null = null;
  let bootstrapGeneration = 0;
  let releasingControl = false;
  let openConversationGeneration = 0;
  const eventCollectors = new Set<WireEvent[]>();

  /** 桌面端新代次：会话级状态整体回到初值并采用新 stream_id，保留当前打开的聊天。 */
  const resetSession = (streamId: string | null): void => {
    openConversationGeneration += 1;
    stoppedOrTerminalMessages.clear();
    endedTtsMessages.clear();
    set({ ...initialSessionState(get().voice.availability), streamId });
  };

  /** 下一条仍有分片待播的朗读；没有时返回 otherwise。 */
  const nextQueuedPlayback = (
    chunks: Record<string, MobileTtsChunk[]>,
    otherwise: MobileVoicePlayback = IDLE_PLAYBACK,
  ): MobileVoicePlayback => {
    const messageId = Object.keys(chunks).find(
      (id) => chunks[id].length > 0 && !stoppedOrTerminalMessages.has(id),
    );
    return messageId
      ? {
          messageId,
          state: endedTtsMessages.has(messageId) ? "playing" : "buffering",
          error: null,
          errorCode: null,
        }
      : otherwise;
  };

  /**
   * 本地已放弃的朗读请服务端停止合成。服务端没停下时只会继续推送分片，
   * 这些分片由终态集合挡住，所以失败只记日志，不改写当前播放状态。
   */
  const requestTtsStop = (messageId: string): void => {
    client.request("voice.mobile_tts_stop", { message_id: messageId }).catch((error: unknown) => {
      console.error("请求服务端停止朗读合成失败", messageId, error);
    });
  };

  /** 角色新回复（消息创建、首个正文分片或首个语音分片）到来时打断正在播放的旧朗读。 */
  const preemptPlayback = (newMessageId: string): void => {
    const voice = get().voice;
    const activeId = voice.playback.messageId;
    if (
      !activeId ||
      activeId === newMessageId ||
      (voice.playback.state !== "buffering" && voice.playback.state !== "playing")
    ) {
      return;
    }
    stoppedOrTerminalMessages.add(activeId);
    endedTtsMessages.delete(activeId);
    const ttsChunks = { ...voice.ttsChunks };
    delete ttsChunks[activeId];
    set({ voice: { ...voice, playback: IDLE_PLAYBACK, ttsChunks } });
    requestTtsStop(activeId);
  };

  /**
   * connect() 只发起握手；业务请求必须等 connected 后才能发。
   * auth_failed 是该连接的终态（凭据失效），直接拒绝，由界面引导重新配对。
   */
  const waitForConnected = (timeoutMs = 10_000): Promise<void> => {
    if (client.getState() === "connected") return Promise.resolve();
    if (client.getState() === "auth_failed") {
      return Promise.reject(new Error("配对凭据已失效，请重新配对"));
    }
    if (client.getState() === "disconnected" && !client.isSocketConnected()) {
      return Promise.reject(new Error("连接已断开"));
    }
    return new Promise<void>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      let unsubscribe: (() => void) | null = null;

      const cleanup = () => {
        if (timer !== null) clearTimeout(timer);
        if (unsubscribe) unsubscribe();
      };

      timer = setTimeout(() => {
        cleanup();
        reject(
          new Error(
            `等待连接超时（${timeoutMs / 1000}s，当前状态：${client.getState()}）`,
          ),
        );
      }, timeoutMs);

      unsubscribe = client.onStateChange((connection) => {
        if (connection === "connected") {
          cleanup();
          resolve();
        }
        if (
          connection === "unreachable" ||
          connection === "disconnected" ||
          connection === "auth_failed"
        ) {
          cleanup();
          reject(new Error(`连接失败：${connection}`));
        }
      });
    });
  };

  let handleEvent: (event: WireEvent, replaying?: boolean) => void;

  const collectEvents = (): { events: WireEvent[]; stop: () => void } => {
    const events: WireEvent[] = [];
    eventCollectors.add(events);
    return {
      events,
      stop: () => eventCollectors.delete(events),
    };
  };

  /** 重放收集期间同一代次的带序号事件；只发给手机的事件不带序号，收到时已即时处理。 */
  const replayEventsAfter = (events: WireEvent[], sequence: number, streamId: string | null): void => {
    events
      .filter(
        (event): event is WireEvent & { sequence: number } =>
          typeof event.sequence === "number" &&
          event.sequence > sequence &&
          event.stream_id === streamId,
      )
      .sort((left, right) => left.sequence - right.sequence)
      .forEach((event) => handleEvent(event, true));
  };

  /** 后台触发的同步失败：错误已写入 syncError，这里保留日志。 */
  const reportBootstrapFailure = (error: unknown): void => {
    console.error("手机端状态同步失败", error);
  };

  /**
   * 写入 conversation.open 装载结果。装载结果只带本聊天的 active_task，
   * 全账号活动任务集合由 app.bootstrap 与 task.busy_changed 维护，这里只替换本聊天的条目。
   */
  const applyConversationOpen = (conversationId: string, result: ConversationOpenResult): void => {
    const otherTasks = get().activeTasks.filter((task) => task.conversation_id !== conversationId);
    set({
      messages: result.messages,
      toolRuns: result.tool_runs,
      queueItems: visibleQueueItems(result.queue_items),
      pair: result.pair,
      activeTask: result.active_task,
      activeTasks: result.active_task ? [...otherTasks, result.active_task] : otherTasks,
      openError: null,
      streamId: result.stream_id,
      lastSequence: result.sequence,
      bootstrapped: true,
    });
  };

  /** 当前状态同步代次的工作；代次被新的同步取代时中途返回。 */
  const runBootstrap = async (
    generation: number,
    activeConversationId: string | null,
    collected: WireEvent[],
  ): Promise<void> => {
    const snapshot = await client.request<DesktopSnapshot>("app.bootstrap");
    if (generation !== bootstrapGeneration) return;
    // 控制声明成功后才公布同步完成；活跃聊天重连也走同一条路径。
    await client.request("remote.claim_control");
    if (generation !== bootstrapGeneration) return;
    // 鉴权请求已成功，连接确认可用后才开始心跳。
    client.startHeartbeat();
    // app.bootstrap 是新连接的基线：重连后本地留着旧 streamId 也采纳响应代次。
    if (snapshot.stream_id !== get().streamId) resetSession(snapshot.stream_id);
    applySnapshot(set, snapshot, get);
    // serve 启动时的 power.status_changed 发生在手机订阅之前且不回放，同步后主动拉一次。
    client
      .request<PowerStatusPayload>("power.get_status")
      .then((status) => {
        if (generation === bootstrapGeneration) set({ powerStatus: status });
      })
      .catch((error: unknown) => {
        console.error("电源状态拉取失败", error);
      });
    if (!activeConversationId || get().activeConversationId !== activeConversationId) {
      replayEventsAfter(collected, snapshot.sequence, snapshot.stream_id);
      return;
    }
    let conversation: ConversationOpenResult;
    try {
      conversation = await client.request<ConversationOpenResult>("conversation.open", {
        conversation_id: activeConversationId,
        view_id: mobileViewId,
      });
    } catch (error) {
      if (generation === bootstrapGeneration) {
        set({
          bootstrapped: false,
          openError: {
            conversationId: activeConversationId,
            message: error instanceof Error ? error.message : String(error),
          },
        });
        replayEventsAfter(collected, get().lastSequence, get().streamId);
      }
      throw error;
    }
    if (
      generation !== bootstrapGeneration ||
      get().activeConversationId !== activeConversationId ||
      conversation.stream_id !== get().streamId
    ) {
      // 装载期间切换了聊天或桌面端换了代次：只重放事件，新的同步会重新装载。
      replayEventsAfter(collected, get().lastSequence, get().streamId);
      return;
    }
    applyConversationOpen(activeConversationId, conversation);
    replayEventsAfter(collected, conversation.sequence, conversation.stream_id);
  };

  const bootstrap = async (): Promise<void> => {
    if (releasingControl) return;
    if (bootstrapping) return bootstrapping;
    const generation = ++bootstrapGeneration;
    set({ bootstrapped: false, syncError: null });
    const collector = collectEvents();
    let tracked: Promise<void>;
    const request = runBootstrap(generation, get().activeConversationId, collector.events);
    tracked = request.catch((error: unknown) => {
      if (generation === bootstrapGeneration) {
        set({
          bootstrapped: false,
          syncError: error instanceof Error ? error.message : String(error),
        });
      }
      throw error;
    }).finally(() => {
      collector.stop();
      if (bootstrapping === tracked) bootstrapping = null;
    });
    bootstrapping = tracked;
    return tracked;
  };

  handleEvent = (event: WireEvent, replaying = false): void => {
    const streamId = get().streamId;
    if (streamId === null) {
      set({ streamId: event.stream_id });
    } else if (event.stream_id !== streamId) {
      // 桌面端换了代次（Sidecar 重启）：作废在途同步，按新代次重新同步。
      bootstrapGeneration += 1;
      bootstrapping = null;
      eventCollectors.clear();
      resetSession(event.stream_id);
      void bootstrap().catch(reportBootstrapFailure);
    }

    // 只发给手机的事件（TTS 分片、转写）不带序号：不收集重放、不做序号校验、不推进 lastSequence。
    if (!replaying && typeof event.sequence === "number") {
      eventCollectors.forEach((events) => events.push(event));
    }

    const current = get();
    if (typeof event.sequence === "number") {
      if (event.sequence <= current.lastSequence) return;
      if (event.sequence > current.lastSequence + 1 && current.bootstrapped) {
        // 事件缺口：先建立收集器再保留触发事件，随后拉取权威快照。
        const pendingBootstrap = bootstrap();
        eventCollectors.forEach((events) => {
          if (!events.includes(event)) events.push(event);
        });
        void pendingBootstrap.catch(reportBootstrapFailure);
        return;
      }
      set({ lastSequence: event.sequence });
    }
    switch (event.event) {
      case "state.snapshot": {
        const payload = event.payload as unknown as DesktopSnapshot;
        applySnapshot(set, payload, get);
        break;
      }
      case "conversation.changed": {
        // 完整记录同时写回所属项目，列表页按项目渲染；归档的聊天带 archived=true。
        const { conversation } = event.payload as { conversation: ConversationRecord };
        set({
          conversationsById: { ...get().conversationsById, [conversation.conversation_id]: conversation },
          projects: get().projects.map((project) =>
            project.project_id === conversation.project_id
              ? {
                  ...project,
                  conversations: upsertBy(
                    project.conversations,
                    conversation,
                    (item) => item.conversation_id === conversation.conversation_id,
                  ),
                }
              : project,
          ),
        });
        break;
      }
      case "approval.requested": {
        const approval = event.payload as unknown as PendingApproval;
        set({
          approvals: upsertBy(
            get().approvals,
            approval,
            (item) => item.approval_id === approval.approval_id,
          ),
        });
        break;
      }
      case "approval.resolved": {
        const payload = event.payload as unknown as ApprovalResolvedPayload;
        const pending = get().approvals.find((item) => item.approval_id === payload.approval_id);
        set({
          approvals: get().approvals.filter((item) => item.approval_id !== payload.approval_id),
          resolvedApprovals: upsertBy(
            get().resolvedApprovals,
            toResolvedApproval(payload, pending),
            (item) => item.approval_id === payload.approval_id,
          ),
        });
        break;
      }
      case "remote.control_changed": {
        set({ remoteControl: event.payload as unknown as RemoteControlState });
        break;
      }
      case "voice.playback_interrupted": {
        // 被打断的朗读本地随之停止，迟到分片由终态集合挡住；打断记录供页面展示。
        const payload = event.payload as {
          conversation_id: string;
          message_id: string | null;
          reason: string;
        };
        console.warn("朗读被打断", payload);
        const lastInterruption: MobilePlaybackInterruption = {
          conversationId: payload.conversation_id,
          messageId: payload.message_id,
          reason: payload.reason,
        };
        const voice = get().voice;
        const interruptedId = payload.message_id;
        if (interruptedId === null) {
          set({ voice: { ...voice, lastInterruption } });
          break;
        }
        stoppedOrTerminalMessages.add(interruptedId);
        endedTtsMessages.delete(interruptedId);
        const ttsChunks = { ...voice.ttsChunks };
        delete ttsChunks[interruptedId];
        set({
          voice: {
            ...voice,
            ttsChunks,
            playback: voice.playback.messageId === interruptedId ? IDLE_PLAYBACK : voice.playback,
            lastInterruption,
          },
        });
        break;
      }
      case "message.created":
      case "message.status_changed": {
        // message.created 给可朗读的角色回复附带 tts_ready（服务端能否真实合成）。
        // 状态变化按 message_id 原位替换，时间线位置不变。
        const payload = event.payload as { message: Message; tts_ready?: boolean };
        const message =
          payload.tts_ready === undefined
            ? payload.message
            : { ...payload.message, tts_ready: payload.tts_ready };
        if (message.conversation_id !== get().activeConversationId) break;
        if (
          event.event === "message.created" &&
          message.source === "character" &&
          message.tts_ready !== false
        ) {
          preemptPlayback(message.message_id);
        }
        set({
          messages: upsertBy(
            get().messages,
            message,
            (item) => item.message_id === message.message_id,
          ),
        });
        break;
      }
      case "message.delta": {
        const payload = event.payload as unknown as MessageDeltaPayload;
        if (payload.conversation_id !== get().activeConversationId) break;
        const existing = get().messages.find((item) => item.message_id === payload.message_id);
        if (!existing && payload.source === "character" && !isReasoningDelta(payload)) {
          preemptPlayback(payload.message_id);
        }
        const message = applyMessageDelta(existing, payload, {
          // 同步完成前聊天记录可能还没到。流式占位消息的 pair_id 不参与展示，
          // 定稿后 message.created 用完整记录替换它。
          pairId: get().conversationsById[payload.conversation_id]?.pair_id ?? "",
          createdAt: new Date().toISOString(),
        });
        set({
          messages: upsertBy(
            get().messages,
            message,
            (item) => item.message_id === message.message_id,
          ),
        });
        break;
      }
      case "message.finalized": {
        // 流式段结束：正文与思考都不再增长，思考缎带随之收起。
        const payload = event.payload as { conversation_id: string; message_id: string };
        if (payload.conversation_id !== get().activeConversationId) break;
        set({
          messages: get().messages.map((message) =>
            message.message_id === payload.message_id
              ? {
                  ...message,
                  streaming: false,
                  payload: { ...message.payload, reasoning_streaming: false },
                }
              : message,
          ),
        });
        break;
      }
      case "tool_run.upserted": {
        const { tool_run: toolRun } = event.payload as { tool_run: ToolRun };
        if (toolRun.conversation_id !== get().activeConversationId) break;
        set({
          toolRuns: upsertBy(
            get().toolRuns,
            toolRun,
            (item) => item.tool_call_id === toolRun.tool_call_id,
          ),
        });
        break;
      }
      case "voice.mobile_transcript": {
        const payload = event.payload as {
          conversation_id: string;
          session_id: string;
          text: string;
          is_final: boolean;
        };
        const voice = get().voice;
        if (payload.session_id !== voice.capture.sessionId) break;
        set({
          voice: {
            ...voice,
            transcript: { sessionId: payload.session_id, text: payload.text, isFinal: payload.is_final },
            capture: {
              state: payload.is_final ? "idle" : voice.capture.state,
              sessionId: payload.is_final ? null : voice.capture.sessionId,
              // is_final 事件先于 stop 响应到达；上行分片失败留下的错误保留到下一次启动。
              error: voice.capture.error,
            },
          },
        });
        break;
      }
      case "voice.mobile_asr_failed": {
        // 服务端放弃本次转写（如录音超时）：会话已关闭，录音状态退出并展示错误原文。
        const payload = event.payload as {
          conversation_id: string;
          session_id: string;
          code: string;
          error: string;
        };
        console.error("手机语音转写失败", payload);
        if (payload.session_id !== get().voice.capture.sessionId) break;
        set({
          voice: {
            ...get().voice,
            capture: { state: "idle", sessionId: null, error: payload.error },
          },
        });
        break;
      }
      case "voice.mobile_tts_chunk": {
        const payload = event.payload as unknown as MobileTtsChunkPayload;
        const messageId = payload.message_id;
        const current = get().voice.playback;
        if (
          stoppedOrTerminalMessages.has(messageId) ||
          (current.messageId === messageId &&
            (current.state === "failed" || current.state === "stopping"))
        ) {
          break;
        }
        preemptPlayback(messageId);
        const voice = get().voice;
        const ttsChunks = { ...voice.ttsChunks };
        const appended = appendTtsChunk(
          ttsChunks[messageId] ?? [],
          {
            seq: payload.seq,
            mime: payload.mime,
            data: payload.data,
            bytes: base64PcmByteLength(payload.data),
          },
          TTS_MAX_BUFFERED_PCM_BYTES,
        );
        if (appended.overflow) {
          // 整条播放失败并清空缓冲；迟到的分片与结束信号由终态集合挡住。
          stoppedOrTerminalMessages.add(messageId);
          endedTtsMessages.delete(messageId);
          delete ttsChunks[messageId];
          console.error(`手机端 PCM 缓冲超过上限（pcm_overflow），朗读已中止：message_id=${messageId}`);
          set({
            voice: {
              ...voice,
              playback: {
                messageId,
                state: "failed",
                error: `播放缓冲超过上限（${TTS_MAX_BUFFERED_PCM_BYTES} 字节，约 300 秒音频），已中止播放`,
                errorCode: "pcm_overflow",
              },
              ttsChunks,
            },
          });
          requestTtsStop(messageId);
          break;
        }
        ttsChunks[messageId] = appended.chunks;
        const isCurrent = voice.playback.messageId === messageId;
        set({
          voice: {
            ...voice,
            playback: isCurrent
              ? voice.playback
              : {
                  messageId,
                  state: endedTtsMessages.has(messageId) ? "playing" : "buffering",
                  error: null,
                  errorCode: null,
                },
            ttsChunks,
            // 新一条朗读开始，上一次的打断提示随之失效。
            lastInterruption: isCurrent ? voice.lastInterruption : null,
          },
        });
        break;
      }
      case "voice.mobile_tts_failed": {
        // 供应商合成失败：退出播放状态并保留错误原文。
        const payload = event.payload as {
          conversation_id: string;
          message_id: string;
          error: string;
        };
        const messageId = payload.message_id;
        console.error("角色语音合成失败", messageId, payload.error);
        if (stoppedOrTerminalMessages.has(messageId)) break;
        stoppedOrTerminalMessages.add(messageId);
        endedTtsMessages.delete(messageId);
        const voice = get().voice;
        const ttsChunks = { ...voice.ttsChunks };
        delete ttsChunks[messageId];
        const affectsCurrent =
          voice.playback.messageId === null || voice.playback.messageId === messageId;
        set({
          voice: {
            ...voice,
            ttsChunks,
            playback: affectsCurrent
              ? nextQueuedPlayback(ttsChunks, {
                  messageId,
                  state: "failed",
                  error: payload.error,
                  errorCode: null,
                })
              : voice.playback,
          },
        });
        break;
      }
      case "voice.mobile_tts_end": {
        // 整体结束信号：真正收尾要等播放引擎把最后一个分片播完。
        const { message_id: messageId } = event.payload as {
          conversation_id: string;
          message_id: string;
        };
        const voice = get().voice;
        if (
          stoppedOrTerminalMessages.has(messageId) ||
          (voice.playback.messageId === messageId &&
            (voice.playback.state === "failed" || voice.playback.state === "stopping"))
        ) {
          break;
        }
        endedTtsMessages.add(messageId);
        if (voice.playback.messageId === messageId) {
          set({
            voice: {
              ...voice,
              playback: { messageId, state: "playing", error: null, errorCode: null },
            },
          });
        }
        break;
      }
      case "power.status_changed": {
        // 载荷与 power.get_status 结果同形，由 Sidecar 推导，手机端原样展示。
        set({ powerStatus: event.payload as unknown as PowerStatusPayload });
        break;
      }
      case "task.busy_changed": {
        // active_tasks 是事件发生后的完整集合，整体替换；activeTask 是其中当前聊天的条目。
        const { active_tasks: activeTasks } = event.payload as { active_tasks: ActiveTask[] };
        const activeConversationId = get().activeConversationId;
        set({
          activeTasks,
          activeTask:
            activeTasks.find((task) => task.conversation_id === activeConversationId) ?? null,
        });
        break;
      }
      case "queue.changed": {
        // 某个聊天的排队项全量快照；其他聊天的队列在打开时由 conversation.open 带回。
        const payload = event.payload as { conversation_id: string; items: QueueItem[] };
        if (payload.conversation_id !== get().activeConversationId) break;
        set({ queueItems: visibleQueueItems(payload.items) });
        break;
      }
      case "diagnostic.warning":
        console.warn("引擎诊断告警", event.payload);
        break;
      default:
        break;
    }
  };

  /** 发消息或开始按住说话前停止本机全部朗读；停止失败时抛出。 */
  const stopLocalPlayback = async (): Promise<void> => {
    const voice = get().voice;
    const playing =
      voice.playback.messageId &&
      (voice.playback.state === "buffering" || voice.playback.state === "playing")
        ? [voice.playback.messageId]
        : [];
    const messageIds = [...new Set([...playing, ...Object.keys(voice.ttsChunks)])];
    await Promise.all(messageIds.map((messageId) => get().stopVoicePlayback(messageId)));
  };

  return {
    connection: "disconnected",
    authFailureReason: null,
    deviceName: getStoredDeviceName(),
    activeConversationId: null,
    ...initialSessionState(detectVoiceAvailability()),

    start() {
      if (wired) return;
      wired = true;
      client.onStateChange((connection) => {
        const reason = connection === "auth_failed" ? client.getAuthFailureReason() : null;
        // 令牌过期时客户端已清除凭据：设备名随之清空，路由守卫回到配对页。
        const expired = reason === "expired_token";
        set({ connection, authFailureReason: reason, ...(expired ? { deviceName: null } : {}) });
        if (connection === "disconnected" || connection === "reconnecting" || connection === "unreachable") {
          bootstrapGeneration += 1;
          bootstrapping = null;
          set({ bootstrapped: false });
        }
        if (connection === "connected" && getStoredToken() && !releasingControl) {
          void bootstrap().catch(reportBootstrapFailure);
        }
        if (expired) navigate({ name: "pair" }, { replace: true });
      });
      client.onEvent(handleEvent);
      // 回前台：connected 时重新 bootstrap 覆盖本地快照；unreachable 由客户端复位重连，连上后自会 bootstrap。
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") return;
        if (client.notifyAppForeground() === "resync") {
          void bootstrap().catch(reportBootstrapFailure);
        }
      });
      client.connect();
    },

    reconnect() {
      // client.disconnect() 复位退避计数，随后从第一档重新连接。
      client.disconnect();
      client.connect();
    },

    async retrySync() {
      await bootstrap();
    },

    async pairDevice(code, deviceName) {
      // 配对总在新连接上进行：旧连接可能已绑定失效 token（服务端不允许同一连接切换身份）。
      // 先清旧凭据，新连接建立时不会拿它自动 bootstrap。
      clearCredentials();
      set({ authFailureReason: null });
      client.disconnect();
      client.connect();
      await waitForConnected();
      const result = await client.request<{ token: string }>(
        "remote.pair",
        { code, device_name: deviceName },
        { skipAuth: true },
      );
      saveCredentials(result.token, deviceName);
      set({ deviceName });
      await bootstrap();
    },

    async openConversation(conversationId) {
      const generation = ++openConversationGeneration;
      // 页面已切到目标聊天：装载失败也保持在这里，由 openError 提供重试。
      set({
        activeConversationId: conversationId,
        openError: null,
        messages: [],
        toolRuns: [],
        queueItems: [],
        pair: null,
        activeTask: null,
      });
      // 页面刷新直接落在聊天页时，装载可能先于 WS 握手完成。
      client.connect();
      let collector: ReturnType<typeof collectEvents> | null = null;
      let result: ConversationOpenResult;
      try {
        await waitForConnected();
        collector = collectEvents();
        result = await client.request<ConversationOpenResult>("conversation.open", {
          conversation_id: conversationId,
          view_id: mobileViewId,
        });
      } catch (error) {
        if (generation === openConversationGeneration) {
          set({
            openError: {
              conversationId,
              message: error instanceof Error ? error.message : String(error),
            },
          });
        }
        throw error;
      } finally {
        collector?.stop();
      }
      if (generation !== openConversationGeneration) return;
      const streamId = get().streamId;
      if (streamId !== null && result.stream_id !== streamId) {
        // 装载结果来自另一代次：整体重新同步，bootstrap 会重新装载当前聊天。
        void bootstrap().catch(reportBootstrapFailure);
        return;
      }
      applyConversationOpen(conversationId, result);
      replayEventsAfter(collector.events, result.sequence, result.stream_id);
    },

    async submitDelegation(conversationId, text) {
      await stopLocalPlayback();
      // 不带 mode：服务端按会话持久化的模式校验，手机上可能过时的模式不覆盖桌面切换。
      const receipt = await client.request<SubmitReceipt>("chat.submit", {
        conversation_id: conversationId,
        target: "assistant",
        text,
      });
      applySubmitReceipt(set, get, conversationId, receipt);
    },

    async submitMessage(conversationId, text) {
      await stopLocalPlayback();
      const receipt = await client.request<SubmitReceipt>("chat.submit", {
        conversation_id: conversationId,
        target: "character",
        text,
      });
      applySubmitReceipt(set, get, conversationId, receipt);
    },

    async withdrawQueueItem(queueItemId) {
      await client.request("queue.withdraw", { queue_item_id: queueItemId });
    },

    async editQueueItem(queueItemId, text) {
      await client.request("queue.edit", { queue_item_id: queueItemId, text });
    },

    async prioritizeQueueItem(queueItemId) {
      await client.request("queue.prioritize", { queue_item_id: queueItemId });
    },

    async setConversationMode(conversationId, mode) {
      // 不做乐观更新：conversation.changed 事件回来后 last_mode 才变化。
      await client.request("conversation.set_mode", {
        conversation_id: conversationId,
        mode,
      });
    },

    async setApprovalMode(projectId, mode) {
      // 以服务端返回的项目记录更新本地审批模式。
      const { project } = await client.request<{ project: Omit<ProjectRecord, "conversations"> }>(
        "project.update_settings",
        { project_id: projectId, approval_mode: mode },
      );
      set({
        projects: get().projects.map((item) =>
          item.project_id === project.project_id
            ? { ...item, approval_mode: project.approval_mode }
            : item,
        ),
      });
    },

    async resolveApproval(approvalId, decision) {
      try {
        await client.request("approval.resolve", { approval_id: approvalId, decision });
      } catch (error) {
        if (error instanceof RemoteCommandError && error.code === "approval_already_resolved") {
          // 双端并发裁决：details 与 approval.resolved 载荷同形，按先到者的终态收敛；
          // 事件已先到时以事件记录为准。
          const recorded = get().resolvedApprovals.some((item) => item.approval_id === approvalId);
          const pending = get().approvals.find((item) => item.approval_id === approvalId);
          set({
            approvals: get().approvals.filter((item) => item.approval_id !== approvalId),
            resolvedApprovals: recorded
              ? get().resolvedApprovals
              : [
                  ...get().resolvedApprovals,
                  toResolvedApproval(error.details as unknown as ApprovalResolvedPayload, pending),
                ],
          });
        }
        throw error;
      }
    },

    async disconnect() {
      bootstrapGeneration += 1;
      openConversationGeneration += 1;
      bootstrapping = null;
      releasingControl = true;
      try {
        // auth_failed 时凭据已失效，服务端不会接受释放请求；撤销流程已同步清除控制资格。
        if (getStoredToken() && client.getState() !== "auth_failed") {
          client.connect();
          await waitForConnected();
          try {
            await client.request("remote.release_control");
          } catch (error) {
            // 已撤销的凭证无法释放；服务端撤销流程已同步清除控制资格。
            if (!(error instanceof RemoteCommandError) || error.code !== "unauthorized") throw error;
          }
        }
      } finally {
        releasingControl = false;
      }
      eventCollectors.clear();
      client.disconnect();
      clearCredentials();
      stoppedOrTerminalMessages.clear();
      endedTtsMessages.clear();
      set({
        connection: "disconnected",
        authFailureReason: null,
        deviceName: null,
        activeConversationId: null,
        ...initialSessionState(get().voice.availability),
      });
    },

    async startVoiceCapture(conversationId) {
      const voice = get().voice;
      if (voice.capture.state !== "idle") {
        // 前置条件违反：原因写进 capture.error 再抛出，界面能看到这次按压为什么没有开始。
        const message = "语音采集正在进行中";
        set({
          voice: {
            ...voice,
            capture: { ...voice.capture, error: message },
          },
        });
        throw new Error(message);
      }
      set({
        voice: {
          ...voice,
          capture: { state: "starting", sessionId: null, error: null },
          transcript: null,
        },
      });
      try {
        // 开始说话前先停本机朗读，避免麦克风录进角色语音。
        await stopLocalPlayback();
        const result = await client.request<{ session_id: string }>("voice.mobile_ptt_start", {
          conversation_id: conversationId,
        });
        set({
          voice: {
            ...get().voice,
            capture: { state: "recording", sessionId: result.session_id, error: null },
          },
        });
        return result;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        set({
          voice: {
            ...get().voice,
            capture: { state: "idle", sessionId: null, error: message },
          },
        });
        throw error;
      }
    },

    async sendAudioChunk(seq, base64) {
      const sessionId = get().voice.capture.sessionId;
      if (!sessionId) throw new Error("未开始语音采集");
      try {
        await client.request("voice.mobile_audio_chunk", {
          session_id: sessionId,
          seq,
          data: base64,
        });
      } catch (error) {
        // 上行分片失败（如 voice_audio_seq_gap）写入 capture.error，hook 随后的停止动作不会清掉它。
        const message = error instanceof Error ? error.message : String(error);
        set({
          voice: {
            ...get().voice,
            capture: { ...get().voice.capture, error: message },
          },
        });
        throw error;
      }
    },

    async stopVoiceCapture(explicitSessionId?: string) {
      // 显式 sessionId 会覆盖 store 里的值：启动在途被取消时，会话可能刚建立、
      // 也可能已被别的启动改写，补发停止必须打向本次启动拿到的那一个。
      const sessionId = explicitSessionId ?? get().voice.capture.sessionId;
      if (!sessionId) return;
      // 服务端 end_session 先发 is_final 事件、后返回 stop 响应，这个窗口里 store 可能
      // 已被事件置 idle，用户也可能已经建起新会话。旧会话的迟到响应若无条件写 capture，
      // 会把新会话抹成 idle/null，新会话的服务端会话因此泄漏到 watchdog。
      // 所以每次写 capture 前都确认目标会话仍是当前会话；不一致只发请求、不写状态。
      const stillCurrent = () => get().voice.capture.sessionId === sessionId;
      if (stillCurrent()) {
        set({
          voice: {
            ...get().voice,
            // error 原样保留：上行分片失败（如 voice_audio_seq_gap）留下的错误
            // 必须留到用户看见，停止动作本身不构成「错误已消解」的证据。
            capture: { ...get().voice.capture, state: "stopping", sessionId },
          },
        });
      }
      try {
        const result = await client.request<{
          session_id: string;
          transcript: string;
          conversation_id: string;
        }>("voice.mobile_ptt_stop", { session_id: sessionId });
        // 停止成功即复位：停响应本身携带最终转写全文，与 is_final 事件路径等价，
        // 事件丢失时 capture 也不会停在 stopping。
        if (stillCurrent()) {
          set({
            voice: {
              ...get().voice,
              // error 同样保留（见上）：停止成功只说明会话结束了，
              // 不代表本次采集过程中出现过的上行失败没发生过。
              capture: { state: "idle", sessionId: null, error: get().voice.capture.error },
              transcript: {
                sessionId,
                text: result.transcript,
                isFinal: true,
              },
            },
          });
        }
        // 身份不一致：新会话已接管，本次响应只说明旧会话确实关掉了，
        // 不复位、也不把旧会话的转写盖到新会话的界面上。
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error("语音会话停止失败", sessionId, error);
        if (stillCurrent()) {
          set({
            voice: {
              ...get().voice,
              // 本次采集已记录的错误（麦克风、引擎、分片上行）是根因，停止失败
              // （如空会话的 voice_transcript_empty）只是后果，不覆盖根因。
              capture: {
                state: "idle",
                sessionId: null,
                error: get().voice.capture.error ?? message,
              },
            },
          });
        } else {
          // 新会话已接管：只写入 error，不动新会话的 state 与 sessionId。
          set({
            voice: {
              ...get().voice,
              capture: { ...get().voice.capture, error: message },
            },
          });
        }
        throw error;
      }
    },

    reportVoiceCaptureError(message) {
      set({
        voice: {
          ...get().voice,
          capture: { ...get().voice.capture, error: message },
        },
      });
    },

    async stopVoicePlayback(messageId) {
      stoppedOrTerminalMessages.add(messageId);
      endedTtsMessages.delete(messageId);
      const voice = get().voice;
      const ttsChunks = { ...voice.ttsChunks };
      delete ttsChunks[messageId];
      set({
        voice: {
          ...voice,
          ttsChunks,
          // 只有正在播放的就是这条时才进入 stopping。
          playback:
            voice.playback.messageId === messageId
              ? { messageId, state: "stopping", error: null, errorCode: null }
              : voice.playback,
        },
      });
      let failure: MobileVoicePlayback | undefined;
      try {
        await client.request("voice.mobile_tts_stop", { message_id: messageId });
      } catch (error) {
        failure = {
          messageId,
          state: "failed",
          error: error instanceof Error ? error.message : String(error),
          errorCode: null,
        };
        throw error;
      } finally {
        // 等待期间已切到别的朗读时不改写它的状态。
        const current = get().voice;
        if (current.playback.messageId === messageId) {
          set({ voice: { ...current, playback: nextQueuedPlayback(current.ttsChunks, failure) } });
        }
      }
    },

    finishVoicePlayback(messageId) {
      stoppedOrTerminalMessages.add(messageId);
      endedTtsMessages.delete(messageId);
      const voice = get().voice;
      if (voice.playback.messageId !== messageId) return;
      if (voice.playback.state === "stopping") return;
      const nextChunks = { ...voice.ttsChunks };
      delete nextChunks[messageId];
      set({
        voice: {
          ...voice,
          playback: nextQueuedPlayback(nextChunks),
          ttsChunks: nextChunks,
        },
      });
    },

    releaseTtsChunksUpTo(messageId, uptoSeq) {
      const voice = get().voice;
      const chunks = voice.ttsChunks[messageId];
      if (!chunks) return;
      const remaining = chunks.filter((item) => item.seq > uptoSeq);
      if (remaining.length === chunks.length) return;
      const nextChunks = { ...voice.ttsChunks };
      if (remaining.length === 0) {
        delete nextChunks[messageId];
      } else {
        nextChunks[messageId] = remaining;
      }
      set({
        voice: {
          ...voice,
          ttsChunks: nextChunks,
        },
      });
    },

    failVoicePlayback(messageId, error, errorCode) {
      stoppedOrTerminalMessages.add(messageId);
      endedTtsMessages.delete(messageId);
      console.error("语音播放失败", messageId, error);
      const voice = get().voice;
      if (voice.playback.messageId !== messageId || voice.playback.state === "stopping") return;
      // 该消息的分片已不可用，随失败一并清理。
      const ttsChunks = { ...voice.ttsChunks };
      delete ttsChunks[messageId];
      set({
        voice: {
          ...voice,
          playback: nextQueuedPlayback(ttsChunks, { messageId, state: "failed", error, errorCode }),
          ttsChunks,
        },
      });
    },

    async refreshVoiceAvailability() {
      set({
        voice: {
          ...get().voice,
          availability: {
            secureContext: window.isSecureContext,
            micPermission: await queryMicPermission(),
            supported: microphoneSupported(),
          },
        },
      });
    },
  };
});

/**
 * 麦克风授权状态。Permissions API 不支持 "microphone" 名称的浏览器（如 Firefox）
 * 会拒绝查询，此时记为 unknown，能否录音由 getUserMedia 的结果决定。
 */
async function queryMicPermission(): Promise<MobileVoiceAvailability["micPermission"]> {
  if (!navigator.permissions) return "unknown";
  try {
    const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
    return status.state;
  } catch (error) {
    console.warn("浏览器不支持查询麦克风授权状态", error);
    return "unknown";
  }
}

/** 全应用共用的 WS 客户端；通知引擎直接订阅它的事件流。 */
export const mobileWsClient = client;
