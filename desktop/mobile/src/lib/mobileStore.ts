import { create } from "zustand";
import type {
  ActiveTask,
  ApprovalMode,
  ApprovalResolvedPayload,
  ConversationMode,
  ConversationOpenResult,
  ConversationRecord,
  ConversationSummary,
  DesktopSnapshot,
  Message,
  PairMemory,
  QueueItem,
  PairRecord,
  PendingApproval,
  PowerStatusPayload,
  ProjectRecord,
  RemoteControlState,
  ToolRun,
  Turn,
} from "@shared/contracts/protocol";
import type { MobileConnectionState, WireEvent } from "./wsClient";
import {
  clearCredentials,
  getStoredDeviceName,
  getStoredToken,
  MobileWsClient,
  RemoteCommandError,
  saveCredentials,
} from "./wsClient";

/**
 * 手机端业务 store：统一归并连接代次、事件序号、会话消息、工具与审批状态。
 * 序号缺口或连接代次变化时重新 bootstrap，不猜测缺失状态。
 */

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
  /**
   * V0.3.9 §6：真实失败码（如 pcm_overflow）；无失败为 null，不伪造。
   * 可选以兼容既有 UI 测试构造的字面量，store 内部始终显式写入。
   */
  errorCode?: string | null;
}

export interface MobileVoiceAvailability {
  secureContext: boolean;
  micPermission: "unknown" | "granted" | "denied" | "prompt";
  supported: boolean;
}

/** 下行 TTS 分片（``voice.mobile_tts_chunk`` payload 的缓冲形态）。 */
export interface MobileTtsChunk {
  seq: number;
  mime: string;
  data: string;
  /** 解码后 PCM 字节数（容量核算用，避免重复解码）。 */
  bytes: number;
}

/** 服务端下行 PCM 规格：24kHz mono s16le（2 字节/采样）。 */
const TTS_SAMPLE_RATE = 24000;
const TTS_BYTES_PER_SAMPLE = 2;

/**
 * V0.3.8：未播分片缓冲上限 ≈ 300 秒音频（14.4MB），防长回复内存尖峰。
 * 正常播放边收边放只留网络突发量；超限见于播放停滞/结束信号丢失等异常。
 */
export const TTS_MAX_BUFFERED_PCM_BYTES = TTS_SAMPLE_RATE * TTS_BYTES_PER_SAMPLE * 300;

/** 标准 base64 长度换算解码后字节数（仅容量核算，不解码）。 */
export function base64PcmByteLength(base64: string): number {
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.floor((base64.length * 3) / 4) - padding;
}

/**
 * V0.3.9 契约 §6：有界追加 TTS 分片。
 *
 * 超过上限时**不再丢弃旧分片后继续播放**——整条播放必须进入 failed
 * （error_code=pcm_overflow）。这里只负责判定：返回 overflow=true 时调用方
 * 必须清空该消息缓冲、记录终态并请求服务端停止合成。
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
  deviceName: string | null;
  projects: ProjectRecord[];
  conversationsById: Record<string, ConversationRecord>;
  activeConversationId: string | null;
  messages: Message[];
  toolRuns: ToolRun[];
  /** V0.3.8 T5（契约 §14.1）：活跃会话的排队项（queue.changed/快照驱动），
      忙时消息可见、可撤回/编辑/置顶。 */
  queueItems: QueueItem[];
  approvals: PendingApproval[];
  /** V0.3.5：已决审批记录（含 resolved_by/decision），供 UI 表达双端仲裁结果。 */
  resolvedApprovals: Array<{
    approval_id: string;
    conversation_id?: string;
    decision: string;
    resolved_by: string;
    task_id?: string;
    /** 保留原始 operation/reason 以便已决卡仍展示详情。 */
    operation?: PendingApproval["operation"];
    reason?: string;
    /** V0.3.9 §6：真实失败码（timeout 等）；无则为 null。 */
    error_code?: string | null;
    resolved_at?: string | null;
  }>;
  /** V0.3.4：当前配对（委派卡「来自 <角色名> 的委派」数据源）。 */
  pair: PairRecord | null;
  /** V0.3.4：当前活动任务（委派卡运行状态与 delegation_id 对齐）。 */
  activeTask: ActiveTask | null;
  /** V0.3.9 §3：全账号活动任务权威集合；activeTask 只是当前会话的视图。 */
  activeTasks: ActiveTask[];
  /** V0.3.9 §3：按 conversation_id 存放的回合（turn.started/turn.status_changed）。 */
  turnsByConversation: Record<string, Turn[]>;
  /** V0.3.9 §2：当前或最新装载的摘要列表（便于组件与测试消费）。 */
  summaries: ConversationSummary[];
  /** V0.3.9 §2：按 conversation_id 存放的摘要记录（摘要键只含 conversation_id）。 */
  summariesByConversation: Record<string, ConversationSummary[]>;
  /** V0.3.9 §2：配对长期记忆（服务端按冻结作用域过滤后下发）。 */
  memories: PairMemory[];
  /** V0.3.9 §6：远程控制租约；无数据保持 null，不本地推导。 */
  remoteControl: RemoteControlState | null;
  streamId: string | null;
  lastSequence: number;
  bootstrapped: boolean;
  /** V0.3.7：桌面端电源状态（power.status_changed 事件驱动；无数据时为 null，不本地推导）。 */
  powerStatus: PowerStatusPayload | null;
    /** V0.3.5：手机语音状态。 */
    voice: {
      capture: MobileVoiceCapture;
      transcript: MobileVoiceTranscript | null;
      playback: MobileVoicePlayback;
      availability: MobileVoiceAvailability;
      /** 下行 TTS 分片缓冲：message_id → 有序分片（有界，见 TTS_MAX_BUFFERED_PCM_BYTES）。 */
      ttsChunks: Record<string, MobileTtsChunk[]>;
      /**
       * V0.3.9：PCM 溢出改为整条播放失败，不再丢分片继续播放，因此本计数不再写入。
       * 字段保留为可选仅为兼容既有 UI 测试的字面量，后续版本可随 UI 一并删除。
       */
      ttsDroppedChunks?: Record<string, number>;
    };

  start: () => void;
  /** 手动重连入口（unreachable/auth_failed 后由 UI 重试按钮调用）。 */
  reconnect: () => void;
  pairDevice: (code: string, deviceName: string) => Promise<void>;
  openConversation: (conversationId: string) => Promise<void>;
  submitDelegation: (text: string) => Promise<void>;
  /** V0.3.4 缺陷 3：手机端普通角色消息输入（target=character，任何模式可用）。 */
  submitMessage: (text: string) => Promise<void>;
  /** V0.3.8 T5：队列三命令——撤回 / 编辑文本 / 置顶（仅 queued 项）。 */
  withdrawQueueItem: (queueItemId: string) => Promise<void>;
  editQueueItem: (queueItemId: string, text: string) => Promise<void>;
  prioritizeQueueItem: (queueItemId: string) => Promise<void>;
  /** V0.3.4 缺陷 4：会话模式切换（chat/collaboration），委派仅在协作模式可用。 */
  setConversationMode: (conversationId: string, mode: ConversationMode) => Promise<void>;
  resolveApproval: (approvalId: string, decision: string) => Promise<void>;
  /** V0.3.5：切换项目审批模式（request_approval 请求批准 / review 帮我审核 / full_auto 完全允许运行）。 */
  setApprovalMode: (projectId: string, mode: ApprovalMode) => Promise<void>;
  /** V0.3.5：手机语音相关 actions。 */
  startVoiceCapture: (conversationId: string) => Promise<{ session_id: string }>;
  sendAudioChunk: (seq: number, base64: string) => Promise<void>;
  stopVoiceCapture: () => Promise<void>;
  stopVoicePlayback: (messageId: string) => Promise<void>;
  /** V0.3.5：本地 TTS 队列自然播放到末尾后复位 playback 状态。 */
  finishVoicePlayback: (messageId: string) => void;
  /** V0.3.8：分片已解码移交播放引擎（≤ uptoSeq），从 store 释放。 */
  releaseTtsChunksUpTo: (messageId: string, uptoSeq: number) => void;
  /** V0.3.8：播放引擎异常（resume 失败/结束信号超时）如实置 failed 并保留错误。
      V0.3.9 §6：errorCode 携带真实失败码（pcm_overflow 等），无则为 null。 */
  failVoicePlayback: (messageId: string, error: string, errorCode?: string | null) => void;
  /** V0.3.9 §6：查询远程控制租约（remote.control_status 只读查询）。 */
  refreshRemoteControl: () => Promise<void>;
  /** V0.3.9 §2：查询当前会话摘要（summary.get 只读查询）。 */
  loadSummaries: (conversationId?: string) => Promise<void>;
  /** V0.3.9 §2：查询当前会话可见的配对记忆（memory.list 只读查询）。 */
  loadMemories: (conversationId?: string) => Promise<void>;
  refreshVoiceAvailability: () => Promise<void>;
  disconnect: () => Promise<void>;
}

const client = new MobileWsClient();
const mobileViewId =
  typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? `mobile-${crypto.randomUUID()}`
    : `mobile-${Date.now().toString(36)}`;

function indexConversations(projects: ProjectRecord[]): Record<string, ConversationRecord> {
  const map: Record<string, ConversationRecord> = {};
  for (const project of projects) {
    for (const conversation of project.conversations ?? []) {
      map[conversation.conversation_id] = conversation;
    }
  }
  return map;
}

/** V0.3.8 T5：chat.submit 的排队回执（忙时 accepted=false→queued=true）。 */
interface SubmitReceipt {
  queued?: boolean;
  queue_item?: QueueItem;
}

function applySubmitReceipt(
  set: (partial: Partial<MobileState>) => void,
  get: () => MobileState,
  conversationId: string,
  receipt: SubmitReceipt,
): void {
  if (receipt.queued !== true || !receipt.queue_item) return;
  if (receipt.queue_item.conversation_id !== conversationId) return;
  if (get().activeConversationId !== conversationId) return;
  const existing = get().queueItems;
  if (existing.some((item) => item.queue_item_id === receipt.queue_item!.queue_item_id)) return;
  set({ queueItems: [...existing, receipt.queue_item] });
}

/** V0.3.9 §2：快照/装载的摘要按 conversation_id 归组（同一 summary_id 后到覆盖）。 */
function snapshotSummaries(
  summaries: ConversationSummary[] | undefined,
): Record<string, ConversationSummary[]> {
  const grouped: Record<string, ConversationSummary[]> = {};
  for (const summary of summaries ?? []) {
    const list = grouped[summary.conversation_id] ?? [];
    grouped[summary.conversation_id] = [
      ...list.filter((item) => item.summary_id !== summary.summary_id),
      summary,
    ];
  }
  return grouped;
}

/**
 * V0.3.9 §6：租约快照的 null 归一化——state 缺失或非法时整体为 null，
 * 不伪造 free；其余字段缺什么就是 null。
 */
function normalizeRemoteControl(value: unknown): RemoteControlState | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const state = raw.state;
  if (state !== "free" && state !== "held" && state !== "grace") return null;
  const asStringOrNull = (input: unknown): string | null =>
    typeof input === "string" && input.length > 0 ? input : null;
  return {
    state,
    device_key: asStringOrNull(raw.device_key),
    expires_at: asStringOrNull(raw.expires_at),
    grace_expires_at: asStringOrNull(raw.grace_expires_at),
    reason: asStringOrNull(raw.reason),
  };
}

function applySnapshot(
  set: (partial: Partial<MobileState>) => void,
  snapshot: DesktopSnapshot,
  get: () => MobileState,
): void {
  // 手机当前会话上下文（委派卡的角色名与运行状态）必须与会话对齐：全局快照
  // 的 pair/active_task 属于桌面当前会话，不能覆盖本会话（V0.3.4 Codex 建议 B）。
  // 有打开的会话时，只从快照的全量集合（pairs / active_tasks）按当前会话重新选择；
  // 快照不携带本会话信息时保留现状，不跨会话覆盖、也不臆测为 null。
  const activeConvId = get().activeConversationId;
  const activeConv =
    typeof activeConvId === "string" && activeConvId
      ? get().conversationsById[activeConvId] ||
        indexConversations(snapshot.projects)[activeConvId]
      : null;
  const activePairId = activeConv?.pair_id;

  let pair: PairRecord | null = get().pair;
  let activeTask: ActiveTask | null = get().activeTask;
  if (!activeConvId) {
    // 尚未打开会话：直接采用全局快照的配对与全局活动任务。
    pair = snapshot.pair;
    activeTask = snapshot.active_task;
  } else {
    if (activePairId) {
      const selected = snapshot.pairs?.find((p) => p.pair_id === activePairId);
      pair =
        selected ??
        (snapshot.pair?.pair_id === activePairId ? snapshot.pair : get().pair);
    }
    if (Array.isArray(snapshot.active_tasks)) {
      activeTask =
        snapshot.active_tasks.find((t) => t.conversation_id === activeConvId) ?? null;
    } else if (snapshot.active_task?.conversation_id === activeConvId) {
      activeTask = snapshot.active_task;
    }
  }

  const snapshotConversationId = snapshot.current_conversation_id || null;
  const snapshotMatchesActive = !activeConvId || snapshotConversationId === activeConvId;
  const messages = snapshotMatchesActive ? snapshot.messages : get().messages;
  const toolRuns = snapshotMatchesActive ? snapshot.tool_runs : get().toolRuns;
  // V0.3.8 T5：快照 queue_items 属于快照当前会话；不匹配本会话时不覆盖。
  const queueItems = snapshotMatchesActive
    ? snapshot.queue_items.filter((item) => item.status === "queued")
    : get().queueItems;

  // V0.3.9 §3：全账号活动任务集合与回合按会话存放，activeTask 只是当前会话视图。
  const activeTasks = Array.isArray(snapshot.active_tasks)
    ? snapshot.active_tasks
    : snapshot.active_task
      ? [snapshot.active_task]
      : [];
  const turnsByConversation: Record<string, Turn[]> = {};
  for (const turn of snapshot.turns ?? []) {
    (turnsByConversation[turn.conversation_id] ??= []).push(turn);
  }
  set({
    projects: snapshot.projects,
    conversationsById: indexConversations(snapshot.projects),
    messages,
    toolRuns,
    queueItems,
    approvals: snapshot.approvals,
    pair,
    activeTask,
    activeTasks,
    turnsByConversation,
    // V0.3.9 §2/§6：摘要、记忆与租约随快照替换；缺字段即空/ null，不沿用旧值。
    summaries: snapshot.summaries ?? [],
    summariesByConversation: snapshotSummaries(snapshot.summaries),
    memories: snapshot.memories ?? [],
    remoteControl: normalizeRemoteControl(snapshot.remote_control),
    streamId: snapshot.stream_id == null ? get().streamId : String(snapshot.stream_id),
    lastSequence: snapshot.sequence,
    bootstrapped: true,
  });
}

const stoppedOrTerminalMessages = new Set<string>();
const endedTtsMessages = new Set<string>();

/** 测试专用：复位语音终态与结束信号集合，隔离用例间的模块级状态。 */
export function resetVoiceTerminalStateForTests(): void {
  stoppedOrTerminalMessages.clear();
  endedTtsMessages.clear();
}

/** V0.3.9 §2：当前会话的摘要（其他聊天的摘要不跨会话展示）。 */
export const selectMobileSummaries = (state: MobileState): ConversationSummary[] =>
  state.activeConversationId
    ? (state.summariesByConversation[state.activeConversationId] ?? [])
    : [];

/** V0.3.9 §2：仍在生效的配对记忆（deleted 记录不展示）。 */
export const selectMobileActiveMemories = (state: MobileState): PairMemory[] =>
  state.memories.filter((item) => item.status === "active");

export const useMobileStore = create<MobileState>((set, get) => {
  let wired = false;
  let bootstrapping: Promise<void> | null = null;
  let bootstrapGeneration = 0;
  let releasingControl = false;
  let openConversationGeneration = 0;
  let stableConversationView: Pick<
    MobileState,
    "activeConversationId" | "messages" | "toolRuns" | "pair" | "activeTask"
  > | null = null;
  const eventCollectors = new Set<WireEvent[]>();
  const nextQueuedPlayback = (
    chunks: Record<string, MobileTtsChunk[]>,
    fallback: MobileVoicePlayback = { messageId: null, state: "idle", error: null, errorCode: null },
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
      : fallback;
  };

  /**
   * V0.3.8 修复：新消息回答出现时，主动打断并截断前序正在播放的旧语音。
   * 清除本地分片缓冲并向服务端发送 voice.mobile_tts_stop 终止旧合成任务。
   */
  const preemptOldPlayback = (newMessageId: string): void => {
    const currentVoice = get().voice;
    const activeMsgId = currentVoice.playback.messageId;
    if (
      !activeMsgId ||
      activeMsgId === newMessageId ||
      (currentVoice.playback.state !== "buffering" && currentVoice.playback.state !== "playing")
    ) {
      return;
    }
    stoppedOrTerminalMessages.add(activeMsgId);
    endedTtsMessages.delete(activeMsgId);
    void client.request("voice.mobile_tts_stop", { message_id: activeMsgId }).catch(() => {});
    const nextChunks = { ...currentVoice.ttsChunks };
    delete nextChunks[activeMsgId];
    set({
      voice: {
        ...currentVoice,
        playback: { messageId: null, state: "idle", error: null, errorCode: null },
        ttsChunks: nextChunks,
      },
    });
  };

  /** connect() 只发起握手；pair 等调用必须等 connected 后才能发请求。 */
  const waitForConnected = (timeoutMs = 10_000): Promise<void> => {
    if (client.getState() === "connected") return Promise.resolve();
    // V0.3.8 D4：若处于 auth_failed，但底层 socket 物理连接仍为 OPEN，
    // 对于 remote.pair 等免鉴权请求物理链路可用，立即放行，杜绝配对按钮永久挂起。
    if (client.getState() === "auth_failed" && client.isSocketConnected()) {
      return Promise.resolve();
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
        if (connection === "auth_failed" && client.isSocketConnected()) {
          cleanup();
          resolve();
        }
        if (connection === "unreachable" || connection === "disconnected") {
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

  const replayEventsAfter = (
    events: WireEvent[],
    sequence: number,
    streamId: string | null,
  ): void => {
    events
      .filter((event) => {
        const eventStream = event.stream_id == null ? null : String(event.stream_id);
        return event.sequence > sequence && (!streamId || !eventStream || eventStream === streamId);
      })
      .sort((left, right) => left.sequence - right.sequence)
      .forEach((event) => handleEvent(event, true));
  };

  const reportBootstrapFailure = (error: unknown): void => {
    console.error("手机端状态同步失败", error);
  };

  const bootstrap = async (): Promise<void> => {
    if (releasingControl) return;
    if (bootstrapping) return bootstrapping;
    const generation = ++bootstrapGeneration;
    set({ bootstrapped: false });
    const activeConversationId = get().activeConversationId;
    const collector = collectEvents();
    let tracked: Promise<void>;
    const request = (async () => {
      const snapshot = await client.request<DesktopSnapshot>("app.bootstrap");
      if (generation !== bootstrapGeneration) return;
      // 控制声明必须成功后才公布同步完成；活跃聊天重连也走同一条路径。
      await client.request("remote.claim_control");
      if (generation !== bootstrapGeneration) return;
      client.confirmAuthenticated();
      const snapshotStream =
        snapshot.stream_id == null ? null : String(snapshot.stream_id);
      // app.bootstrap 是新连接的权威基线；重连后即使旧 streamId 仍在本地，也采纳响应代次。
      if (snapshotStream && snapshotStream !== get().streamId) {
        openConversationGeneration += 1;
        stableConversationView = null;
        set({
          streamId: snapshotStream,
          lastSequence: -1,
          bootstrapped: false,
          messages: [],
          toolRuns: [],
          approvals: [],
          pair: null,
          activeTask: null,
          // 新 stream 属于桌面端新一轮会话：旧电源状态随之作废，
          // serve 启动时按冻结 §2.1 会重新 emit，之前不展示旧值。
          powerStatus: null,
        });
      }
      applySnapshot(set, snapshot, get);
      // V0.3.7 电源（Codex Review P2）：serve 启动时的 status_changed 只在
      // 已鉴权订阅之前 emit 一次，晚连手机收不到（无回放缓冲）——bootstrap
      // 完成后主动拉一次当前快照（power.get_status 幂等无副作用），晚连
      // 手机即可获得休眠风险提示；失败如实保留日志不阻塞 bootstrap。
      void client
        .request<PowerStatusPayload>("power.get_status")
        .then((status) => {
          if (
            generation === bootstrapGeneration &&
            typeof status.supported === "boolean" &&
            typeof status.at_risk === "boolean"
          ) {
            set({ powerStatus: status });
          }
        })
        .catch((error) => {
          console.warn("电源状态拉取失败（如实保留）", error);
        });
      if (activeConversationId && get().activeConversationId === activeConversationId) {
        let conversation: ConversationOpenResult;
        try {
          conversation = await client.request<ConversationOpenResult>("conversation.open", {
            conversation_id: activeConversationId,
            view_id: mobileViewId,
          });
        } catch (error) {
          if (generation === bootstrapGeneration) {
            set({ bootstrapped: false });
            replayEventsAfter(collector.events, get().lastSequence, get().streamId);
          }
          throw error;
        }
        if (generation !== bootstrapGeneration || get().activeConversationId !== activeConversationId) {
          replayEventsAfter(collector.events, get().lastSequence, get().streamId);
          return;
        }
        const conversationStream =
          conversation.stream_id == null ? get().streamId : String(conversation.stream_id);
        if (conversationStream && get().streamId && conversationStream !== get().streamId) {
          replayEventsAfter(collector.events, get().lastSequence, get().streamId);
          return;
        }
        set({
          messages: conversation.messages,
          toolRuns: conversation.tool_runs,
          queueItems: conversation.queue_items.filter((item) => item.status === "queued"),
          pair: conversation.pair,
          activeTask: conversation.active_task,
          // V0.3.9 §3：conversation.open 只带当前聊天的 active_task；全账号权威集合
          // 由 app.bootstrap / task.busy_changed 维护，这里只替换本会话条目。
          activeTasks: conversation.active_task
            ? [
                ...get().activeTasks.filter((task) => task.conversation_id !== activeConversationId),
                conversation.active_task,
              ]
            : get().activeTasks.filter((task) => task.conversation_id !== activeConversationId),
          turnsByConversation: {
            ...get().turnsByConversation,
            [activeConversationId]: conversation.turns ?? [],
          },
          // V0.3.9 §2/§6：只读装载显式下发时才覆盖摘要/记忆/租约。
          summaries: conversation.summaries ?? (get().summariesByConversation[activeConversationId] ?? []),
          summariesByConversation: conversation.summaries
            ? { ...get().summariesByConversation, [activeConversationId]: conversation.summaries }
            : get().summariesByConversation,
          memories: conversation.memories ?? get().memories,
          remoteControl:
            conversation.remote_control === undefined
              ? get().remoteControl
              : normalizeRemoteControl(conversation.remote_control),
          streamId: conversationStream,
          lastSequence: conversation.sequence,
          bootstrapped: true,
        });
        replayEventsAfter(collector.events, conversation.sequence, conversationStream);
        return;
      }
      replayEventsAfter(collector.events, snapshot.sequence, snapshotStream ?? get().streamId);
    })();
    tracked = request.catch((error: unknown) => {
      if (generation === bootstrapGeneration) set({ bootstrapped: false });
      throw error;
    }).finally(() => {
      collector.stop();
      if (bootstrapping === tracked) bootstrapping = null;
    });
    bootstrapping = tracked;
    return tracked;
  };

  handleEvent = (event: WireEvent, replaying = false): void => {
    const state = get();
    const eventStream = event.stream_id == null ? null : String(event.stream_id);
    if (eventStream && state.streamId && eventStream !== state.streamId) {
      bootstrapGeneration += 1;
      bootstrapping = null;
      eventCollectors.clear();
      openConversationGeneration += 1;
      stableConversationView = null;
      set({
        streamId: eventStream,
        lastSequence: -1,
        bootstrapped: false,
        messages: [],
        toolRuns: [],
        approvals: [],
        pair: null,
        activeTask: null,
        powerStatus: null,
      });
      void bootstrap().catch(reportBootstrapFailure);
    } else if (eventStream && !state.streamId) {
      set({ streamId: eventStream });
    }

    if (!replaying) {
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
        // 真实协议存在两种载荷：完整 {"conversation": record} 与仅
        // {"conversation_id": ...}（如归档其他会话的分支）。骨架只合并
        // 带完整 record 的分支；仅 id 形态不做本地猜测，等下次水合对齐。
        const conversation = (event.payload as { conversation?: ConversationRecord }).conversation;
        if (conversation) {
          set({
            conversationsById: { ...get().conversationsById, [conversation.conversation_id]: conversation },
          });
        }
        break;
      }
      case "approval.requested": {
        // 真实协议：payload 平铺即为 PendingApproval
        // （application_service 直接 emit approval_id/conversation_id/task_id/operation/reason），
        // 不是 {"approval": {...}} 嵌套。
        const approval = event.payload as unknown as PendingApproval;
        if (approval && approval.approval_id) {
          const rest = get().approvals.filter((item) => item.approval_id !== approval.approval_id);
          set({ approvals: [...rest, approval] });
        }
        break;
      }
      case "approval.resolved": {
        // V0.3.9 §6：终态统一为 allow|allow_for_conversation|deny|timeout，
        // resolved_by/actor/reason/error_code 缺失保持 null——绝不伪造成 remote。
        const payload = event.payload as Partial<ApprovalResolvedPayload>;
        if (payload.approval_id) {
          const existing = get().approvals.find((item) => item.approval_id === payload.approval_id);
          set({
            approvals: get().approvals.filter((item) => item.approval_id !== payload.approval_id),
            resolvedApprovals: [
              ...get().resolvedApprovals.filter((item) => item.approval_id !== payload.approval_id),
              {
                approval_id: payload.approval_id,
                conversation_id: payload.conversation_id ?? get().activeConversationId ?? undefined,
                // 缺失时不伪造方向，置空串由展示层给中性文案。
                decision: payload.decision ?? "",
                resolved_by: payload.resolved_by ?? "",
                task_id: payload.task_id ?? undefined,
                operation: existing?.operation,
                reason: payload.reason ?? existing?.reason,
                error_code: payload.error_code ?? null,
                resolved_at: payload.resolved_at ?? null,
              },
            ],
          });
        }
        break;
      }
      case "turn.started":
      case "turn.status_changed": {
        // V0.3.9 §3：回合按 conversation_id 存放，不得退化为单个全局任务。
        const turn = event.payload.turn as Turn | undefined;
        if (turn?.conversation_id && turn.turn_id) {
          const list = get().turnsByConversation[turn.conversation_id] ?? [];
          set({
            turnsByConversation: {
              ...get().turnsByConversation,
              [turn.conversation_id]: [
                ...list.filter((item) => item.turn_id !== turn.turn_id),
                turn,
              ],
            },
          });
        }
        break;
      }
      case "summary.started":
      case "summary.completed":
      case "summary.failed": {
        // V0.3.9 §2：摘要状态事件；失败保留原始 error/error_code，不生成空摘要。
        const payload = event.payload as Partial<ConversationSummary>;
        const summaryConversationId = payload.conversation_id ?? get().activeConversationId ?? "";
        if (payload.summary_id && summaryConversationId) {
          const previous = (get().summariesByConversation[summaryConversationId] ?? []).find(
            (item) => item.summary_id === payload.summary_id,
          );
          const status: ConversationSummary["status"] =
            event.event === "summary.started"
              ? "running"
              : event.event === "summary.completed"
                ? "completed"
                : "failed";
          const summary: ConversationSummary = {
            summary_id: payload.summary_id,
            conversation_id: summaryConversationId,
            status,
            covers_from_message_id:
              payload.covers_from_message_id ?? previous?.covers_from_message_id ?? null,
            covers_to_message_id:
              payload.covers_to_message_id ?? previous?.covers_to_message_id ?? null,
            covers_message_count:
              payload.covers_message_count ?? previous?.covers_message_count ?? 0,
            content: payload.content ?? previous?.content ?? null,
            provider: payload.provider ?? previous?.provider ?? null,
            model: payload.model ?? previous?.model ?? null,
            error_code: payload.error_code ?? null,
            error: payload.error ?? null,
            created_at: payload.created_at ?? previous?.created_at ?? "",
            updated_at: payload.updated_at ?? previous?.updated_at ?? "",
          };
          const list = get().summariesByConversation[summaryConversationId] ?? [];
          const nextList = [
            ...list.filter((item) => item.summary_id !== payload.summary_id),
            summary,
          ];
          const activeConvId = get().activeConversationId;
          const nextSummaries =
            !activeConvId || activeConvId === summaryConversationId
              ? [
                  ...get().summaries.filter((item) => item.summary_id !== payload.summary_id),
                  summary,
                ]
              : get().summaries;
          set({
            summaries: nextSummaries,
            summariesByConversation: {
              ...get().summariesByConversation,
              [summaryConversationId]: nextList,
            },
          });
        }
        break;
      }
      case "memory.updated": {
        // V0.3.9 §2：记忆内容由模型负责，store 只按 memory_id 存原始记录。
        const payload = event.payload as { memory?: PairMemory } & Partial<PairMemory>;
        const memory = payload.memory ?? (payload.memory_id ? (payload as PairMemory) : null);
        if (memory?.memory_id) {
          set({
            memories: [
              ...get().memories.filter((item) => item.memory_id !== memory.memory_id),
              memory,
            ],
          });
        }
        break;
      }
      case "memory.deleted": {
        const payload = event.payload as { memory?: PairMemory } & Partial<PairMemory>;
        const memory = payload.memory;
        const memoryId = memory?.memory_id ?? payload.memory_id ?? "";
        if (memory && memoryId) {
          set({
            memories: [
              ...get().memories.filter((item) => item.memory_id !== memoryId),
              memory,
            ],
          });
        } else if (memoryId) {
          set({
            memories: get().memories.map((item) =>
              item.memory_id === memoryId ? { ...item, status: "deleted" } : item,
            ),
          });
        }
        break;
      }
      case "remote.control_changed": {
        // V0.3.9 §6：租约以服务端为准；非法/缺失 state 保持 null，不伪造 free。
        set({ remoteControl: normalizeRemoteControl(event.payload) });
        break;
      }
      case "voice.playback_interrupted": {
        // V0.3.9 §6：抢占反馈——本地播放必须已停止，迟到分片由终态集合挡住。
        const payload = event.payload as {
          conversation_id?: string;
          message_id?: string | null;
          reason?: string | null;
        };
        const interruptedId = payload.message_id ?? null;
        if (interruptedId) {
          stoppedOrTerminalMessages.add(interruptedId);
          endedTtsMessages.delete(interruptedId);
          const nextChunks = { ...get().voice.ttsChunks };
          delete nextChunks[interruptedId];
          const voice = get().voice;
          set({
            voice: {
              ...voice,
              ttsChunks: nextChunks,
              // 被抢占的消息不再是播放目标；迟到分片由终态集合挡住。
              playback:
                voice.playback.messageId === interruptedId
                  ? { messageId: null, state: "idle", error: null, errorCode: null }
                  : voice.playback,
            },
          });
        }
        console.warn("[voice.playback_interrupted]", event.payload);
        break;
      }
      case "message.created":
      case "message.status_changed": {
        // V0.3.4 Codex 建议 A：委派执行的完成/失败/取消由 message.status_changed
        // 推进消息状态；按 message_id upsert，委派卡据此退出「运行中」。
        const createdPayload = event.payload as {
          message?: Message;
          /** V0.3.7：服务端预判的移动端朗读可用性随 created 下发。 */
          tts_ready?: boolean;
        };
        let message = createdPayload.message;
        if (
          event.event === "message.created" &&
          message &&
          typeof message.message_id === "string" &&
          createdPayload.tts_ready !== undefined &&
          message.tts_ready === undefined
        ) {
          // created 附带的朗读可用性是产生时刻的服务端判定；快照/旧消息
          // 无此字段时保持原样（手机端按不可朗读保守处理，不猜测）。
          message = { ...message, tts_ready: createdPayload.tts_ready };
        }
        if (
          message &&
          typeof message.message_id === "string" &&
          typeof message.conversation_id === "string" &&
          message.conversation_id === get().activeConversationId
        ) {
          if (
            event.event === "message.created" &&
            message.source === "character" &&
            message.tts_ready !== false
          ) {
            preemptOldPlayback(message.message_id);
          }
          const rest = get().messages.filter((m) => m.message_id !== message.message_id);
          set({ messages: [...rest, message] });
        }
        break;
      }
      case "message.delta": {
        const payload = event.payload as {
          message_id?: string;
          conversation_id?: string;
          pair_id?: string;
          source?: Message["source"];
          kind?: Message["kind"];
          channel?: string;
          delta?: string;
          timeline_order?: number | null;
        };
        if (
          payload.conversation_id !== get().activeConversationId ||
          !payload.message_id ||
          typeof payload.delta !== "string"
        ) {
          break;
        }
        const isReasoning =
          (payload.source === "character" && payload.channel === "reasoning") ||
          payload.kind === "assistant.reasoning";
        const existing = get().messages.find(
          (message) => message.message_id === payload.message_id,
        );
        if (!existing && !isReasoning && payload.source === "character" && payload.message_id) {
          preemptOldPlayback(payload.message_id);
        }
        const message: Message = existing
          ? {
              ...existing,
              text: isReasoning ? existing.text : existing.text + payload.delta,
              payload: isReasoning
                ? {
                    ...existing.payload,
                    reasoning:
                      String(existing.payload?.reasoning ?? "") + payload.delta,
                    reasoning_streaming: true,
                  }
                : existing.payload,
              streaming: true,
            }
          : {
              message_id: payload.message_id,
              conversation_id: payload.conversation_id,
              pair_id: payload.pair_id ?? "",
              engine_turn_id: null,
              source: payload.source ?? "assistant",
              kind: payload.kind ?? "assistant.natural_language",
              text: isReasoning ? "" : payload.delta,
              payload: isReasoning
                ? { reasoning: payload.delta, reasoning_streaming: true }
                : {},
              tts_eligible: false,
              created_at: new Date().toISOString(),
              streaming: true,
              timeline_order: payload.timeline_order ?? null,
            };
        const rest = get().messages.filter(
          (item) => item.message_id !== message.message_id,
        );
        set({ messages: [...rest, message] });
        break;
      }
      case "message.finalized": {
        const payload = event.payload as {
          message_id?: string;
          conversation_id?: string;
          text?: string;
        };
        if (payload.conversation_id !== get().activeConversationId || !payload.message_id) {
          break;
        }
        set({
          messages: get().messages.map((message) => {
            if (message.message_id !== payload.message_id) return message;
            return {
              ...message,
              text: payload.text ?? message.text,
              streaming: false,
              payload: { ...message.payload, reasoning_streaming: false },
            };
          }),
        });
        break;
      }
      case "tool_run.upserted": {
        const payload = event.payload as { tool_run?: ToolRun };
        const toolRun = payload.tool_run ?? (event.payload as unknown as ToolRun);
        if (
          !toolRun?.tool_call_id ||
          toolRun.conversation_id !== get().activeConversationId
        ) {
          break;
        }
        const rest = get().toolRuns.filter(
          (item) => item.tool_call_id !== toolRun.tool_call_id,
        );
        set({ toolRuns: [...rest, toolRun] });
        break;
      }
      case "voice.mobile_transcript": {
        const payload = event.payload as {
          session_id?: string;
          text?: string;
          is_final?: boolean;
        };
        if (payload.session_id && payload.session_id === get().voice.capture.sessionId) {
          set({
            voice: {
              ...get().voice,
              transcript: {
                sessionId: payload.session_id,
                text: String(payload.text ?? ""),
                isFinal: payload.is_final ?? false,
              },
              capture: {
                state: payload.is_final ? "idle" : get().voice.capture.state,
                sessionId: payload.is_final ? null : get().voice.capture.sessionId,
                error: null,
              },
            },
          });
        }
        break;
      }
      case "voice.mobile_tts_chunk": {
        const payload = event.payload as {
          message_id?: string;
          seq?: number;
          mime?: string;
          data?: string;
        };
        if (!payload.message_id || typeof payload.seq !== "number") break;
        const msgId = payload.message_id;
        const voice = get().voice;
        // 终态与已停止防御：已停止或已终态的消息分片不得复活播放状态
        if (
          stoppedOrTerminalMessages.has(msgId) ||
          (voice.playback.messageId === msgId &&
            (voice.playback.state === "failed" || voice.playback.state === "stopping"))
        ) {
          break;
        }
        const data = payload.data ?? "";
        const chunk: MobileTtsChunk = {
          seq: payload.seq,
          mime: payload.mime ?? "audio/pcm;rate=24000",
          data,
          bytes: base64PcmByteLength(data),
        };

        // V0.3.8 修复：新语音分片到达时，若正在播放前序旧消息，立即抢占打断旧消息
        const nextChunks = { ...voice.ttsChunks };
        const currentMsgId = voice.playback.messageId;
        if (
          currentMsgId &&
          currentMsgId !== msgId &&
          (voice.playback.state === "buffering" || voice.playback.state === "playing")
        ) {
          stoppedOrTerminalMessages.add(currentMsgId);
          endedTtsMessages.delete(currentMsgId);
          delete nextChunks[currentMsgId];
          void client.request("voice.mobile_tts_stop", { message_id: currentMsgId }).catch(() => {});
        }

        const appended = appendTtsChunk(
          nextChunks[msgId] ?? [],
          chunk,
          TTS_MAX_BUFFERED_PCM_BYTES,
        );
        if (appended.overflow) {
          // V0.3.9 契约 §6：超过上限时整条播放进入 failed（error_code=pcm_overflow），
          // 清空缓冲、记录终态并请求服务端停止合成；不丢旧片段后继续播放。
          // 迟到 chunk/end 由 stoppedOrTerminalMessages + failed 终态挡住，不得复活。
          stoppedOrTerminalMessages.add(msgId);
          endedTtsMessages.delete(msgId);
          delete nextChunks[msgId];
          void client.request("voice.mobile_tts_stop", { message_id: msgId }).catch(() => {});
          console.error(
            `手机端 PCM 缓冲超过上限：message_id=${msgId}，整条播放已标记失败（pcm_overflow）`,
          );
          set({
            voice: {
              ...voice,
              playback: {
                messageId: msgId,
                state: "failed",
                error: `播放缓冲超过上限（${TTS_MAX_BUFFERED_PCM_BYTES} 字节，约 300 秒音频），已中止播放`,
                errorCode: "pcm_overflow",
              },
              ttsChunks: nextChunks,
            },
          });
          break;
        }
        nextChunks[msgId] = appended.chunks;

        let nextPlayback = voice.playback;
        if (
          !voice.playback.messageId ||
          voice.playback.state === "idle" ||
          voice.playback.state === "failed" ||
          voice.playback.messageId !== msgId
        ) {
          nextPlayback = {
            messageId: msgId,
            state: endedTtsMessages.has(msgId) ? "playing" : "buffering",
            error: null,
            errorCode: null,
          };
        } else if (voice.playback.messageId === msgId) {
          nextPlayback = {
            messageId: msgId,
            state: voice.playback.state,
            error: null,
            errorCode: null,
          };
        }

        set({
          voice: {
            ...voice,
            playback: nextPlayback,
            ttsChunks: nextChunks,
          },
        });
        break;
      }
      case "voice.mobile_tts_failed": {
        // 供应商合成失败（契约 §5.2 增补）：如实退出播放状态并保留诊断，
        // 不能让手机端停留在 buffering/playing。
        const failedPayload = event.payload as {
          message_id?: string;
          error?: string;
          error_code?: string | null;
        };
        if (failedPayload.message_id) {
          const failedVoice = get().voice;
          const messageId = failedPayload.message_id;
          const error = failedPayload.error ?? "角色语音合成失败";
          const errorCode = failedPayload.error_code ?? null;
          console.error("角色语音合成失败", messageId, error);
          if (stoppedOrTerminalMessages.has(messageId)) break;
          stoppedOrTerminalMessages.add(messageId);
          endedTtsMessages.delete(messageId);
          const nextChunks = Object.fromEntries(
            Object.entries(failedVoice.ttsChunks).filter(([id]) => id !== messageId),
          );
          set({
            voice: {
              ...failedVoice,
              ttsChunks: nextChunks,
              playback: !failedVoice.playback.messageId || failedVoice.playback.messageId === messageId
                ? nextQueuedPlayback(nextChunks, {
                    messageId,
                    state: "failed",
                    error,
                    errorCode,
                  })
                : failedVoice.playback,
            },
          });
        }
        break;
      }
      case "voice.mobile_tts_end": {
        const payload = event.payload as { message_id?: string };
        if (payload.message_id) {
          const msgId = payload.message_id;
          const voice = get().voice;
          // V0.3.8：失败/停止是终态，迟到的 end 不得掩盖已如实呈现的播放异常；
          // 此事件只是整体结束信号，真实收尾等引擎把最后一个分片播完。
          if (
            stoppedOrTerminalMessages.has(msgId) ||
            (voice.playback.messageId === msgId &&
              (voice.playback.state === "failed" || voice.playback.state === "stopping"))
          ) {
            break;
          }
          endedTtsMessages.add(msgId);
          if (voice.playback.messageId === msgId) {
            set({
              voice: {
                ...voice,
                playback: {
                  messageId: msgId,
                  state: "playing",
                  error: null,
                  errorCode: null,
                },
              },
            });
          }
        }
        break;
      }
      case "power.status_changed": {
        // V0.3.7 电源状态（冻结 §2.1）：payload 与 power.get_status result 完全同形，
        // 由 Sidecar 确定性推导，手机端原样存储展示，不本地重算 at_risk。
        const powerPayload = event.payload as Partial<PowerStatusPayload> | null;
        if (
          powerPayload &&
          typeof powerPayload.supported === "boolean" &&
          typeof powerPayload.at_risk === "boolean"
        ) {
          set({ powerStatus: event.payload as unknown as PowerStatusPayload });
        } else {
          // 形状不符属协议违规：不入状态（残缺数据会伪造横幅），保留原始载荷日志。
          console.warn("mobileStore 收到形状不符的 power.status_changed 事件，已忽略：", event.payload);
        }
        break;
      }
      case "task.busy_changed": {
        // V0.3.4 Codex 建议 A/B：活动任务是会话级权威状态；任务结束（busy=false）
        // 时清空当前会话的活动任务，委派卡不再误判为运行中。只取当前会话条目，
        // 不被其他会话任务干扰。
        const payload = event.payload as {
          busy?: boolean;
          active_task?: ActiveTask | null;
          active_tasks?: ActiveTask[];
          conversation_id?: string;
        };
        const convId = get().activeConversationId;
        let activeTask = get().activeTask;
        // V0.3.9 §3：active_tasks 是事件发生后的完整权威集合，整体替换；
        // activeTask 只是当前会话在该集合中的视图。
        let activeTasks = get().activeTasks;
        if (Array.isArray(payload.active_tasks)) {
          activeTasks = payload.active_tasks;
          activeTask = payload.active_tasks.find((t) => t.conversation_id === convId) ?? null;
        } else if (payload.active_task?.conversation_id === convId) {
          activeTask = payload.active_task;
          activeTasks = [
            ...get().activeTasks.filter((task) => task.conversation_id !== convId),
            payload.active_task,
          ];
        } else if (payload.busy === false && payload.conversation_id === convId) {
          activeTask = null;
          activeTasks = get().activeTasks.filter((task) => task.conversation_id !== convId);
        }
        set({ activeTask, activeTasks });
        break;
      }
      case "queue.changed": {
        // V0.3.8 T5（契约 §14.1）：全量快照按会话对齐——只更新当前活跃
        // 会话的排队项；其他会话的队列由其打开时的 conversation.open 带回。
        const queuePayload = event.payload as {
          conversation_id?: unknown;
          items?: unknown;
        };
        if (
          typeof queuePayload.conversation_id === "string" &&
          queuePayload.conversation_id === get().activeConversationId &&
          Array.isArray(queuePayload.items)
        ) {
          set({
            queueItems: (queuePayload.items as QueueItem[]).filter(
              (item) => item.status === "queued",
            ),
          });
        }
        break;
      }
      case "diagnostic.warning":
        // V0.3.8 T4（契约 §14.6）：引擎诊断告警的客户端最低要求——console
        // 可见且不崩溃；不中断事件流，不伪造任何状态。
        console.warn("[diagnostic.warning]", event.payload);
        break;
      default:
        break;
    }
  };

  return {
    connection: "disconnected",
    deviceName: getStoredDeviceName(),
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
    summariesByConversation: {},
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
      availability: {
        secureContext: typeof window !== "undefined" ? window.isSecureContext : false,
        micPermission: "unknown",
        supported: typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia),
      },
      ttsChunks: {},
    },

    start() {
      if (wired) return;
      wired = true;
      client.onStateChange((connection) => {
        set({ connection });
        if (connection === "disconnected" || connection === "reconnecting" || connection === "unreachable") {
          bootstrapGeneration += 1;
          bootstrapping = null;
          set({ bootstrapped: false });
        }
        if (connection === "connected" && getStoredToken() && !releasingControl) {
          void bootstrap().catch(reportBootstrapFailure);
        }
      });
      client.onEvent(handleEvent);
      // V0.3.8 T1（契约 §14.4）：回前台重同步——connected 时重新 bootstrap
      // 全量覆盖本地快照（幂等补拉）；unreachable 终态由客户端复位重连，
      // 连接成功后自会 bootstrap，不再永久停摆。
      if (typeof document !== "undefined") {
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState !== "visible") return;
          const action = client.notifyAppForeground();
          if (action === "resync") {
            void bootstrap().catch(reportBootstrapFailure);
          }
        });
      }
      client.connect();
    },

    reconnect() {
      // reconnect 前复位退避计数：unreachable 是终态，需显式重开。
      client.disconnect();
      client.connect();
    },

    async pairDevice(code, deviceName) {
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
      const currentView = {
        activeConversationId: get().activeConversationId,
        messages: get().messages,
        toolRuns: get().toolRuns,
        pair: get().pair,
        activeTask: get().activeTask,
      };
      if (currentView.activeConversationId !== conversationId && currentView.messages.length > 0) {
        stableConversationView = currentView;
      }
      const previous = stableConversationView ?? currentView;
      set({
        activeConversationId: conversationId,
        messages: [],
        toolRuns: [],
        pair: null,
        activeTask: null,
      });
      // 页面刷新直接落在聊天页时，装载可能先于 WS 握手完成；
      // 连接等待和请求都必须处于同一回滚范围。
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
          set({ ...previous, bootstrapped: false });
          if (collector) {
            replayEventsAfter(collector.events, get().lastSequence, get().streamId);
          }
        }
        throw error;
      } finally {
        collector?.stop();
      }
      if (generation !== openConversationGeneration || !collector) return;
      const resultStream = result.stream_id == null ? get().streamId : String(result.stream_id);
      if (resultStream && get().streamId && resultStream !== get().streamId) {
        replayEventsAfter(collector.events, get().lastSequence, get().streamId);
        set(previous);
        void bootstrap().catch(reportBootstrapFailure);
        return;
      }
      set({
        activeConversationId: conversationId,
        messages: result.messages,
        toolRuns: result.tool_runs,
        queueItems: result.queue_items.filter((item) => item.status === "queued"),
        pair: result.pair,
        activeTask: result.active_task,
        activeTasks: result.active_task
          ? [
              ...get().activeTasks.filter((task) => task.conversation_id !== conversationId),
              result.active_task,
            ]
          : get().activeTasks.filter((task) => task.conversation_id !== conversationId),
        turnsByConversation: {
          ...get().turnsByConversation,
          [conversationId]: result.turns ?? [],
        },
        summaries: result.summaries ?? (get().summariesByConversation[conversationId] ?? []),
        summariesByConversation: result.summaries
          ? { ...get().summariesByConversation, [conversationId]: result.summaries }
          : get().summariesByConversation,
        memories: result.memories ?? get().memories,
        remoteControl:
          result.remote_control === undefined
            ? get().remoteControl
            : normalizeRemoteControl(result.remote_control),
        streamId: resultStream,
        lastSequence: result.sequence,
        bootstrapped: true,
      });
      replayEventsAfter(collector.events, result.sequence, resultStream);
      stableConversationView = {
        activeConversationId: get().activeConversationId,
        messages: get().messages,
        toolRuns: get().toolRuns,
        pair: get().pair,
        activeTask: get().activeTask,
      };
    },

    async submitDelegation(text) {
      const conversationId = get().activeConversationId;
      if (!conversationId) throw new Error("尚未打开会话");
      const mode = get().conversationsById[conversationId]?.last_mode ?? "chat";
      // V0.3.8 T5：忙时回执 queued+queue_item——排队消息立即本地可见，
      // 随后的 queue.changed 全量快照会对齐（事件为权威）。
      const receipt = await client.request<SubmitReceipt>("chat.submit", {
        conversation_id: conversationId,
        target: "assistant",
        mode,
        text,
      });
      applySubmitReceipt(set, get, conversationId, receipt);
    },

    async submitMessage(text) {
      const conversationId = get().activeConversationId;
      if (!conversationId) throw new Error("尚未打开会话");
      // 角色消息任何模式都可发送；不带 mode 参数，避免顺带切换会话模式。
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
      // 项目级审批模式切换（请求批准/帮我审核/完全允许运行）。以服务端
      // 返回的真实 project 快照更新本地状态；失败如实抛出由界面呈现。
      const result = (await client.request("project.update_settings", {
        project_id: projectId,
        approval_mode: mode,
      })) as { project?: { project_id: string; approval_mode: ApprovalMode } };
      if (result?.project?.project_id) {
        const updated = result.project;
        set({
          projects: get().projects.map((item) =>
            item.project_id === updated.project_id
              ? { ...item, approval_mode: updated.approval_mode }
              : item,
          ),
        });
      }
    },

    async resolveApproval(approvalId, decision) {
      try {
        await client.request("approval.resolve", { approval_id: approvalId, decision });
      } catch (error) {
        const code = error instanceof Error && "code" in error ? String((error as Error & { code?: string }).code) : "";
        if (code === "approval_already_resolved") {
          // V0.3.5 双端并发仲裁：本端失败必须按先到者的真实结果收敛，严禁用本端入参顶替
          // （此前直接写入本端 attempted decision，会把对端的真实拒绝伪造成批准，违反 Let It Fail）。
          // 真实结果首选 approval.resolved 事件已写入的记录（同一 WS 上有序，通常已先处理）；
          // 事件未到时优先取服务端结构化 details（契约 §6：error.details={decision,resolved_by}，
          // 见 application_service.py ApprovalBroker.resolve），仅在 details 缺失时从错误文案提取。
          const message = error instanceof Error ? error.message : String(error);
          const structured =
            error instanceof RemoteCommandError ? error.details : undefined;
          const recorded = get().resolvedApprovals.find((item) => item.approval_id === approvalId);
          const parsedDecision =
            typeof structured?.decision === "string" && structured.decision
              ? structured.decision
              : (/应答（([^）]+)）/.exec(message)?.[1] ?? "");
          const parsedBy =
            typeof structured?.resolved_by === "string" && structured.resolved_by
              ? structured.resolved_by
              : (/已由\s*(\S+)\s*应答/.exec(message)?.[1] ?? "remote");
          const pending = get().approvals.find((item) => item.approval_id === approvalId);
          set({
            approvals: get().approvals.filter((item) => item.approval_id !== approvalId),
            resolvedApprovals: recorded
              ? get().resolvedApprovals
              : parsedDecision
                ? [
                    ...get().resolvedApprovals.filter((item) => item.approval_id !== approvalId),
                    {
                      approval_id: approvalId,
                      conversation_id: get().activeConversationId ?? undefined,
                      decision: parsedDecision,
                      resolved_by: parsedBy,
                      task_id: pending?.task_id,
                      operation: pending?.operation,
                      reason: pending?.reason,
                    },
                  ]
                : // 解析不到真实决策时如实不补已决卡片；错误照常抛出由界面呈现。
                  get().resolvedApprovals,
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
        if (getStoredToken()) {
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
      stableConversationView = null;
      client.disconnect();
      clearCredentials();
      set({
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
        activeTasks: [],
        turnsByConversation: {},
        summaries: [],
        summariesByConversation: {},
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
          availability: {
            secureContext: typeof window !== "undefined" ? window.isSecureContext : false,
            micPermission: "unknown",
            supported: typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia),
          },
          ttsChunks: {},
        },
      });
    },

    async startVoiceCapture(conversationId) {
      const voice = get().voice;
      if (voice.capture.state !== "idle") {
        // 前置条件违反如实抛错：此前静默 return undefined，叠加接口的 `| void`，
        // 导致 useVoiceCapture 每次启动都必抛「服务端未返回语音会话 ID」。
        throw new Error("语音采集正在进行中");
      }
      set({
        voice: {
          ...voice,
          capture: { state: "starting", sessionId: null, error: null },
          transcript: null,
        },
      });
      try {
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
        // Let It Fail：上行分片失败（如 voice_audio_seq_gap）必须留在界面上，
        // 不得被 hook 后续的 stopSession 复位动作静默冲掉。
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

    async stopVoiceCapture() {
      const sessionId = get().voice.capture.sessionId;
      if (!sessionId) return;
      set({
        voice: {
          ...get().voice,
          capture: { state: "stopping", sessionId, error: null },
        },
      });
      try {
        await client.request<{ session_id: string; transcript: string; conversation_id: string }>(
          "voice.mobile_ptt_stop",
          { session_id: sessionId },
        );
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

    async stopVoicePlayback(messageId) {
      stoppedOrTerminalMessages.add(messageId);
      endedTtsMessages.delete(messageId);
      const voice = get().voice;
      // 只有当前活跃播放确为该消息时，才将全局状态置为 stopping
      if (voice.playback.messageId === messageId) {
        set({
          voice: {
            ...voice,
            playback: { messageId, state: "stopping", error: null, errorCode: null },
          },
        });
      }
      // 该消息在本地残留的分片立即释放
      const nextChunks = { ...get().voice.ttsChunks };
      delete nextChunks[messageId];
      set({
        voice: {
          ...get().voice,
          ttsChunks: nextChunks,
        },
      });

      try {
        await client.request("voice.mobile_tts_stop", { message_id: messageId });
        // 请求成功后：只有当当前全局状态仍属于该 messageId 时才重置为 idle！
        // 如果当前已切换为新消息，切勿把新消息清空！
        const currentVoice = get().voice;
        if (currentVoice.playback.messageId === messageId) {
          set({
            voice: {
              ...currentVoice,
              playback: nextQueuedPlayback(currentVoice.ttsChunks),
            },
          });
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const currentVoice = get().voice;
        if (currentVoice.playback.messageId === messageId) {
          set({
            voice: {
              ...currentVoice,
              playback: nextQueuedPlayback(currentVoice.ttsChunks, {
              messageId,
              state: "failed",
              error: message,
              errorCode: null,
            }),
            },
          });
        }
        throw error;
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

    failVoicePlayback(messageId, error, errorCode = null) {
      stoppedOrTerminalMessages.add(messageId);
      endedTtsMessages.delete(messageId);
      console.error("语音播放失败", messageId, error);
      const voice = get().voice;
      if (voice.playback.messageId !== messageId) return;
      if (voice.playback.state === "stopping") return;
      // Let It Fail：播放异常如实置 failed 并保留错误与真实失败码，不清成成功态；
      // 该消息分片已不可用，随失败一并清理。
      const nextChunks = { ...voice.ttsChunks };
      delete nextChunks[messageId];
      set({
        voice: {
          ...voice,
          playback: nextQueuedPlayback(nextChunks, { messageId, state: "failed", error, errorCode }),
          ttsChunks: nextChunks,
        },
      });
    },

    async refreshRemoteControl() {
      // V0.3.9 §6：显式只读查询租约；响应形状不符时保持 null，不伪造 free。
      const result = await client.request<{ remote_control?: unknown }>("remote.control_status");
      const raw =
        result && typeof result === "object" && "remote_control" in result
          ? (result as { remote_control?: unknown }).remote_control
          : result;
      set({ remoteControl: normalizeRemoteControl(raw) });
    },

    async loadSummaries(conversationId) {
      // V0.3.9 §2：摘要只读查询；响应未带数组时保持现状，不合成空摘要。
      const target = conversationId ?? get().activeConversationId;
      if (!target) return;
      const result = await client.request<{ summaries?: ConversationSummary[] }>("summary.get", {
        conversation_id: target,
      });
      if (Array.isArray(result?.summaries)) {
        const activeConvId = get().activeConversationId;
        const nextSummaries =
          !activeConvId || activeConvId === target ? result.summaries : get().summaries;
        set({
          summaries: nextSummaries,
          summariesByConversation: {
            ...get().summariesByConversation,
            [target]: result.summaries,
          },
        });
      }
    },

    async loadMemories(conversationId) {
      // V0.3.9 §2：记忆只读查询；作用域由服务端解析，客户端只传 conversation_id。
      const target = conversationId ?? get().activeConversationId;
      if (!target) return;
      const result = await client.request<{ memories?: PairMemory[] }>("memory.list", {
        conversation_id: target,
      });
      if (Array.isArray(result?.memories)) {
        set({ memories: result.memories });
      }
    },

    async refreshVoiceAvailability() {
      const supported =
        typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
      const secureContext = typeof window !== "undefined" ? window.isSecureContext : false;
      let micPermission: MobileVoiceAvailability["micPermission"] = "unknown";
      try {
        if (typeof navigator !== "undefined" && navigator.permissions?.query) {
          const result = await navigator.permissions.query({ name: "microphone" as PermissionName });
          micPermission = result.state as MobileVoiceAvailability["micPermission"];
        }
      } catch {
        micPermission = "unknown";
      }
      set({
        voice: {
          ...get().voice,
          availability: { secureContext, micPermission, supported },
        },
      });
    },
  };
});

/** 测试专用：暴露底层 client 以便注入 FakeWebSocket 后断言帧。 */
export const mobileWsClient = client;
