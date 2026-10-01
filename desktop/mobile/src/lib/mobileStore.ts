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
  MemoryWirePayload,
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
import { pairMemoryFromPayload } from "@shared/contracts/protocol";
import type { MobileConnectionState, WireEvent } from "./wsClient";
import {
  clearCredentials,
  getStoredDeviceName,
  getStoredToken,
  MobileWsClient,
  RemoteCommandError,
  saveCredentials,
} from "./wsClient";
import { navigate } from "./router";

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

/** 最近一次朗读被服务端打断（voice.playback_interrupted 载荷原值）。 */
export interface MobilePlaybackInterruption {
  conversationId: string | null;
  messageId: string | null;
  reason: string | null;
}

/** 已决审批：终态字段取自 approval.resolved 或 approval_already_resolved 的 details。 */
export interface MobileResolvedApproval {
  approval_id: string;
  conversation_id?: string;
  task_id?: string;
  /** allow / allow_for_conversation / deny / timeout；服务端未给出时为空串。 */
  decision: string;
  resolved_by: string | null;
  actor: string | null;
  /** 终态原因（如「等待审批超时」），与申请理由分开存放。 */
  resolved_reason: string | null;
  error_code: string | null;
  resolved_at: string | null;
  /** 申请时的操作与理由；本端未收到 approval.requested 时缺省。 */
  operation?: PendingApproval["operation"];
  reason?: string;
}

/** 聊天页装载失败：保留目标会话，页面据此提供重试。 */
export interface MobileOpenError {
  conversationId: string;
  message: string;
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
  authFailureCode: string | null;
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
  /** 已决审批记录，供 UI 表达双端仲裁结果。 */
  resolvedApprovals: MobileResolvedApproval[];
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
  /** 最近处理的带序号事件；-1 表示本代次尚未收到事件。 */
  lastSequence: number;
  bootstrapped: boolean;
  /** 最近一次状态同步（app.bootstrap）的原始错误；同步成功或重新开始时清空。 */
  syncError: string | null;
  /** 当前聊天页装载（conversation.open）失败的原始错误。 */
  openError: MobileOpenError | null;
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
      /** 最近一次朗读被打断；下一条朗读开始时清空。 */
      lastInterruption: MobilePlaybackInterruption | null;
    };

  start: () => void;
  /** 手动重连入口（unreachable/auth_failed 后由 UI 重试按钮调用）。 */
  reconnect: () => void;
  /** 状态同步失败后的重试入口。 */
  retrySync: () => Promise<void>;
  pairDevice: (code: string, deviceName: string) => Promise<void>;
  openConversation: (conversationId: string) => Promise<void>;
  /** 委派给助手；不带 mode，模式以服务端会话记录为准。 */
  submitDelegation: (conversationId: string, text: string) => Promise<void>;
  /** 普通角色消息（target=character，任何模式可用）。 */
  submitMessage: (conversationId: string, text: string) => Promise<void>;
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
  /** 停止语音采集；传入 sessionId 时以它覆盖 store 里的会话（用于补发停止）。 */
  stopVoiceCapture: (sessionId?: string) => Promise<void>;
  /** 采集端（麦克风、音频引擎）失败写入 capture.error。 */
  reportVoiceCaptureError: (message: string) => void;
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

function detectVoiceAvailability(): MobileVoiceAvailability {
  return {
    secureContext: typeof window !== "undefined" ? window.isSecureContext : false,
    micPermission: "unknown",
    supported: typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia),
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
  | "turnsByConversation"
  | "summaries"
  | "summariesByConversation"
  | "memories"
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
    turnsByConversation: {},
    summaries: [],
    summariesByConversation: {},
    memories: [],
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
      playback: { messageId: null, state: "idle", error: null, errorCode: null },
      availability,
      ttsChunks: {},
      lastInterruption: null,
    },
  };
}

/**
 * 已决审批记录：终态字段来自 approval.resolved 载荷或 approval_already_resolved 的
 * details（两者字段相同）；申请时的 operation 与理由来自本端见过的待审批记录。
 */
function toResolvedApproval(
  approvalId: string,
  fields: Partial<ApprovalResolvedPayload>,
  pending: PendingApproval | undefined,
): MobileResolvedApproval {
  return {
    approval_id: approvalId,
    conversation_id: fields.conversation_id ?? pending?.conversation_id,
    task_id: fields.task_id ?? pending?.task_id,
    decision: fields.decision ?? "",
    resolved_by: fields.resolved_by ?? null,
    actor: fields.actor ?? null,
    resolved_reason: fields.reason ?? null,
    error_code: fields.error_code ?? null,
    resolved_at: fields.resolved_at ?? null,
    operation: pending?.operation,
    reason: pending?.reason,
  };
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

/**
 * V0.3.9 §2：memory.* 线缆载荷 → 前端记录。
 *
 * 后端 `_memory_payload`（memory.list 条目与 memory.updated / memory.deleted
 * 事件共用）下发的是**扁平五分量**，线缆上没有嵌套 scope 对象（见
 * protocol.MemoryWirePayload）。scope 一律由共享的 `pairMemoryFromPayload`
 * 派生，客户端不拼接、不改写作用域；直接强转 PairMemory 会得到 scope undefined。
 *
 * 形状不符（缺 memory_id / status 不在枚举内）返回 null，由调用方如实报错，
 * 不伪造记录、也不把协议违规当成空数据成功。
 */
function decodeMemoryPayload(raw: unknown): PairMemory | null {
  if (!raw || typeof raw !== "object") return null;
  const payload = raw as Partial<MemoryWirePayload>;
  if (typeof payload.memory_id !== "string" || payload.memory_id === "") return null;
  if (payload.status !== "active" && payload.status !== "deleted") return null;
  return pairMemoryFromPayload(payload as MemoryWirePayload);
}

/** 载荷里非空的 memory_id（含形状不符时只剩 id 的形态）；没有则空串。 */
function memoryIdFromPayload(raw: unknown): string {
  if (!raw || typeof raw !== "object") return "";
  const memoryId = (raw as { memory_id?: unknown }).memory_id;
  return typeof memoryId === "string" ? memoryId : "";
}

/** 线缆载荷必须能解码；解不开即协议违规，抛错而不静默丢弃。 */
function requireMemoryPayload(raw: unknown, source: string): PairMemory {
  const memory = decodeMemoryPayload(raw);
  if (!memory) {
    throw new Error(
      `${source} 载荷形状不符：需要扁平分量的记忆记录（memory_id + status + 作用域五分量），收到 ${JSON.stringify(raw)}`,
    );
  }
  return memory;
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
  // 快照 queue_items 属于快照当前会话；不匹配本会话时不覆盖。
  const queueItems = snapshotMatchesActive
    ? visibleQueueItems(snapshot.queue_items)
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
    // 记忆：后端 bootstrap 不下发 memories 字段（application_service.bootstrap
    // 只回 messages/tool_runs/turns/queue_items/active_task），此处不涉及线缆解码；
    // 记忆的真实水合入口是 memory.list 与 memory.updated / memory.deleted。
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
  const eventCollectors = new Set<WireEvent[]>();

  /** 桌面端新代次：会话级状态整体回到初值并采用新 stream_id，保留当前打开的聊天。 */
  const resetSession = (streamId: string | null): void => {
    openConversationGeneration += 1;
    stoppedOrTerminalMessages.clear();
    endedTtsMessages.clear();
    set({ ...initialSessionState(get().voice.availability), streamId });
  };
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

  /** 重放收集期间的带序号事件；remote-only 事件不带序号，收到时已即时处理。 */
  const replayEventsAfter = (
    events: WireEvent[],
    sequence: number,
    streamId: string | null,
  ): void => {
    events
      .filter((event): event is WireEvent & { sequence: number } => {
        const eventStream = event.stream_id == null ? null : String(event.stream_id);
        return (
          typeof event.sequence === "number" &&
          event.sequence > sequence &&
          (!streamId || !eventStream || eventStream === streamId)
        );
      })
      .sort((left, right) => left.sequence - right.sequence)
      .forEach((event) => handleEvent(event, true));
  };

  /** 后台触发的同步失败：错误已写入 syncError，这里保留日志。 */
  const reportBootstrapFailure = (error: unknown): void => {
    console.error("手机端状态同步失败", error);
  };

  const bootstrap = async (): Promise<void> => {
    if (releasingControl) return;
    if (bootstrapping) return bootstrapping;
    const generation = ++bootstrapGeneration;
    set({ bootstrapped: false, syncError: null });
    const activeConversationId = get().activeConversationId;
    const collector = collectEvents();
    let tracked: Promise<void>;
    const request = (async () => {
      const snapshot = await client.request<DesktopSnapshot>("app.bootstrap");
      if (generation !== bootstrapGeneration) return;
      // 控制声明必须成功后才公布同步完成；活跃聊天重连也走同一条路径。
      await client.request("remote.claim_control");
      if (generation !== bootstrapGeneration) return;
      // 鉴权请求已成功，连接确认可用后才开始心跳。
      client.startHeartbeat();
      const snapshotStream =
        snapshot.stream_id == null ? null : String(snapshot.stream_id);
      // app.bootstrap 是新连接的权威基线；重连后即使旧 streamId 仍在本地，也采纳响应代次。
      if (snapshotStream && snapshotStream !== get().streamId) {
        resetSession(snapshotStream);
      }
      applySnapshot(set, snapshot, get);
      // serve 启动时的 power.status_changed 只在手机订阅之前发一次且没有回放，
      // bootstrap 完成后主动拉一次当前状态（幂等无副作用）；失败保留日志，不阻塞同步。
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
            set({
              bootstrapped: false,
              openError: {
                conversationId: activeConversationId,
                message: error instanceof Error ? error.message : String(error),
              },
            });
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
          queueItems: visibleQueueItems(conversation.queue_items),
          pair: conversation.pair,
          activeTask: conversation.active_task,
          openError: null,
          // conversation.open 只带当前聊天的 active_task；全账号权威集合
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
          // 只读装载显式下发时才覆盖摘要/记忆/租约；conversation.open 不带 memories，保留现状。
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
    const state = get();
    const eventStream = event.stream_id == null ? null : String(event.stream_id);
    if (eventStream && state.streamId && eventStream !== state.streamId) {
      bootstrapGeneration += 1;
      bootstrapping = null;
      eventCollectors.clear();
      resetSession(eventStream);
      void bootstrap().catch(reportBootstrapFailure);
    } else if (eventStream && !state.streamId) {
      set({ streamId: eventStream });
    }

    // remote-only 事件（TTS 分片、转写）不带序号：不收集重放、不做序号校验、不推进 lastSequence。
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
        // 两种载荷：完整 {"conversation": record}，以及归档非当前会话时只带
        // {"conversation_id"}。完整记录同时写回所属项目（列表页按项目渲染）；
        // 只有 id 时本地不知道变了什么，重新同步取权威列表。
        const conversation = (event.payload as { conversation?: ConversationRecord }).conversation;
        if (conversation) {
          set({
            conversationsById: { ...get().conversationsById, [conversation.conversation_id]: conversation },
            projects: get().projects.map((project) =>
              project.project_id === conversation.project_id
                ? {
                    ...project,
                    conversations: upsertBy(
                      project.conversations ?? [],
                      conversation,
                      (item) => item.conversation_id === conversation.conversation_id,
                    ),
                  }
                : project,
            ),
          });
        } else {
          void bootstrap().catch(reportBootstrapFailure);
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
        // 终态为 allow|allow_for_conversation|deny|timeout；resolved_by/actor/reason/
        // error_code 原样记录，缺失保持 null。载荷里的 reason 是终态原因，申请理由取自待审批记录。
        const payload = event.payload as Partial<ApprovalResolvedPayload>;
        const approvalId = payload.approval_id;
        if (approvalId) {
          const pending = get().approvals.find((item) => item.approval_id === approvalId);
          set({
            approvals: get().approvals.filter((item) => item.approval_id !== approvalId),
            resolvedApprovals: upsertBy(
              get().resolvedApprovals,
              toResolvedApproval(approvalId, payload, pending),
              (item) => item.approval_id === approvalId,
            ),
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
        // 线缆载荷是扁平五分量，经 decodeMemoryPayload 派生 scope；
        // 形状不符即协议违规，直接抛出，不静默丢弃也不伪造记录。
        const memory = requireMemoryPayload(event.payload, "memory.updated");
        set({
          memories: [
            ...get().memories.filter((item) => item.memory_id !== memory.memory_id),
            memory,
          ],
        });
        break;
      }
      case "memory.deleted": {
        // V0.3.9 §2：删除必须真实落状态——线缆恒为完整载荷（status=deleted），
        // 按记录替换；只带 id 时把已知记录标记为 deleted，未知 id 不凭空造记录。
        const memory = decodeMemoryPayload(event.payload);
        if (memory) {
          set({
            memories: [
              ...get().memories.filter((item) => item.memory_id !== memory.memory_id),
              memory,
            ],
          });
          break;
        }
        const memoryId = memoryIdFromPayload(event.payload);
        if (!memoryId) {
          throw new Error(
            `memory.deleted 载荷形状不符：既不是完整记忆记录也没有 memory_id，收到 ${JSON.stringify(event.payload)}`,
          );
        }
        set({
          memories: get().memories.map((item) =>
            item.memory_id === memoryId ? { ...item, status: "deleted" } : item,
          ),
        });
        break;
      }
      case "remote.control_changed": {
        // V0.3.9 §6：租约以服务端为准；非法/缺失 state 保持 null，不伪造 free。
        set({ remoteControl: normalizeRemoteControl(event.payload) });
        break;
      }
      case "voice.playback_interrupted": {
        // 抢占反馈：本地播放随之停止，迟到分片由终态集合挡住；打断原因写入 lastInterruption 供页面展示。
        const payload = event.payload as {
          conversation_id?: string;
          message_id?: string | null;
          reason?: string | null;
        };
        const interruptedId = payload.message_id ?? null;
        const lastInterruption: MobilePlaybackInterruption = {
          conversationId: payload.conversation_id ?? null,
          messageId: interruptedId,
          reason: payload.reason ?? null,
        };
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
              playback:
                voice.playback.messageId === interruptedId
                  ? { messageId: null, state: "idle", error: null, errorCode: null }
                  : voice.playback,
              lastInterruption,
            },
          });
        } else {
          set({ voice: { ...get().voice, lastInterruption } });
        }
        console.warn("[voice.playback_interrupted]", event.payload);
        break;
      }
      case "message.created":
      case "message.status_changed": {
        // 委派执行的完成/失败/取消由 message.status_changed 推进消息状态；
        // 按 message_id 原位替换，时间线位置不随状态变化移动。
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
          const messageId = message.message_id;
          set({
            messages: upsertBy(get().messages, message, (item) => item.message_id === messageId),
          });
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
                // V0.3.9 G1 收尾：error 原样保留。生产时序里 is_final 事件先于 stop
                // 响应到达，写死 null 会把上行分片失败（voice_audio_seq_gap 等）留下的
                // 错误清掉，让 F4 的保留只在「事件丢失」兜底路径生效。
                // 错误由下一次成功启动的 starting 态清空（见 startVoiceCapture）。
                error: get().voice.capture.error,
              },
            },
          });
        }
        break;
      }
      case "voice.mobile_asr_failed": {
        // 服务端放弃本次转写（如录音超时）：会话已关闭，录音状态退出并展示错误原文。
        const payload = event.payload as {
          session_id?: string;
          code?: string;
          error?: string;
        };
        console.error("手机语音转写失败", payload);
        if (payload.session_id && payload.session_id === get().voice.capture.sessionId) {
          set({
            voice: {
              ...get().voice,
              capture: {
                state: "idle",
                sessionId: null,
                error: payload.error ?? null,
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

        // 新消息的分片到达时，正在播放的旧消息立即被抢占
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
          // 超过上限时整条播放进入 failed（error_code=pcm_overflow），清空缓冲、
          // 记录终态并请求服务端停止合成；迟到 chunk/end 由终态集合与 failed 挡住。
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
        let lastInterruption = voice.lastInterruption;
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
          // 新一条朗读开始，上一次的打断提示随之失效。
          lastInterruption = null;
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
            lastInterruption,
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
        // 全量快照按会话对齐：只更新当前活跃会话的排队项；
        // 其他会话的队列由其打开时的 conversation.open 带回。
        const queuePayload = event.payload as {
          conversation_id?: unknown;
          items?: unknown;
        };
        if (
          typeof queuePayload.conversation_id === "string" &&
          queuePayload.conversation_id === get().activeConversationId &&
          Array.isArray(queuePayload.items)
        ) {
          set({ queueItems: visibleQueueItems(queuePayload.items as QueueItem[]) });
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

  /** 发消息或开始按住说话前停止本机全部朗读；停止失败如实抛出。 */
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
    authFailureCode: null,
    deviceName: getStoredDeviceName(),
    activeConversationId: null,
    ...initialSessionState(detectVoiceAvailability()),

    start() {
      if (wired) return;
      wired = true;
      client.onStateChange((connection) => {
        const failureCode = client.getAuthFailureCode();
        set({
          connection,
          authFailureCode: connection === "auth_failed" ? failureCode : null,
          ...(connection === "auth_failed" &&
          (failureCode === "expired_token" || failureCode === "token_expired")
            ? { deviceName: null }
            : {}),
        });
        if (connection === "disconnected" || connection === "reconnecting" || connection === "unreachable") {
          bootstrapGeneration += 1;
          bootstrapping = null;
          set({ bootstrapped: false });
        }
        if (connection === "connected" && getStoredToken() && !releasingControl) {
          void bootstrap().catch(reportBootstrapFailure);
        }
        if (
          connection === "auth_failed" &&
          (failureCode === "expired_token" || failureCode === "token_expired")
        ) {
          clearCredentials();
          navigate({ name: "pair" }, { replace: true });
        }
      });
      client.onEvent(handleEvent);
      // 回前台重同步：connected 时重新 bootstrap 全量覆盖本地快照；
      // unreachable 由客户端复位重连，连接成功后自会 bootstrap。
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
      set({ authFailureCode: null });
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
      const resultStream = result.stream_id == null ? get().streamId : String(result.stream_id);
      if (resultStream && get().streamId && resultStream !== get().streamId) {
        // 装载结果来自另一代次：整体重新同步，bootstrap 会重新装载当前聊天。
        void bootstrap().catch(reportBootstrapFailure);
        return;
      }
      set({
        activeConversationId: conversationId,
        messages: result.messages,
        toolRuns: result.tool_runs,
        queueItems: visibleQueueItems(result.queue_items),
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
        // 记忆：conversation.open 返回体不带 memories，缺字段保留现状。
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
    },

    async submitDelegation(conversationId, text) {
      await stopLocalPlayback();
      // 不带 mode：服务端按会话持久化的模式校验，手机上可能过时的模式不覆盖桌面切换。
      // 忙时回执 queued+queue_item，排队消息立即本地可见，随后的 queue.changed 全量快照对齐。
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
        if (error instanceof RemoteCommandError && error.code === "approval_already_resolved") {
          // 双端并发仲裁：按先到者的真实终态收敛。服务端在 details 里给出与
          // approval.resolved 相同的终态字段；事件已先到时以事件记录为准。
          const recorded = get().resolvedApprovals.some((item) => item.approval_id === approvalId);
          const pending = get().approvals.find((item) => item.approval_id === approvalId);
          set({
            approvals: get().approvals.filter((item) => item.approval_id !== approvalId),
            resolvedApprovals: recorded
              ? get().resolvedApprovals
              : [
                  ...get().resolvedApprovals,
                  toResolvedApproval(
                    approvalId,
                    error.details as Partial<ApprovalResolvedPayload>,
                    pending,
                  ),
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
        authFailureCode: null,
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
          // 新会话已接管：失败必须可见（Let It Fail），但只落 error，
          // 不动新会话的 state/sessionId。
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
      // 返回体是扁平五分量数组（protocol.MemoryWirePayload），逐条经共享解码器
      // 派生 scope。缺 memories 数组或条目形状不符即协议违规：如实抛错，
      // 既不合成空列表当成功，也不清空既有记录。
      const target = conversationId ?? get().activeConversationId;
      if (!target) return;
      const result = await client.request<{ memories?: unknown }>("memory.list", {
        conversation_id: target,
      });
      if (!Array.isArray(result?.memories)) {
        throw new Error(
          `memory.list 返回体缺 memories 数组，无法按线缆形状解码：${JSON.stringify(result)}`,
        );
      }
      const memories = result.memories.map((raw) => requireMemoryPayload(raw, "memory.list"));
      set({ memories });
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
