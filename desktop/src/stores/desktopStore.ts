import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";

import type {
  AccountListItem,
  AccountRecord,
  ActiveTask,
  ConversationOpenResult,
  ConversationRecord,
  ConversationSummary,
  DesktopEvent,
  DesktopSnapshot,
  DesktopStreamEvent,
  MemoryWirePayload,
  Message,
  MessageDeltaPayload,
  PairMemory,
  PairRecord,
  PairSummary,
  PendingApproval,
  PowerStatusPayload,
  ProjectRecord,
  QueueItem,
  ToolRun,
  TunnelFailedPayload,
  TunnelStartedPayload,
  TurnMetric,
  VoiceCardProvisionChangedPayload,
  VoiceState,
} from "../contracts/protocol";
import type {
  CharacterCreateViewModel,
  CharacterLibraryViewModel,
  MainView,
  PromptAssemblyView,
  RemotePairingViewModel,
  SummaryRegenerateTarget,
  TunnelState,
  TunnelViewModel,
} from "../contracts/view-models";
import { pairMemoryFromPayload } from "../contracts/protocol";
import { applyMessageDelta } from "./messageDelta";

export type DesktopStatus = "booting" | "ready" | "disconnected" | "error";

/** error.reported 中描述「本地服务已断开」的协议错误码；toast id 以它为前缀。 */
const DISCONNECT_TOAST_PREFIX = "backend_disconnected:";

/** Toast 队列项，与 ui/status/types.ts 的 ToastItem 同形。 */
export interface StoreToast {
  id: string;
  kind: "error" | "warning" | "info" | "success";
  text: string;
  hasDetails?: boolean;
}

/** Sidecar 在 backend.ready 中自报的运行模式。 */
export interface BackendInfo {
  pid: number | null;
  /** 是否运行在演示模式；null 表示未上报。 */
  demo: boolean | null;
  /** 模式判定来源（explicit_real | explicit_demo | default_real），未上报为 null，取值原样保留。 */
  modeSource: string | null;
}

/** 设置中心「长期记忆」页的读取状态。 */
export interface MemoryPanelState {
  /** 本次读取针对的会话（作用域由服务端按该会话解析）；null 表示尚未读取。 */
  conversationId: string | null;
  loading: boolean;
  /** memory.list 的失败原文；成功读取后清除。 */
  error: string | null;
  /** 至少完成过一次 memory.list，用于区分「未读取」与「零条」。 */
  loaded: boolean;
}

/** 某聊天最近一次审查智能体状态（review.* 事件）。 */
export interface ReviewStatus {
  active: boolean;
  /** 审查结论或失败原因；审查进行中为 null。 */
  text: string | null;
}

export interface DesktopState {
  status: DesktopStatus;
  error: string | null;
  /** 序号缺口触发的重新同步进行中；界面保持可用，只显示同步提示。 */
  resyncing: boolean;
  theme: "dark" | "light";
  composerTarget: "character" | "assistant";
  projectsById: Record<string, ProjectRecord>;
  conversationsById: Record<string, ConversationRecord>;
  messagesById: Record<string, Message>;
  messageIdsByConversation: Record<string, string[]>;
  toolRunsById: Record<string, ToolRun>;
  toolIdsByConversation: Record<string, string[]>;
  queueItemsByConversation: Record<string, QueueItem[]>;
  currentAccountId: string;
  /** 当前账号上下文代次；任何账号切换事件都会推进，用于废弃在途异步结果。 */
  accountGeneration: number;
  currentAccount: AccountRecord | null;
  accounts: AccountListItem[];
  currentProjectId: string;
  currentConversationId: string;
  pair: PairRecord | null;
  pairs: PairSummary[];
  activeTask: DesktopSnapshot["active_task"];
  /** 全账号活动任务，按 conversation_id 索引；busy 与 activeTask 由本窗口活动聊天推导。 */
  activeTasksByConversation: Record<string, ActiveTask>;
  busy: boolean;
  approvals: PendingApproval[];
  approvalResolvingById: Record<string, boolean>;
  reviewByConversation: Record<string, ReviewStatus>;
  voice: VoiceState;
  /** recoverable/info 错误与操作失败提示；同 id 去重，最多 5 条。 */
  toasts: StoreToast[];
  /** config.get 结果，设置中心的数据源。 */
  configSnapshot: Record<string, unknown> | null;
  lastSequence: number;
  needsBootstrap: boolean;
  /** 当前连接代次；业务事件和快照必须属于该代次才投影。 */
  streamId: string | null;
  /** bootstrap 或序号缺口期间暂存的同代次业务事件，快照水合后核对重放。 */
  eventBuffer: DesktopEvent[];
  /** conversation.open 结果对应的事件序号：序号不超过它的会话内消息、工具、回合与队列事件
      已包含在装载结果里，经常驻订阅再次到达时只推进序号。 */
  conversationViewSequence: Record<string, number>;
  /** 本窗口视图 id，用于请求 id 与 conversation.open 的 view_id。 */
  viewId: string;
  /** 本窗口打开的聊天标签，顺序即标签顺序。 */
  openConversationIds: string[];
  /** 本窗口当前活动标签；全部关闭后为 null。 */
  activeConversationId: string | null;
  /** 本窗口当前标签所属项目，不随 Sidecar 全局导航指针变化。 */
  activeProjectId: string | null;
  /** 已用缓存切过去、正在等待 conversation.open 权威结果的聊天。 */
  syncingConversationIds: Record<string, true>;

  /** 按聊天存放的摘要记录，由 summary.* 事件驱动。 */
  summariesByConversation: Record<string, ConversationSummary[]>;
  /** 当前聊天作用域内的长期记忆（服务端解析作用域）。 */
  memories: PairMemory[];
  /** 按聊天存放的长期记忆。 */
  memoriesByConversation: Record<string, PairMemory[]>;
  memoryPanel: MemoryPanelState;
  backendInfo: BackendInfo | null;
  /** 最近一次 summary.failed 留下的重新生成目标。 */
  summaryRegenerateTarget: SummaryRegenerateTarget | null;
  /** metrics.query 结果（未观测指标为 null，真实零值为 0）。 */
  turnMetrics: TurnMetric[];
  metricsCursor: string | null;
  metricsLoading: boolean;
  metricsError: string | null;
  /** diagnostics.prompt_assembly 的概览结果（不含隐藏原文）。 */
  promptAssembly: PromptAssemblyView | null;
  promptAssemblyLoading: boolean;
  promptAssemblyError: string | null;
  setMemories(memories: PairMemory[]): void;
  setMemoriesForConversation(conversationId: string, memories: PairMemory[]): void;
  upsertMemory(memory: PairMemory, conversationId: string): void;
  setMemoryPanel(patch: Partial<MemoryPanelState>): void;
  /** 写入一页指标。replace（缺省）整体覆盖；append 按 keyset 分页追加并按 metric_id 去重。 */
  setMetricsPage(
    page: { metrics: TurnMetric[]; cursor: string | null },
    mode?: "replace" | "append",
  ): void;
  setMetricsError(message: string | null): void;
  setMetricsLoading(loading: boolean): void;
  setPromptAssembly(assembly: PromptAssemblyView): void;
  setPromptAssemblyLoading(loading: boolean): void;
  setPromptAssemblyError(message: string | null): void;

  /** 主工作区视图：聊天、角色库或角色创作。 */
  mainView: MainView;
  characterLibrary: CharacterLibraryViewModel;
  characterCreate: CharacterCreateViewModel;
  remotePairing: RemotePairingViewModel;

  /** power.get_status 结果或 power.status_changed 最新载荷；未查询过为 null。 */
  powerStatus: PowerStatusPayload | null;
  /** 最近一次 power.get_status 查询失败原文（如 power_status_unavailable）；成功读取后清除。 */
  powerError: string | null;
  /** 是否有 power.get_status 查询在途（由 usePowerStatusQuery 维护）。 */
  powerQueryInFlight: boolean;
  /** 用户关闭提示后，本次 at_risk 持续期内不再提示；at_risk 消失（false 到达）时复位。 */
  powerPromptDismissed: boolean;
  /** 写入一次成功读取的电源状态（主动查询或事件共用）；at_risk=false 复位关闭标记。 */
  setPowerStatus(payload: PowerStatusPayload): void;
  /** 如实记录查询失败原文；不伪造任何成功状态。 */
  setPowerError(message: string): void;
  setPowerQueryInFlight(inFlight: boolean): void;
  dismissPowerPrompt(): void;
  setMainView(view: MainView): void;
  setCharacterLibrary(partial: Partial<CharacterLibraryViewModel>): void;
  setCharacterCreate(partial: Partial<CharacterCreateViewModel>): void;
  setRemotePairing(partial: Partial<RemotePairingViewModel>): void;
  /** 合并 serve 地址载荷（serve.started 事件与 remote.issue_code 返回同形）。 */
  setServeAddress(payload: unknown): void;
  setTunnelStatus(status: {
    state: TunnelState;
    public_url: string | null;
    hostname: string | null;
    error: string | null;
  }): void;
  setTunnelStarting(): void;
  setTunnelStopping(): void;
  setTunnelFailed(error: string): void;
  /** 隧道停止或状态查询请求失败：记录错误原文，隧道状态保持不变。 */
  setTunnelRequestFailed(error: string): void;
  hydrate(snapshot: DesktopSnapshot): void;
  applyEvents(events: DesktopStreamEvent[]): void;
  /** 装载 conversation.open 的只读结果并打开对应标签，不改全局当前聊天。 */
  hydrateConversationView(result: ConversationOpenResult, bufferedEvents?: DesktopStreamEvent[]): void;
  /** 打开或聚焦本窗口标签。 */
  openConversationTab(conversationId: string): void;
  /** 只移除本窗口标签，不触发后端关闭或取消；关闭活动标签后选右侧相邻、无右侧选左侧。 */
  closeConversationTab(conversationId: string): void;
  setConversationSyncing(conversationId: string, syncing: boolean): void;
  setStatus(status: DesktopStatus, error?: string | null): void;
  setTheme(theme: "dark" | "light"): void;
  setComposerTarget(target: "character" | "assistant"): void;
  setApprovalResolving(approvalId: string, resolving: boolean): void;
  dismissToast(id: string): void;
  pushToast(toast: StoreToast): void;
  setConfigSnapshot(snapshot: Record<string, unknown> | null): void;
}

export type DesktopRenderState = Pick<
  DesktopState,
  | "status"
  | "error"
  | "resyncing"
  | "theme"
  | "composerTarget"
  | "projectsById"
  | "conversationsById"
  | "messagesById"
  | "messageIdsByConversation"
  | "toolRunsById"
  | "toolIdsByConversation"
  | "queueItemsByConversation"
  | "currentAccountId"
  | "currentAccount"
  | "accounts"
  | "currentProjectId"
  | "currentConversationId"
  | "pair"
  | "pairs"
  | "activeTask"
  | "activeTasksByConversation"
  | "busy"
  | "approvals"
  | "approvalResolvingById"
  | "reviewByConversation"
  | "voice"
  | "toasts"
  | "configSnapshot"
  | "openConversationIds"
  | "activeConversationId"
  | "activeProjectId"
  | "syncingConversationIds"
  | "mainView"
  | "characterLibrary"
  | "characterCreate"
  | "remotePairing"
>;

const emptyVoice: VoiceState = {
  supported: false,
  assistant_voice_enabled: false,
  vad: "idle",
  vad_enabled: false,
  ptt: false,
  tts: "idle",
  asr_partial: "",
  error: null,
  speech_queue_len: 0,
};

/** 启动 URL 中的窗口参数（独立聊天窗口由 Rust 带 query 创建）。 */
function readUrlParam(name: string): string | null {
  const value = new URLSearchParams(window.location.search).get(name);
  return value && value.length > 0 ? value : null;
}

/** 聊天窗口启动时携带的会话 id；有值时首次水合不播种标签，等 conversation.open 打开。 */
const initialUrlConversationId = readUrlParam("conversation_id");

/** store 中的数据字段（不含操作方法）。 */
type DesktopData = {
  [K in keyof DesktopState as DesktopState[K] extends (...args: never[]) => unknown ? never : K]: DesktopState[K];
};

function createInitialState(): DesktopData {
  return {
    status: "booting",
    error: null,
    resyncing: false,
    theme: readThemePreference(),
    composerTarget: "character",
    projectsById: {},
    conversationsById: {},
    messagesById: {},
    messageIdsByConversation: {},
    toolRunsById: {},
    toolIdsByConversation: {},
    queueItemsByConversation: {},
    currentAccountId: "",
    accountGeneration: 0,
    currentAccount: null,
    accounts: [],
    currentProjectId: "",
    currentConversationId: "",
    pair: null,
    pairs: [],
    activeTask: null,
    activeTasksByConversation: {},
    busy: false,
    approvals: [],
    approvalResolvingById: {},
    reviewByConversation: {},
    voice: emptyVoice,
    toasts: [],
    configSnapshot: null,
    lastSequence: -1,
    needsBootstrap: false,
    streamId: null,
    eventBuffer: [],
    conversationViewSequence: {},
    viewId: readUrlParam("view_id") ?? crypto.randomUUID(),
    openConversationIds: [],
    activeConversationId: null,
    activeProjectId: null,
    syncingConversationIds: {},
    mainView: "chat",
    characterLibrary: { cards: [], loading: false, error: null, loaded: false },
    characterCreate: {
      requestedCardId: null,
      cardId: null,
      card: null,
      readOnly: false,
      loading: false,
      error: null,
    },
    remotePairing: {
      code: null,
      ttlSeconds: 300,
      issuedAtEpochMs: null,
      devices: [],
      loading: false,
      error: null,
      serveAddress: null,
      servePort: null,
      serveMode: null,
      serveUnavailableReason: null,
      serveFailure: null,
      devicesRevision: 0,
      tunnel: {
        state: "off",
        publicUrl: null,
        hostname: null,
        error: null,
        requestError: null,
        loading: false,
      },
    },
    powerStatus: null,
    powerError: null,
    powerQueryInFlight: false,
    powerPromptDismissed: false,
    summariesByConversation: {},
    memories: [],
    memoriesByConversation: {},
    memoryPanel: { conversationId: null, loading: false, error: null, loaded: false },
    backendInfo: null,
    summaryRegenerateTarget: null,
    turnMetrics: [],
    metricsCursor: null,
    metricsLoading: false,
    metricsError: null,
    promptAssembly: null,
    promptAssemblyLoading: false,
    promptAssemblyError: null,
  };
}

function readThemePreference(): "dark" | "light" {
  return window.localStorage.getItem("pair-harness-theme") === "light" ? "light" : "dark";
}

/** 账号切换：账号级数据回到初始状态；连接、主题、通知、后端模式与本机电源状态沿用。 */
function resetAccountScope(state: DesktopState): DesktopState {
  return {
    ...state,
    ...createInitialState(),
    status: state.status,
    error: state.error,
    resyncing: state.resyncing,
    theme: state.theme,
    toasts: state.toasts,
    accounts: state.accounts,
    accountGeneration: state.accountGeneration,
    lastSequence: state.lastSequence,
    needsBootstrap: state.needsBootstrap,
    streamId: state.streamId,
    eventBuffer: state.eventBuffer,
    viewId: state.viewId,
    backendInfo: state.backendInfo,
    powerStatus: state.powerStatus,
    powerError: state.powerError,
    powerQueryInFlight: state.powerQueryInFlight,
    powerPromptDismissed: state.powerPromptDismissed,
  };
}

function indexSnapshot(snapshot: DesktopSnapshot) {
  const projectsById: Record<string, ProjectRecord> = {};
  const conversationsById: Record<string, ConversationRecord> = {};
  for (const project of snapshot.projects) {
    projectsById[project.project_id] = project;
    for (const conversation of project.conversations) {
      conversationsById[conversation.conversation_id] = conversation;
    }
  }
  const messagesById: Record<string, Message> = {};
  const messageIdsByConversation: Record<string, string[]> = {};
  for (const message of snapshot.messages) {
    messagesById[message.message_id] = message;
    (messageIdsByConversation[message.conversation_id] ??= []).push(message.message_id);
  }
  const toolRunsById: Record<string, ToolRun> = {};
  const toolIdsByConversation: Record<string, string[]> = {};
  for (const toolRun of snapshot.tool_runs) {
    const key = toolRunKey(toolRun);
    toolRunsById[key] = toolRun;
    (toolIdsByConversation[toolRun.conversation_id] ??= []).push(key);
  }
  const queueItemsByConversation: Record<string, QueueItem[]> = {};
  for (const item of snapshot.queue_items) {
    (queueItemsByConversation[item.conversation_id] ??= []).push(item);
  }
  return {
    projectsById,
    conversationsById,
    messagesById,
    messageIdsByConversation,
    toolRunsById,
    toolIdsByConversation,
    queueItemsByConversation,
  };
}

function mergeIndexedConversationCache<T>(
  existingById: Record<string, T>,
  existingIdsByConversation: Record<string, string[]>,
  incomingById: Record<string, T>,
  incomingIdsByConversation: Record<string, string[]>,
  replacedConversationIds: string[],
): { byId: Record<string, T>; idsByConversation: Record<string, string[]> } {
  const byId = { ...existingById };
  const idsByConversation = { ...existingIdsByConversation };
  for (const conversationId of replacedConversationIds) {
    for (const id of existingIdsByConversation[conversationId] ?? []) {
      delete byId[id];
    }
    idsByConversation[conversationId] = incomingIdsByConversation[conversationId] ?? [];
  }
  Object.assign(byId, incomingById);
  return { byId, idsByConversation };
}

/** 一批事件内的写时复制：索引表和 id 列表在本批第一次写入时复制一份，
    之后的事件原地写入这份尚未发布的副本，整批只复制一次。 */
interface BatchDraft {
  owned: WeakSet<object>;
}

function createBatchDraft(): BatchDraft {
  return { owned: new WeakSet() };
}

function ownRecord<V>(draft: BatchDraft, record: Record<string, V>): Record<string, V> {
  if (draft.owned.has(record)) return record;
  const copy = { ...record };
  draft.owned.add(copy);
  return copy;
}

function ownList<V>(draft: BatchDraft, list: V[]): V[] {
  if (draft.owned.has(list)) return list;
  const copy = [...list];
  draft.owned.add(copy);
  return copy;
}

/** byId 的每个键都在其会话的 id 列表里，所以 byId 已有的记录只替换对象，新记录才追加 id。 */
function upsertIndexed<T>(
  draft: BatchDraft,
  byId: Record<string, T>,
  idsByConversation: Record<string, string[]>,
  conversationId: string,
  id: string,
  item: T,
): { byId: Record<string, T>; idsByConversation: Record<string, string[]> } {
  const isNew = byId[id] === undefined;
  const nextById = ownRecord(draft, byId);
  nextById[id] = item;
  if (!isNew) return { byId: nextById, idsByConversation };
  const nextIdsByConversation = ownRecord(draft, idsByConversation);
  const ids = ownList(draft, nextIdsByConversation[conversationId] ?? []);
  ids.push(id);
  nextIdsByConversation[conversationId] = ids;
  return { byId: nextById, idsByConversation: nextIdsByConversation };
}

/** 装载结果与缓存记录逐字段比较，嵌套对象按 JSON 文本比较；相同则沿用缓存对象。 */
function sameRecord(current: object, next: object): boolean {
  const currentFields = current as Record<string, unknown>;
  const nextFields = next as Record<string, unknown>;
  const keys = Object.keys(nextFields);
  if (keys.length !== Object.keys(currentFields).length) return false;
  return keys.every((key) => {
    const left = currentFields[key];
    const right = nextFields[key];
    if (Object.is(left, right)) return true;
    return (
      typeof left === "object" &&
      left !== null &&
      typeof right === "object" &&
      right !== null &&
      JSON.stringify(left) === JSON.stringify(right)
    );
  });
}

function sameList<V>(left: readonly V[], right: readonly V[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

/** 按会话整体替换一组记录：内容未变的记录沿用缓存对象，本会话不在结果里的旧记录移出索引；
    什么都没变时返回原来的两张表。 */
function replaceConversationRecords<T extends object>(
  byId: Record<string, T>,
  idsByConversation: Record<string, string[]>,
  conversationId: string,
  records: readonly T[],
  keyOf: (record: T) => string,
): { byId: Record<string, T>; idsByConversation: Record<string, string[]> } {
  let nextById = byId;
  const writable = () => (nextById === byId ? (nextById = { ...byId }) : nextById);
  const ids = records.map(keyOf);
  records.forEach((record, index) => {
    const cached = byId[ids[index]];
    if (cached === undefined || !sameRecord(cached, record)) writable()[ids[index]] = record;
  });
  const previousIds = idsByConversation[conversationId] ?? [];
  const kept = new Set(ids);
  for (const id of previousIds) {
    if (!kept.has(id)) delete writable()[id];
  }
  return {
    byId: nextById,
    idsByConversation:
      idsByConversation[conversationId] !== undefined && sameList(previousIds, ids)
        ? idsByConversation
        : { ...idsByConversation, [conversationId]: ids },
  };
}

/** 工具记录以 conversation_id + tool_call_id 复合键索引，两个会话复用同一 tool_call_id 时互不覆盖。 */
function toolRunKey(toolRun: ToolRun): string {
  return `${toolRun.conversation_id}\u0000${toolRun.tool_call_id}`;
}

/** 本窗口活动聊天有活动任务才算忙；activeTask 只保留本窗口聊天的任务。 */
function refreshWindowTask(state: {
  activeConversationId: string | null;
  activeTasksByConversation: Record<string, ActiveTask>;
}): { busy: boolean; activeTask: ActiveTask | null } {
  const conversationId = state.activeConversationId;
  const activeTask = conversationId
    ? (state.activeTasksByConversation[conversationId] ?? null)
    : null;
  return { busy: activeTask !== null, activeTask };
}

/** 移除标签后的相邻选择：先右侧相邻，无右侧取左侧，全空为 null。 */
function closeTabOn(
  ids: string[],
  active: string | null,
  conversationId: string,
): { ids: string[]; active: string | null } {
  const index = ids.indexOf(conversationId);
  if (index === -1) return { ids, active };
  const nextIds = ids.filter((id) => id !== conversationId);
  let nextActive = active;
  if (active === conversationId) {
    nextActive = nextIds[index] ?? nextIds[index - 1] ?? null;
  }
  return { ids: nextIds, active: nextActive };
}

/** 按当前已知会话修剪标签：会话消失或已归档的标签移除，活动标签被修剪时沿用相邻选择规则。 */
function pruneOpenTabs(
  state: Pick<DesktopState, "openConversationIds" | "activeConversationId" | "conversationsById">,
): { openConversationIds: string[]; activeConversationId: string | null } {
  let ids = state.openConversationIds;
  let active = state.activeConversationId;
  for (const id of state.openConversationIds) {
    const conversation = state.conversationsById[id];
    if (conversation === undefined || conversation.archived) {
      const closed = closeTabOn(ids, active, id);
      ids = closed.ids;
      active = closed.active;
    }
  }
  return { openConversationIds: ids, activeConversationId: active };
}

function pushToast(toasts: StoreToast[], toast: StoreToast): StoreToast[] {
  if (toasts.some((item) => item.id === toast.id)) return toasts;
  return [...toasts, toast].slice(-5);
}

function hydrateSnapshotState(state: DesktopState, snapshot: DesktopSnapshot): DesktopState {
  // 旧代次快照不能覆盖新代次状态；streamId 为空时是首次水合，任意快照都可建立代次。
  if (state.streamId !== null && snapshot.stream_id !== state.streamId) return state;
  const accountSwitched =
    state.currentAccountId !== "" && state.currentAccountId !== snapshot.current_account_id;
  const base = accountSwitched ? resetAccountScope(state) : state;
  const indexed = indexSnapshot(snapshot);
  // Sidecar 快照只携带全局当前聊天的消息详情。保留本窗口其他已打开标签的缓存，
  // 只替换快照明确覆盖的聊天。
  const replacedConversationIds = Array.from(
    new Set(
      [
        snapshot.current_conversation_id,
        ...Object.keys(indexed.messageIdsByConversation),
        ...Object.keys(indexed.toolIdsByConversation),
        ...Object.keys(indexed.queueItemsByConversation),
      ].filter(Boolean),
    ),
  );
  const messages = mergeIndexedConversationCache(
    base.messagesById,
    base.messageIdsByConversation,
    indexed.messagesById,
    indexed.messageIdsByConversation,
    replacedConversationIds,
  );
  const tools = mergeIndexedConversationCache(
    base.toolRunsById,
    base.toolIdsByConversation,
    indexed.toolRunsById,
    indexed.toolIdsByConversation,
    replacedConversationIds,
  );
  const queueItemsByConversation = { ...base.queueItemsByConversation };
  for (const conversationId of replacedConversationIds) {
    queueItemsByConversation[conversationId] =
      indexed.queueItemsByConversation[conversationId] ?? [];
  }
  // 快照重建全账号会话目录后，已归档或消失的会话关闭标签。
  const pruned = pruneOpenTabs({
    openConversationIds: base.openConversationIds,
    activeConversationId: base.activeConversationId,
    conversationsById: indexed.conversationsById,
  });
  // 本窗口没有打开任何标签、且不是等待 conversation.open 的聊天窗口时，跟随全局当前聊天
  // 打开一个标签，主窗口 bootstrap 或重连后工作区始终有内容。
  const seedInitialTab =
    pruned.openConversationIds.length === 0 &&
    initialUrlConversationId === null &&
    snapshot.current_conversation_id !== "";
  const openConversationIds = seedInitialTab
    ? [snapshot.current_conversation_id]
    : pruned.openConversationIds;
  const activeConversationId = seedInitialTab
    ? snapshot.current_conversation_id
    : pruned.activeConversationId;
  // 项目上下文跟随本窗口活动标签，不跟随可能被另一个窗口改写的 current_conversation_id。
  const selectedConversation = activeConversationId
    ? indexed.conversationsById[activeConversationId]
    : undefined;
  const selectedPair = selectedConversation
    ? snapshot.pairs.find((item) => item.pair_id === selectedConversation.pair_id) ??
      base.pairs.find((item) => item.pair_id === selectedConversation.pair_id) ??
      snapshot.pair
    : snapshot.pair;
  const hydrated: DesktopState = {
    ...base,
    projectsById: indexed.projectsById,
    conversationsById: indexed.conversationsById,
    messagesById: messages.byId,
    messageIdsByConversation: messages.idsByConversation,
    toolRunsById: tools.byId,
    toolIdsByConversation: tools.idsByConversation,
    queueItemsByConversation,
    status: "ready",
    error: null,
    resyncing: false,
    currentAccountId: snapshot.current_account_id,
    accountGeneration: accountSwitched ? base.accountGeneration + 1 : base.accountGeneration,
    currentAccount: snapshot.current_account,
    accounts: snapshot.accounts,
    currentProjectId: snapshot.current_project_id,
    currentConversationId: snapshot.current_conversation_id,
    pair: selectedPair,
    pairs: snapshot.pairs,
    activeTasksByConversation: Object.fromEntries(
      snapshot.active_tasks.map((task) => [task.conversation_id, task]),
    ),
    approvals: snapshot.approvals,
    approvalResolvingById: {},
    reviewByConversation: {},
    voice: snapshot.voice,
    lastSequence: snapshot.sequence,
    needsBootstrap: false,
    streamId: snapshot.stream_id,
    eventBuffer: [],
    conversationViewSequence:
      snapshot.stream_id === base.streamId
        ? pendingViewSequences(
            base.conversationViewSequence,
            snapshot.sequence,
            replacedConversationIds,
          )
        : {},
    openConversationIds,
    activeConversationId,
    activeProjectId:
      selectedConversation?.project_id ??
      (activeConversationId ? base.activeProjectId : null),
  };
  return { ...hydrated, ...refreshWindowTask(hydrated) };
}

function applyErrorReported(state: DesktopState, event: DesktopStreamEvent): DesktopState {
  // fatal 接管整屏；其余级别保留已加载内容，进 Toast 队列。
  const payload = event.payload as { message?: string; severity?: string; code?: string };
  const severity = payload.severity ?? "fatal";
  if (severity === "fatal") {
    return {
      ...state,
      status: "error",
      error: String(payload.message ?? "桌面后端错误"),
    };
  }
  const text = String(payload.message ?? "");
  // Rust 的 publish_disconnected 在同一次调用里先发 connection.status{disconnected}，
  // 再发这条 error.reported。两路描述同一个事实：这条错误上屏时连接确实已断开，
  // 连接状态同样记为 disconnected，药丸与通知保持一致。
  const disconnected = payload.code === "backend_disconnected";
  return {
    ...state,
    ...(disconnected
      ? { status: "disconnected" as DesktopStatus, needsBootstrap: false, resyncing: false }
      : {}),
    error: text,
    remotePairing: remotePairingWithServeFailure(state.remotePairing, payload.code, text),
    toasts: pushToast(state.toasts, {
      id: `${payload.code ?? "error"}:${text}`,
      kind: severity === "info" ? "info" : "warning",
      text,
      hasDetails: Boolean(payload.code),
    }),
  };
}

/** backend.ready 的运行模式字段；整批缺失时保持上一次的值。 */
function readBackendInfo(payload: unknown, previous: BackendInfo | null): BackendInfo | null {
  const raw = (payload && typeof payload === "object" ? payload : {}) as Record<string, unknown>;
  const pid = typeof raw.pid === "number" ? raw.pid : null;
  const demo = typeof raw.demo === "boolean" ? raw.demo : null;
  const modeSource =
    typeof raw.mode_source === "string" && raw.mode_source ? raw.mode_source : null;
  if (pid === null && demo === null && modeSource === null) return previous;
  return { pid, demo, modeSource };
}

/**
 * 合并 serve 地址载荷（serve.started 事件与 remote.issue_code 的 serve_address 同形）。
 *
 * 缺 port 属协议违规，清空地址并如实报告；host 为 null 表示服务已监听但没有可用的
 * 局域网地址，此时清空地址并保留端口与原因码。
 */
function remotePairingWithServeAddress(
  remotePairing: DesktopState["remotePairing"],
  payload: unknown,
): DesktopState["remotePairing"] {
  const raw = (payload && typeof payload === "object" ? payload : null) as
    | { host?: unknown; port?: unknown; mode?: unknown; tls?: unknown; reason?: unknown }
    | null;
  if (!raw) return remotePairing;
  if (typeof raw.port !== "number") {
    // 缺 port 是协议违规：地址此刻不可知，不得继续展示上一次的二维码成功态。
    return {
      ...remotePairing,
      serveAddress: null,
      serveUnavailableReason: null,
      serveFailure: "远程服务地址报文不符合协议：缺少 port",
    };
  }
  const host = typeof raw.host === "string" && raw.host ? raw.host : null;
  const reason = typeof raw.reason === "string" && raw.reason ? raw.reason : null;
  const mode = raw.mode === "lan" || raw.mode === "loopback" ? raw.mode : undefined;
  const tls = typeof raw.tls === "boolean" ? raw.tls : undefined;
  return {
    ...remotePairing,
    serveAddress: host
      ? {
          host,
          port: raw.port,
          ...(mode !== undefined ? { mode } : {}),
          ...(tls !== undefined ? { tls } : {}),
        }
      : null,
    servePort: raw.port,
    serveMode: mode ?? remotePairing.serveMode,
    serveUnavailableReason: host ? null : reason,
    // 服务已启动：上一次「启动失败」的报文条件已结束。
    serveFailure: null,
  };
}

/** 远程服务启动失败的报文进远程设备页，说明二维码不可用的原因。 */
function remotePairingWithServeFailure(
  remotePairing: DesktopState["remotePairing"],
  code: string | undefined,
  text: string,
): DesktopState["remotePairing"] {
  if (code !== "serve_start_failed") return remotePairing;
  return { ...remotePairing, serveFailure: text };
}

/** 连接恢复后撤回描述「已断开/正在重连」的瞬时通知：该条件已经结束。
    只按协议错误码匹配（backend_disconnected），不解析、不猜测通知文案。 */
function retractDisconnectNotices(state: DesktopState): DesktopState {
  const toasts = state.toasts.filter((toast) => !toast.id.startsWith(DISCONNECT_TOAST_PREFIX));
  if (toasts.length === state.toasts.length) return state;
  const retracted = state.toasts.filter((toast) => toast.id.startsWith(DISCONNECT_TOAST_PREFIX));
  const errorWasDisconnect = retracted.some((toast) => toast.text === state.error);
  return { ...state, toasts, error: errorWasDisconnect ? null : state.error };
}

function applyConnectionStatus(state: DesktopState, event: DesktopStreamEvent): DesktopState {
  const streamId = event.stream_id;
  const status = String(event.payload.status ?? "");
  // connected 总是权威，新代次到达时用它切换 streamId；
  // disconnected 只接受当前代次，旧 reader 迟到的 disconnected 不能覆盖新连接。
  if (status === "connected") {
    // toast 没有 TTL，连接恢复后显式撤回「正在重连…」这类瞬时通知。
    const recovered = retractDisconnectNotices(state);
    return {
      ...recovered,
      streamId: streamId ?? state.streamId,
      status: "booting",
      needsBootstrap: true,
      eventBuffer: [],
    };
  }
  if (status === "disconnected") {
    if (state.streamId !== null && streamId !== undefined && streamId !== state.streamId) {
      return state;
    }
    return {
      ...state,
      status: "disconnected",
      needsBootstrap: false,
      resyncing: false,
      eventBuffer: [],
    };
  }
  return state;
}

function replayBufferedEvents(state: DesktopState, draft: BatchDraft): DesktopState {
  const buffered = state.eventBuffer;
  if (buffered.length === 0) return state;
  let current: DesktopState = { ...state, eventBuffer: [] };
  for (const event of buffered) {
    current = applyEvent(current, event, draft);
  }
  return current;
}

/** Sidecar 发出的事件都带序号；Rust 宿主合成的事件不带。 */
function isSequencedEvent(event: DesktopStreamEvent): event is DesktopEvent {
  return event.sequence !== undefined;
}

/**
 * 暂存等待快照核对的事件。错误报告不进快照，暂存的同时立即上屏：
 * 没有快照时致命启动错误也要显示，重放时按序号推进游标。
 */
function bufferEvent(state: DesktopState, event: DesktopEvent): DesktopState {
  const buffered = { ...state, eventBuffer: [...state.eventBuffer, event] };
  return event.event === "error.reported" ? applyErrorReported(buffered, event) : buffered;
}

function applyEvent(state: DesktopState, event: DesktopStreamEvent, draft: BatchDraft): DesktopState {
  // 宿主事件不带序号，不经过序号过滤。
  if (!isSequencedEvent(event)) {
    return event.event === "connection.status"
      ? applyConnectionStatus(state, event)
      : applyErrorReported(state, event);
  }
  // 旧代次事件直接丢弃。
  if (event.stream_id !== undefined && state.streamId !== null && event.stream_id !== state.streamId) {
    return state;
  }
  if (event.event === "state.snapshot") {
    const hydrated = hydrateSnapshotState(state, event.payload as unknown as DesktopSnapshot);
    if (hydrated === state) return state;
    // 水合会清空 eventBuffer；保留待核对事件，水合后按快照序号重放。
    return replayBufferedEvents({ ...hydrated, eventBuffer: state.eventBuffer }, draft);
  }
  // 新代次 bootstrap 或序号缺口期间暂存业务事件，等快照水合后核对重放。
  if (state.needsBootstrap || state.status === "booting") {
    return bufferEvent(state, event);
  }
  // 同代次重复序号直接丢弃。
  if (event.sequence <= state.lastSequence) return state;
  if (state.lastSequence >= 0 && event.sequence !== state.lastSequence + 1) {
    // 序号缺口：重新拉取快照，界面保持可用；缺口后的事件等待快照核对。
    return bufferEvent({ ...state, needsBootstrap: true, resyncing: true }, event);
  }
  if (includedInConversationView(state.conversationViewSequence, event)) {
    // conversation.open 的装载结果已包含这条事件的效果，只推进序号。
    return {
      ...state,
      lastSequence: event.sequence,
      conversationViewSequence: pendingViewSequences(
        state.conversationViewSequence,
        event.sequence,
      ),
    };
  }

  return applyBusinessEvent(state, event, draft);
}

/** conversation.open 按会话整体替换的数据（消息、工具、队列）只受这些事件影响。 */
const CONVERSATION_VIEW_EVENTS: ReadonlySet<DesktopEvent["event"]> = new Set([
  "message.created",
  "message.status_changed",
  "message.delta",
  "message.finalized",
  "tool_run.upserted",
  "queue.changed",
]);

function includedInConversationView(
  viewSequence: Record<string, number>,
  event: DesktopEvent,
): boolean {
  if (!CONVERSATION_VIEW_EVENTS.has(event.event)) return false;
  return Object.entries(viewSequence).some(
    ([conversationId, sequence]) =>
      event.sequence <= sequence && eventTargetsConversation(event, conversationId),
  );
}

/** 保留仍有待跳过事件的会话序号：不超过 lastSequence 或数据已被快照替换的条目移除。 */
function pendingViewSequences(
  viewSequence: Record<string, number>,
  lastSequence: number,
  replacedConversationIds: readonly string[] = [],
): Record<string, number> {
  const pending: Record<string, number> = {};
  for (const [conversationId, sequence] of Object.entries(viewSequence)) {
    if (sequence > lastSequence && !replacedConversationIds.includes(conversationId)) {
      pending[conversationId] = sequence;
    }
  }
  return pending;
}

function eventTargetsConversation(event: DesktopEvent, conversationId: string): boolean {
  const payload = event.payload as Record<string, unknown>;
  const direct = payload.conversation_id;
  if (direct === conversationId) return true;
  for (const key of ["message", "tool_run", "turn", "conversation", "active_task"]) {
    const nested = payload[key];
    if (nested && typeof nested === "object") {
      const nestedConversationId = (nested as Record<string, unknown>).conversation_id;
      if (nestedConversationId === conversationId) return true;
    }
  }
  const activeTasks = payload.active_tasks;
  return (
    Array.isArray(activeTasks) &&
    activeTasks.some(
      (task) =>
        task &&
        typeof task === "object" &&
        (task as Record<string, unknown>).conversation_id === conversationId,
    )
  );
}

/** tunnel.* 事件是隧道状态的权威来源：整体替换隧道视图并清除上一次请求错误。 */
function remotePairingWithTunnelEvent(
  remotePairing: DesktopState["remotePairing"],
  event: DesktopEvent,
): DesktopState["remotePairing"] {
  const base = { publicUrl: null, hostname: null, error: null, requestError: null, loading: false };
  let tunnel: TunnelViewModel;
  if (event.event === "tunnel.started") {
    const payload = event.payload as unknown as TunnelStartedPayload;
    tunnel = { ...base, state: "ready", publicUrl: payload.public_url, hostname: payload.hostname };
  } else if (event.event === "tunnel.failed") {
    const payload = event.payload as unknown as TunnelFailedPayload;
    tunnel = { ...base, state: "failed", error: payload.error };
  } else {
    tunnel = { ...base, state: "off" };
  }
  return { ...remotePairing, tunnel };
}

function applyBusinessEvent(state: DesktopState, event: DesktopEvent, draft: BatchDraft): DesktopState {
  const next: DesktopState = { ...state, lastSequence: event.sequence };
  switch (event.event) {
    case "backend.ready":
      // 新 stream 的 bootstrap 起点：快照水合前暂存业务事件，AppController 看到
      // needsBootstrap 会重新拉快照。Sidecar 自报的运行模式未上报的字段保持 null。
      next.backendInfo = readBackendInfo(event.payload, state.backendInfo);
      next.status = "booting";
      next.needsBootstrap = true;
      next.eventBuffer = [];
      break;
    case "message.created": {
      const message = event.payload.message as Message;
      const indexed = upsertIndexed(
        draft,
        next.messagesById,
        next.messageIdsByConversation,
        message.conversation_id,
        message.message_id,
        message,
      );
      next.messagesById = indexed.byId;
      next.messageIdsByConversation = indexed.idsByConversation;
      break;
    }
    case "message.status_changed": {
      // 按 id 对账消息状态。完整 Message 执行 upsert（先于 message.created 到达也能落库）；
      // 缺少必要字段时重新同步快照。
      const message = event.payload.message as Partial<Message> | null | undefined;
      const hasRequiredFields =
        !!message &&
        typeof message.message_id === "string" &&
        typeof message.conversation_id === "string" &&
        typeof message.pair_id === "string" &&
        typeof message.source === "string" &&
        typeof message.kind === "string" &&
        typeof message.text === "string" &&
        typeof message.created_at === "string";
      if (!hasRequiredFields) {
        return {
          ...next,
          needsBootstrap: true,
          resyncing: true,
          eventBuffer: [...next.eventBuffer, event],
        };
      }
      const indexed = upsertIndexed(
        draft,
        next.messagesById,
        next.messageIdsByConversation,
        message.conversation_id!,
        message.message_id!,
        message as Message,
      );
      next.messagesById = indexed.byId;
      next.messageIdsByConversation = indexed.idsByConversation;
      break;
    }
    case "message.delta": {
      // 同一批里连续到达的分片写进同一份消息表副本，整批只复制一次。
      const payload = event.payload as unknown as MessageDeltaPayload;
      const message = applyMessageDelta(next.messagesById[payload.message_id], payload, {
        pairId:
          next.conversationsById[payload.conversation_id]?.pair_id ?? next.pair?.pair_id ?? "",
        createdAt: new Date().toISOString(),
      });
      const indexed = upsertIndexed(
        draft,
        next.messagesById,
        next.messageIdsByConversation,
        payload.conversation_id,
        payload.message_id,
        message,
      );
      next.messagesById = indexed.byId;
      next.messageIdsByConversation = indexed.idsByConversation;
      break;
    }
    case "message.finalized": {
      const messageId = String(event.payload.message_id ?? "");
      const current = next.messagesById[messageId];
      if (current) {
        const messagesById = ownRecord(draft, next.messagesById);
        messagesById[messageId] = { ...current, streaming: false };
        next.messagesById = messagesById;
      }
      break;
    }
    case "tool_run.upserted": {
      const toolRun = event.payload.tool_run as ToolRun;
      const key = toolRunKey(toolRun);
      const indexed = upsertIndexed(
        draft,
        next.toolRunsById,
        next.toolIdsByConversation,
        toolRun.conversation_id,
        key,
        toolRun,
      );
      next.toolRunsById = indexed.byId;
      next.toolIdsByConversation = indexed.idsByConversation;
      break;
    }
    case "approval.requested": {
      const approval = event.payload as unknown as PendingApproval;
      next.approvals = [
        ...next.approvals.filter((item) => item.approval_id !== approval.approval_id),
        approval,
      ];
      break;
    }
    case "approval.resolved": {
      // 首个终态获胜；待审批移出队列并解除按钮锁定。
      const approvalId = String(event.payload.approval_id);
      next.approvals = next.approvals.filter((item) => item.approval_id !== approvalId);
      const { [approvalId]: _resolved, ...remaining } = next.approvalResolvingById;
      next.approvalResolvingById = remaining;
      break;
    }
    case "task.busy_changed": {
      // active_tasks 是事件发生后的完整集合，整体替换，增删事件丢失也不会留下幽灵忙碌状态。
      const payload = event.payload as { active_tasks: ActiveTask[] };
      next.activeTasksByConversation = Object.fromEntries(
        payload.active_tasks.map((task) => [task.conversation_id, task]),
      );
      Object.assign(next, refreshWindowTask(next));
      break;
    }
    case "queue.changed": {
      // 队列变化推送该聊天的全量有序列表，直接替换。
      const payload = event.payload as { conversation_id: string; items: QueueItem[] };
      next.queueItemsByConversation = {
        ...next.queueItemsByConversation,
        [payload.conversation_id]: payload.items,
      };
      break;
    }
    case "review.started":
    case "review.completed":
    case "review.failed": {
      // 审查智能体真正被调用时才有审查状态，按事件归属的聊天存放。
      // review.completed 带 allow 与 reason，review.failed 带 reason，review.started 不带二者。
      const payload = event.payload as { conversation_id: string; allow: boolean; reason: string };
      const review: ReviewStatus =
        event.event === "review.started"
          ? { active: true, text: null }
          : event.event === "review.failed"
            ? { active: false, text: `审查失败：${payload.reason}` }
            : { active: false, text: payload.allow ? "审查通过" : `审查否决：${payload.reason}` };
      next.reviewByConversation = { ...next.reviewByConversation, [payload.conversation_id]: review };
      break;
    }
    case "project.changed": {
      // project.changed 只携带项目字段，会话列表沿用已知记录。
      const project = event.payload.project as Omit<ProjectRecord, "conversations">;
      const conversations = next.projectsById[project.project_id]?.conversations ?? [];
      next.projectsById = {
        ...next.projectsById,
        [project.project_id]: { ...project, conversations },
      };
      // 项目归档时关闭本窗口属于该项目的标签。
      if (project.archived) {
        for (const id of next.openConversationIds) {
          if (next.conversationsById[id]?.project_id !== project.project_id) continue;
          const closed = closeTabOn(next.openConversationIds, next.activeConversationId, id);
          next.openConversationIds = closed.ids;
          next.activeConversationId = closed.active;
        }
        next.activeProjectId = next.activeConversationId
          ? next.conversationsById[next.activeConversationId]?.project_id ?? null
          : null;
        Object.assign(next, refreshWindowTask(next));
      }
      break;
    }
    case "conversation.changed": {
      const conversation = event.payload.conversation as ConversationRecord;
      const conversationId = conversation.conversation_id;
      next.conversationsById = { ...next.conversationsById, [conversationId]: conversation };
      // 侧栏渲染自 projectsById[].conversations，同步更新项目内的会话条目；
      // 与快照一致，项目列表只保留未归档的会话。
      const projectId = conversation.project_id;
      const project = projectId ? next.projectsById[projectId] : undefined;
      if (projectId && project) {
        const others = project.conversations.filter((item) => item.conversation_id !== conversationId);
        const exists = others.length !== project.conversations.length;
        const conversations = conversation.archived
          ? others
          : exists
            ? project.conversations.map((item) =>
                item.conversation_id === conversationId ? conversation : item,
              )
            : [...project.conversations, conversation];
        next.projectsById = { ...next.projectsById, [projectId]: { ...project, conversations } };
      }
      // 会话被归档时关闭本窗口对应标签，只关视图，不取消任务。
      if (conversation.archived) {
        const closed = closeTabOn(next.openConversationIds, next.activeConversationId, conversationId);
        next.openConversationIds = closed.ids;
        next.activeConversationId = closed.active;
        next.activeProjectId = next.activeConversationId
          ? next.conversationsById[next.activeConversationId]?.project_id ?? null
          : null;
        Object.assign(next, refreshWindowTask(next));
      }
      break;
    }
    case "voice.asr_partial":
      next.voice = { ...next.voice, asr_partial: String(event.payload.text ?? "") };
      break;
    case "voice.state_changed":
      next.voice = { ...next.voice, ...(event.payload.voice as Partial<VoiceState>) };
      break;
    case "voice.card_provision_changed": {
      // 卡音色状态变化同步到角色库摘要；音色详情由读取方经 card.get 获取。
      const payload = event.payload as unknown as VoiceCardProvisionChangedPayload;
      next.characterLibrary = {
        ...next.characterLibrary,
        cards: next.characterLibrary.cards.map((card) =>
          card.cardId === payload.card_id ? { ...card, voiceState: payload.state } : card,
        ),
      };
      break;
    }
    case "voice.provision_changed": {
      // 逐项进度投影到 configSnapshot.voice.speakers；命令结束后还会再取一次 config.get。
      const payload = event.payload as {
        account_id?: string;
        speaker_id?: string;
        state?: string;
        completed?: number;
        total?: number;
        error?: string | null;
        voice_id?: string | null;
      };
      if (
        payload.account_id &&
        next.currentAccountId &&
        payload.account_id !== next.currentAccountId
      ) {
        // 账号切换后，旧账号的迟到进度事件不能污染新账号的音色状态。
        break;
      }
      const speakerId = String(payload.speaker_id ?? "");
      if (speakerId) {
        const config = next.configSnapshot ?? {};
        const currentVoice =
          config.voice && typeof config.voice === "object" && !Array.isArray(config.voice)
            ? (config.voice as Record<string, unknown>)
            : {};
        const currentSpeakers = Array.isArray(currentVoice.speakers)
          ? [...currentVoice.speakers]
          : [];
        const index = currentSpeakers.findIndex(
          (item) =>
            item &&
            typeof item === "object" &&
            String((item as Record<string, unknown>).speaker_id ?? "") === speakerId,
        );
        const previous = index >= 0 ? currentSpeakers[index] : {};
        const updated = {
          ...(previous && typeof previous === "object" ? previous : {}),
          speaker_id: speakerId,
          ...(payload.state !== undefined ? { state: payload.state } : {}),
          ...(payload.completed !== undefined ? { completed: payload.completed } : {}),
          ...(payload.total !== undefined ? { total: payload.total } : {}),
          ...(payload.voice_id !== undefined ? { voice_id: payload.voice_id ?? "" } : {}),
          error: payload.error ?? null,
        };
        if (index >= 0) currentSpeakers[index] = updated;
        else currentSpeakers.push(updated);
        next.configSnapshot = {
          ...config,
          voice: { ...currentVoice, speakers: currentSpeakers },
        };
      }
      break;
    }
    case "summary.started":
    case "summary.completed":
    case "summary.failed": {
      // 摘要事件按 summary_id 覆盖；状态以事件名为准（started 的载荷是重新生成前的记录），
      // 失败事件携带 error_code 与 error 原文。
      const payload = event.payload as unknown as Omit<ConversationSummary, "status" | "content"> & {
        error_code?: string | null;
        error?: string | null;
      };
      const status: ConversationSummary["status"] =
        event.event === "summary.started"
          ? "running"
          : event.event === "summary.completed"
            ? "completed"
            : "failed";
      const summary: ConversationSummary = {
        summary_id: payload.summary_id,
        conversation_id: payload.conversation_id,
        status,
        covers_from_message_id: payload.covers_from_message_id,
        covers_to_message_id: payload.covers_to_message_id,
        covers_message_count: payload.covers_message_count,
        content: null,
        provider: payload.provider,
        model: payload.model,
        error_code: payload.error_code ?? null,
        error: payload.error ?? null,
        created_at: payload.created_at,
        updated_at: payload.updated_at,
      };
      const list = next.summariesByConversation[summary.conversation_id] ?? [];
      next.summariesByConversation = {
        ...next.summariesByConversation,
        [summary.conversation_id]: [
          ...list.filter((item) => item.summary_id !== summary.summary_id),
          summary,
        ],
      };
      if (status === "failed") {
        next.summaryRegenerateTarget = {
          summary_id: summary.summary_id,
          conversation_id: summary.conversation_id,
        };
      } else if (next.summaryRegenerateTarget?.summary_id === summary.summary_id) {
        next.summaryRegenerateTarget = null;
      }
      break;
    }
    case "memory.updated":
    case "memory.deleted": {
      // 记忆事件携带完整的扁平记录，按 memory_id 覆盖；删除是状态变为 deleted 的同一条记录。
      const memory = pairMemoryFromPayload(event.payload as unknown as MemoryWirePayload);
      next.memories = [
        ...next.memories.filter((item) => item.memory_id !== memory.memory_id),
        memory,
      ];
      const conversationId = memory.conversation_id;
      if (conversationId) {
        const list = next.memoriesByConversation[conversationId] ?? [];
        next.memoriesByConversation = {
          ...next.memoriesByConversation,
          [conversationId]: [
            ...list.filter((item) => item.memory_id !== memory.memory_id),
            memory,
          ],
        };
      }
      break;
    }
    case "conversation.card_missing": {
      // 聊天绑定的角色卡已删除：服务端回退为内置角色，提示进 Toast 队列。
      const payload = event.payload as { conversation_id: string; card_id: string; message: string };
      next.toasts = pushToast(next.toasts, {
        id: `card_missing:${payload.conversation_id}:${payload.card_id}`,
        kind: "warning",
        text: payload.message,
        hasDetails: true,
      });
      break;
    }
    case "diagnostic.warning":
      console.warn("[diagnostic.warning]", event.payload);
      break;
    case "error.reported":
      return applyErrorReported(next, event);
    case "serve.started":
      // host 为 null 表示服务已在监听但没有可用的局域网地址，原因见 reason。
      next.remotePairing = remotePairingWithServeAddress(next.remotePairing, event.payload);
      break;
    case "tunnel.started":
    case "tunnel.stopped":
    case "tunnel.failed":
      next.remotePairing = remotePairingWithTunnelEvent(next.remotePairing, event);
      break;
    case "remote.paired":
      // 配对码一次性有效，配对成功即作废；面板据 devicesRevision 变化重拉设备列表。
      next.remotePairing = {
        ...next.remotePairing,
        code: null,
        issuedAtEpochMs: null,
        devicesRevision: (next.remotePairing.devicesRevision ?? 0) + 1,
      };
      break;
    case "power.status_changed": {
      // 载荷与 power.get_status 结果同形，覆盖旧状态与旧查询错误；
      // at_risk 消失时复位关闭标记，再次出现时允许重新提示。
      const payload = event.payload as unknown as PowerStatusPayload;
      next.powerStatus = payload;
      next.powerError = null;
      if (!payload.at_risk) next.powerPromptDismissed = false;
      break;
    }
    case "account.changed": {
      // 登录、注册、切换与资料更新；账号切换时账号级数据回到初始状态，同账号更新不影响标签。
      const payload = event.payload as { account: AccountRecord; accounts: AccountListItem[] };
      const switched = payload.account.account_id !== next.currentAccountId;
      const updated =
        switched && next.currentAccountId !== "" ? resetAccountScope(next) : next;
      return {
        ...updated,
        accountGeneration: switched ? updated.accountGeneration + 1 : updated.accountGeneration,
        currentAccountId: payload.account.account_id,
        currentAccount: payload.account,
        accounts: payload.accounts,
      };
    }
  }
  return next;
}

export const desktopStore = createStore<DesktopState>((set) => ({
  ...createInitialState(),
  hydrate(snapshot) {
    set((state) => {
      const hydrated = hydrateSnapshotState(state, snapshot);
      if (hydrated === state) return state;
      // 直接水合（app.bootstrap 响应）也要重放水合前暂存的同代次事件。
      return replayBufferedEvents({ ...hydrated, eventBuffer: state.eventBuffer }, createBatchDraft());
    });
  },
  hydrateConversationView(result, bufferedEvents = []) {
    set((state) => {
      if (state.streamId !== null && result.stream_id !== state.streamId) return state;
      const conversation = result.conversation;
      const conversationId = conversation.conversation_id;
      // 只读装载不改变全局当前聊天，只合并该会话与其项目条目。
      const conversationsById = { ...state.conversationsById, [conversationId]: conversation };
      // conversation.open 的 project 不带会话列表，沿用已知列表并写入本会话。
      const projectId = result.project.project_id;
      const knownConversations = state.projectsById[projectId]?.conversations ?? [];
      const conversations = knownConversations.some((item) => item.conversation_id === conversationId)
        ? knownConversations.map((item) => (item.conversation_id === conversationId ? conversation : item))
        : [...knownConversations, conversation];
      const projectsById = { ...state.projectsById, [projectId]: { ...result.project, conversations } };
      // 消息、工具与队列按会话整体替换为本次装载结果，其他会话的缓存不受影响。
      // 内容未变的记录沿用缓存对象，已渲染的行不因切换聊天重渲染。
      const messages = replaceConversationRecords(
        state.messagesById,
        state.messageIdsByConversation,
        conversationId,
        result.messages,
        (item) => item.message_id,
      );
      const tools = replaceConversationRecords(
        state.toolRunsById,
        state.toolIdsByConversation,
        conversationId,
        result.tool_runs,
        toolRunKey,
      );
      const cachedQueue = state.queueItemsByConversation[conversationId];
      const queueUnchanged =
        cachedQueue !== undefined &&
        cachedQueue.length === result.queue_items.length &&
        cachedQueue.every((item, index) => sameRecord(item, result.queue_items[index]));
      const queueItemsByConversation = queueUnchanged
        ? state.queueItemsByConversation
        : { ...state.queueItemsByConversation, [conversationId]: result.queue_items };
      // 结果只带本会话的活动任务，其余聊天的运行中任务不受影响。
      const activeTasksByConversation = { ...state.activeTasksByConversation };
      if (result.active_task) {
        activeTasksByConversation[conversationId] = result.active_task;
      } else {
        delete activeTasksByConversation[conversationId];
      }
      const openConversationIds = state.openConversationIds.includes(conversationId)
        ? state.openConversationIds
        : [...state.openConversationIds, conversationId];
      const next: DesktopState = {
        ...state,
        conversationsById,
        projectsById,
        messagesById: messages.byId,
        messageIdsByConversation: messages.idsByConversation,
        toolRunsById: tools.byId,
        toolIdsByConversation: tools.idsByConversation,
        queueItemsByConversation,
        activeTasksByConversation,
        openConversationIds,
        activeConversationId: conversationId,
        activeProjectId: projectId,
        // 搭档未变时沿用原对象，依赖搭档的消息行不必重渲染。
        pair: state.pair !== null && sameRecord(state.pair, result.pair) ? state.pair : result.pair,
        pairs: state.pairs.some((item) => item.pair_id === result.pair.pair_id)
          ? state.pairs
          : [...state.pairs, result.pair],
      };
      // 装载结果反映 result.sequence 时的会话数据，窗口全局游标保持常驻订阅的进度。
      // 常驻订阅尚未应用、序号不超过 result.sequence 的会话内事件之后到达时由
      // conversationViewSequence 跳过，避免 message.delta 等事件重复叠加。
      const hydrated: DesktopState = {
        ...next,
        ...refreshWindowTask(next),
        streamId: result.stream_id,
        conversationViewSequence:
          result.sequence > state.lastSequence
            ? { ...state.conversationViewSequence, [conversationId]: result.sequence }
            : pendingViewSequences(state.conversationViewSequence, state.lastSequence, [
                conversationId,
              ]),
      };
      // 常驻订阅已应用、序号在 result.sequence 之后的目标会话事件被整体替换抹掉，
      // 按序号重放一次；更新的事件之后经常驻订阅正常到达。
      const seenSequences = new Set<number>();
      const wipedEvents = bufferedEvents
        .filter(isSequencedEvent)
        .filter((event) => {
          if (event.event === "state.snapshot") return false;
          if (event.stream_id !== undefined && event.stream_id !== result.stream_id) return false;
          if (event.sequence <= result.sequence || event.sequence > state.lastSequence) return false;
          if (seenSequences.has(event.sequence)) return false;
          if (!eventTargetsConversation(event, conversationId)) return false;
          seenSequences.add(event.sequence);
          return true;
        })
        .sort((left, right) => left.sequence - right.sequence);
      const draft = createBatchDraft();
      return wipedEvents.reduce(
        (current, event) => ({
          ...applyBusinessEvent(current, event, draft),
          lastSequence: state.lastSequence,
        }),
        hydrated,
      );
    });
  },
  openConversationTab(conversationId) {
    set((state) => {
      const openConversationIds = state.openConversationIds.includes(conversationId)
        ? state.openConversationIds
        : [...state.openConversationIds, conversationId];
      const activeProjectId =
        state.conversationsById[conversationId]?.project_id ?? state.activeProjectId;
      const derived = refreshWindowTask({
        ...state,
        activeConversationId: conversationId,
      });
      return { openConversationIds, activeConversationId: conversationId, activeProjectId, ...derived };
    });
  },
  closeConversationTab(conversationId) {
    set((state) => {
      const closed = closeTabOn(
        state.openConversationIds,
        state.activeConversationId,
        conversationId,
      );
      const activeProjectId = closed.active
        ? state.conversationsById[closed.active]?.project_id ?? null
        : null;
      const next = {
        ...state,
        openConversationIds: closed.ids,
        activeConversationId: closed.active,
        activeProjectId,
      };
      return { ...next, ...refreshWindowTask(next) };
    });
  },
  setConversationSyncing(conversationId, syncing) {
    set((state) => {
      if (Boolean(state.syncingConversationIds[conversationId]) === syncing) return state;
      const { [conversationId]: _done, ...rest } = state.syncingConversationIds;
      return { syncingConversationIds: syncing ? { ...rest, [conversationId]: true } : rest };
    });
  },
  applyEvents(events) {
    set((state) => {
      const draft = createBatchDraft();
      return events.reduce((current, event) => applyEvent(current, event, draft), state);
    });
  },
  setStatus(status, error = null) {
    set({ status, error });
  },
  setTheme(theme) {
    set({ theme });
  },
  setComposerTarget(target) {
    set({ composerTarget: target });
  },
  setApprovalResolving(approvalId, resolving) {
    set((state) => {
      if (resolving) {
        return {
          approvalResolvingById: {
            ...state.approvalResolvingById,
            [approvalId]: true,
          },
        };
      }
      const { [approvalId]: _resolved, ...remaining } = state.approvalResolvingById;
      return { approvalResolvingById: remaining };
    });
  },
  dismissToast(id) {
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }));
  },
  pushToast(toast) {
    set((state) => ({ toasts: pushToast(state.toasts, toast) }));
  },
  setConfigSnapshot(snapshot) {
    set({ configSnapshot: snapshot });
  },
  setMainView(mainView) {
    set({ mainView });
  },
  setCharacterLibrary(patch) {
    set((state) => ({ characterLibrary: { ...state.characterLibrary, ...patch } }));
  },
  setCharacterCreate(patch) {
    set((state) => ({ characterCreate: { ...state.characterCreate, ...patch } }));
  },
  setRemotePairing(patch) {
    set((state) => ({ remotePairing: { ...state.remotePairing, ...patch } }));
  },
  setServeAddress(payload) {
    set((state) => ({
      remotePairing: remotePairingWithServeAddress(state.remotePairing, payload),
    }));
  },
  setTunnelStatus(status) {
    set((state) => ({
      remotePairing: {
        ...state.remotePairing,
        tunnel: {
          state: status.state,
          publicUrl: status.public_url,
          hostname: status.hostname,
          error: status.error,
          requestError: null,
          loading: false,
        },
      },
    }));
  },
  setTunnelStarting() {
    set((state) => ({
      remotePairing: {
        ...state.remotePairing,
        tunnel: {
          ...state.remotePairing.tunnel,
          state: "starting",
          error: null,
          requestError: null,
          loading: true,
        },
      },
    }));
  },
  setTunnelStopping() {
    set((state) => ({
      remotePairing: {
        ...state.remotePairing,
        tunnel: { ...state.remotePairing.tunnel, requestError: null, loading: true },
      },
    }));
  },
  setTunnelFailed(error) {
    set((state) => ({
      remotePairing: {
        ...state.remotePairing,
        tunnel: { ...state.remotePairing.tunnel, state: "failed", error, loading: false },
      },
    }));
  },
  setTunnelRequestFailed(error) {
    set((state) => ({
      remotePairing: {
        ...state.remotePairing,
        tunnel: { ...state.remotePairing.tunnel, requestError: error, loading: false },
      },
    }));
  },
  setPowerStatus(payload) {
    set((state) => ({
      powerStatus: payload,
      // 成功读取（查询或事件）覆盖旧查询错误；at_risk 持续期间保留用户关闭标记。
      powerError: null,
      powerPromptDismissed: payload.at_risk ? state.powerPromptDismissed : false,
    }));
  },
  setPowerError(message) {
    set({ powerError: message });
  },
  setPowerQueryInFlight(inFlight) {
    set({ powerQueryInFlight: inFlight });
  },
  dismissPowerPrompt() {
    set({ powerPromptDismissed: true });
  },
  setMemories(memories) {
    set({ memories });
  },
  setMemoriesForConversation(conversationId, memories) {
    set((state) => ({
      memoriesByConversation: {
        ...state.memoriesByConversation,
        [conversationId]: memories,
      },
    }));
  },
  setMemoryPanel(patch) {
    set((state) => ({ memoryPanel: { ...state.memoryPanel, ...patch } }));
  },
  upsertMemory(memory, conversationId) {
    set((state) => ({
      memories: [...state.memories.filter((item) => item.memory_id !== memory.memory_id), memory],
      memoriesByConversation: {
        ...state.memoriesByConversation,
        [conversationId]: [
          ...(state.memoriesByConversation[conversationId] ?? []).filter(
            (item) => item.memory_id !== memory.memory_id,
          ),
          memory,
        ],
      },
    }));
  },
  setMetricsPage(page, mode = "replace") {
    set((state) => {
      if (mode === "replace") {
        return {
          turnMetrics: page.metrics,
          metricsCursor: page.cursor,
          metricsLoading: false,
          metricsError: null,
        };
      }
      // append 按 keyset 分页追加，旧页在前；已出现的 metric_id 跳过（含本页内部重复）。
      const seen = new Set(state.turnMetrics.map((metric) => metric.metric_id));
      const merged = [...state.turnMetrics];
      for (const metric of page.metrics) {
        if (seen.has(metric.metric_id)) continue;
        seen.add(metric.metric_id);
        merged.push(metric);
      }
      return {
        turnMetrics: merged,
        metricsCursor: page.cursor,
        metricsLoading: false,
        metricsError: null,
      };
    });
  },
  setMetricsError(message) {
    set({ metricsError: message, metricsLoading: false });
  },
  setMetricsLoading(loading) {
    set({ metricsLoading: loading });
  },
  setPromptAssembly(assembly) {
    set({ promptAssembly: assembly, promptAssemblyLoading: false, promptAssemblyError: null });
  },
  setPromptAssemblyLoading(loading) {
    set({ promptAssemblyLoading: loading });
  },
  setPromptAssemblyError(message) {
    set({ promptAssemblyError: message, promptAssemblyLoading: false });
  },
}));

export function useDesktopStore<T>(selector: (state: DesktopState) => T): T {
  return useStore(desktopStore, selector);
}

/** 本窗口当前聊天只由活动标签决定；无标签时返回 null。 */
export const selectWindowConversationId = (state: DesktopState): string | null =>
  state.activeConversationId;

/** 本窗口当前项目由活动标签所属项目决定，没有标签时取后端快照的当前项目。 */
export const selectWindowProjectId = (
  state: Pick<DesktopState, "activeProjectId" | "currentProjectId">,
): string | null =>
  state.activeProjectId ?? (state.currentProjectId || null);

/** 本窗口模式取自活动标签会话的 last_mode；没有打开的聊天时为 chat。 */
export const selectWindowMode = (
  state: Pick<DesktopState, "activeConversationId" | "conversationsById">,
): "chat" | "collaboration" =>
  state.activeConversationId &&
  state.conversationsById[state.activeConversationId]?.last_mode === "collaboration"
    ? "collaboration"
    : "chat";

/** 实际发送对象：聊天模式只能对角色说，协作模式沿用用户选择。 */
export const selectComposerTarget = (
  state: Pick<DesktopState, "activeConversationId" | "conversationsById" | "composerTarget">,
): "character" | "assistant" =>
  selectWindowMode(state) === "chat" ? "character" : state.composerTarget;

export const selectDesktopRenderState = (state: DesktopState): DesktopRenderState => ({
  status: state.status,
  error: state.error,
  resyncing: state.resyncing,
  theme: state.theme,
  composerTarget: state.composerTarget,
  projectsById: state.projectsById,
  conversationsById: state.conversationsById,
  messagesById: state.messagesById,
  messageIdsByConversation: state.messageIdsByConversation,
  toolRunsById: state.toolRunsById,
  toolIdsByConversation: state.toolIdsByConversation,
  queueItemsByConversation: state.queueItemsByConversation,
  currentAccountId: state.currentAccountId,
  currentAccount: state.currentAccount,
  accounts: state.accounts,
  currentProjectId: state.currentProjectId,
  currentConversationId: state.currentConversationId,
  pair: state.pair,
  pairs: state.pairs,
  activeTask: state.activeTask,
  activeTasksByConversation: state.activeTasksByConversation,
  busy: state.busy,
  approvals: state.approvals,
  approvalResolvingById: state.approvalResolvingById,
  reviewByConversation: state.reviewByConversation,
  voice: state.voice,
  toasts: state.toasts,
  configSnapshot: state.configSnapshot,
  openConversationIds: state.openConversationIds,
  activeConversationId: state.activeConversationId,
  activeProjectId: state.activeProjectId,
  syncingConversationIds: state.syncingConversationIds,
  mainView: state.mainView,
  characterLibrary: state.characterLibrary,
  characterCreate: state.characterCreate,
  remotePairing: state.remotePairing,
});
