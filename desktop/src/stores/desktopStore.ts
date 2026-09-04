import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";

import type {
  AccountListItem,
  AccountRecord,
  ActiveTask,
  CharacterVoiceState,
  ConversationOpenResult,
  ConversationRecord,
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PairRecord,
  PairSummary,
  PendingApproval,
  PowerStatusPayload,
  ProjectRecord,
  QueueItem,
  ToolRun,
  Turn,
  VoiceState,
} from "../contracts/protocol";
import type {
  CharacterCreateViewModel,
  CharacterLibraryViewModel,
  MainView,
  RemotePairingViewModel,
} from "../contracts/view-models";

export type DesktopStatus = "booting" | "ready" | "disconnected" | "error";

/** V0.2 M4：Toast 队列项——store 层用协议无关的最小结构，
    与 ui/status/types.ts 的 ToastItem 形状一致，由 presenters 透传。 */
export interface StoreToast {
  id: string;
  kind: "error" | "warning" | "info" | "success";
  text: string;
  hasDetails?: boolean;
}

export interface DesktopState {
  status: DesktopStatus;
  error: string | null;
  theme: "dark" | "light";
  mode: "chat" | "collaboration";
  composerTarget: "character" | "assistant";
  composerDraft: string;
  projectsById: Record<string, ProjectRecord>;
  conversationsById: Record<string, ConversationRecord>;
  messagesById: Record<string, Message>;
  messageIdsByConversation: Record<string, string[]>;
  toolRunsById: Record<string, ToolRun>;
  toolIdsByConversation: Record<string, string[]>;
  turnsById: Record<string, Turn>;
  turnIdsByConversation: Record<string, string[]>;
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
  /** V0.3.2 M5：全账号活动任务集合（按 conversation_id 索引，同聊天一次只一个活动任务）。
      busy/activeTask 由本窗口活动聊天在该集合中的条目推导。 */
  activeTasksByConversation: Record<string, ActiveTask>;
  busy: boolean;
  approvals: PendingApproval[];
  /** V0.3.5：已决审批记录（含 resolved_by/decision），供 UI 表达双端仲裁结果。 */
  resolvedApprovals: Array<{
    approval_id: string;
    conversation_id?: string;
    decision: string;
    resolved_by: string;
    task_id?: string;
  }>;
  approvalResolvingById: Record<string, boolean>;
  reviewActive: boolean;
  reviewText: string | null;
  voice: VoiceState;
  /** V0.2 M4：Toast 队列（recoverable/info 错误入列，同 code+message 去重，最多 5 条）。 */
  toasts: StoreToast[];
  /** V0.2 M4：config.get 结果缓存（SettingsCenter 四个页的数据源）。 */
  configSnapshot: Record<string, unknown> | null;
  lastSequence: number;
  needsBootstrap: boolean;
  /** M2.1：当前连接代次。业务事件和快照必须属于该代次才允许投影。 */
  streamId: string | null;
  /** M2.1：bootstrap/缺口期间暂存的同一代次业务事件，快照水合后核对重放。 */
  eventBuffer: DesktopEvent[];
  /** V0.3.2 M5：本窗口视图 id——多窗口请求 id 与 conversation.open 的 view_id。 */
  viewId: string;
  /** V0.3.2 M5：本窗口打开的聊天标签（顺序即标签顺序）。 */
  openConversationIds: string[];
  /** V0.3.2 M5：本窗口当前活动标签；全部关闭后为 null（工作区显示空状态）。 */
  activeConversationId: string | null;
  /** V0.3.2 M5：本窗口当前标签所属项目；不随 Sidecar 全局导航指针变化。 */
  activeProjectId: string | null;

  /* —— V0.3.3 角色卡与远程配对 slice（形状见 contracts/view-models.ts）—— */
  /** 主工作区视图：聊天 / 角色库 / 角色创作。 */
  mainView: MainView;
  characterLibrary: CharacterLibraryViewModel;
  characterCreate: CharacterCreateViewModel;
  remotePairing: RemotePairingViewModel;

  /* —— V0.3.7 电源状态 slice（契约冻结 §1.5/§2.1）—— */
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
  hydrate(snapshot: DesktopSnapshot): void;
  applyEvents(events: DesktopEvent[]): void;
  /** V0.3.2 M5：装载 conversation.open 的只读结果并打开对应标签（不改全局当前聊天）。 */
  hydrateConversationView(result: ConversationOpenResult, bufferedEvents?: DesktopEvent[]): void;
  setViewId(viewId: string): void;
  /** V0.3.2 M5：打开（或聚焦）本窗口标签；已开则聚焦，未开则追加并聚焦。 */
  openConversationTab(conversationId: string): void;
  /** V0.3.2 M5：只移除本窗口标签；关闭活动标签后选右侧相邻、无右侧选左侧，
      最后一个标签关闭后 activeConversationId 为 null。绝不触发后端关闭/取消。 */
  closeConversationTab(conversationId: string): void;
  /** V0.3.2 M5：聚焦本窗口已打开的标签。 */
  setActiveConversation(conversationId: string): void;
  setStatus(status: DesktopStatus, error?: string | null): void;
  setTheme(theme: "dark" | "light"): void;
  setMode(mode: "chat" | "collaboration"): void;
  setComposerTarget(target: "character" | "assistant"): void;
  setComposerDraft(draft: string): void;
  setApprovalResolving(approvalId: string, resolving: boolean): void;
  setReviewStatus(active: boolean, text?: string | null): void;
  dismissToast(id: string): void;
  pushToast(toast: StoreToast): void;
  setConfigSnapshot(snapshot: Record<string, unknown> | null): void;
}

export type DesktopRenderState = Pick<
  DesktopState,
  | "status"
  | "error"
  | "theme"
  | "mode"
  | "composerTarget"
  | "composerDraft"
  | "projectsById"
  | "conversationsById"
  | "messagesById"
  | "messageIdsByConversation"
  | "toolRunsById"
  | "toolIdsByConversation"
  | "turnsById"
  | "turnIdsByConversation"
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
  | "resolvedApprovals"
  | "approvalResolvingById"
  | "reviewActive"
  | "reviewText"
  | "voice"
  | "toasts"
  | "configSnapshot"
  | "viewId"
  | "openConversationIds"
  | "activeConversationId"
  | "activeProjectId"
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

/** V0.3.2 M5：启动 URL 中的窗口参数（独立聊天窗口由 Rust 带 query 创建）。 */
function readUrlParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get(name);
  return value && value.length > 0 ? value : null;
}

function randomViewId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // 非安全上下文（旧测试环境）下的降级生成器；只要求进程内唯一。
  return `view-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 聊天窗口启动时携带的会话 id；有值时首次水合不播种标签，等 conversation.open 打开。 */
const initialUrlConversationId = readUrlParam("conversation_id");

function createInitialState(): Omit<
  DesktopState,
  | "hydrate"
  | "hydrateConversationView"
  | "applyEvents"
  | "setViewId"
  | "openConversationTab"
  | "closeConversationTab"
  | "setActiveConversation"
  | "setStatus"
  | "setTheme"
  | "setMode"
  | "setComposerTarget"
  | "setComposerDraft"
  | "setApprovalResolving"
  | "setReviewStatus"
  | "dismissToast"
  | "pushToast"
  | "setConfigSnapshot"
  | "setMainView"
  | "setCharacterLibrary"
  | "setCharacterCreate"
  | "setRemotePairing"
  | "setPowerStatus"
  | "setPowerError"
  | "setPowerQueryInFlight"
  | "dismissPowerPrompt"
> {
  return {
    status: "booting",
    error: null,
    theme: readThemePreference(),
    mode: "chat",
    composerTarget: "character",
    composerDraft: "",
    projectsById: {},
    conversationsById: {},
    messagesById: {},
    messageIdsByConversation: {},
    toolRunsById: {},
    toolIdsByConversation: {},
    turnsById: {},
    turnIdsByConversation: {},
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
    resolvedApprovals: [],
    approvalResolvingById: {},
    reviewActive: false,
    reviewText: null,
    voice: emptyVoice,
    toasts: [],
    configSnapshot: null,
    lastSequence: -1,
    needsBootstrap: false,
    streamId: null,
    eventBuffer: [],
    viewId: readUrlParam("view_id") ?? randomViewId(),
    openConversationIds: [],
    activeConversationId: null,
    activeProjectId: null,
    mainView: "chat",
    characterLibrary: { cards: [], loading: false, error: null, loaded: false },
    characterCreate: { cardId: null, card: null, readOnly: false, loading: false, error: null },
    remotePairing: {
      code: null,
      ttlSeconds: 300,
      issuedAtEpochMs: null,
      devices: [],
      loading: false,
      error: null,
      serveAddress: null,
    },
    powerStatus: null,
    powerError: null,
    powerQueryInFlight: false,
    powerPromptDismissed: false,
  };
}

function readThemePreference(): "dark" | "light" {
  if (typeof window === "undefined") return "dark";
  return window.localStorage.getItem("pair-harness-theme") === "light" ? "light" : "dark";
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
  const turnsById: Record<string, Turn> = {};
  const turnIdsByConversation: Record<string, string[]> = {};
  for (const turn of snapshot.turns ?? []) {
    turnsById[turn.turn_id] = turn;
    (turnIdsByConversation[turn.conversation_id] ??= []).push(turn.turn_id);
  }
  const queueItemsByConversation: Record<string, QueueItem[]> = {};
  for (const item of snapshot.queue_items ?? []) {
    (queueItemsByConversation[item.conversation_id] ??= []).push(item);
  }
  return {
    projectsById,
    conversationsById,
    messagesById,
    messageIdsByConversation,
    toolRunsById,
    toolIdsByConversation,
    turnsById,
    turnIdsByConversation,
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

function upsertIndexed<T>(
  byId: Record<string, T>,
  idsByConversation: Record<string, string[]>,
  conversationId: string,
  id: string,
  item: T,
): { byId: Record<string, T>; idsByConversation: Record<string, string[]> } {
  const ids = idsByConversation[conversationId] ?? [];
  return {
    byId: { ...byId, [id]: item },
    idsByConversation: ids.includes(id)
      ? idsByConversation
      : { ...idsByConversation, [conversationId]: [...ids, id] },
  };
}

/** M4.1：工具记录以 conversation_id + tool_call_id 复合键索引，
    两个会话复用同一 tool_call_id 时互不覆盖。 */
function toolRunKey(toolRun: ToolRun): string {
  return `${toolRun.conversation_id}\u0000${toolRun.tool_call_id}`;
}

/** V0.3.2 M5：从快照建立活动任务集合——active_tasks（新协议全量集合）优先，
    旧协议只有单值 active_task 时回退为单条目集合。 */
function activeTasksFromSnapshot(snapshot: DesktopSnapshot): Record<string, ActiveTask> {
  const map: Record<string, ActiveTask> = {};
  if (Array.isArray(snapshot.active_tasks)) {
    for (const task of snapshot.active_tasks) {
      map[task.conversation_id] = task;
    }
    return map;
  }
  if (snapshot.active_task) {
    map[snapshot.active_task.conversation_id] = snapshot.active_task;
  }
  return map;
}

/** V0.3.2 M5：窗口 busy/activeTask 派生——本窗口活动聊天（无标签时回退全局当前聊天）
    在 activeTasksByConversation 中有任务才算忙；activeTask 只保留本窗口聊天的任务。 */
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

/** V0.3.2 M5：移除标签后的相邻选择——先右侧相邻，无右侧取左侧，全空为 null。 */
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

/** V0.3.2 M5：按当前已知会话修剪标签——会话消失或已归档的标签移除，
    活动标签被修剪时沿用相邻选择规则。 */
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
  // V0.2 M4：同 code+message 去重（以 id 为准），最多保留 5 条
  if (toasts.some((item) => item.id === toast.id)) return toasts;
  return [...toasts, toast].slice(-5);
}

function snapshotMode(snapshot: DesktopSnapshot): "chat" | "collaboration" {
  return snapshot.current_conversation.last_mode === "collaboration" ? "collaboration" : "chat";
}

function normalizeStreamId(value: unknown): string | undefined {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return undefined;
}

function hydrateSnapshotState(state: DesktopState, snapshot: DesktopSnapshot): DesktopState {
  // M2.1：旧代次快照不能覆盖新代次状态。state.streamId 为空时是首次水合，
  // 允许任意快照建立代次。直接 hydrate（测试/mock 等无 stream_id 的旧协议）
  // 会清空代次，事件路径另行拒绝无 stream_id 的快照。
  const snapshotStreamId = normalizeStreamId(snapshot.stream_id);
  if (
    state.streamId !== null &&
    snapshotStreamId !== undefined &&
    snapshotStreamId !== state.streamId
  ) {
    return state;
  }
  let indexed = indexSnapshot(snapshot);
  const sameAccount =
    state.currentAccountId === "" || state.currentAccountId === snapshot.current_account_id;
  if (sameAccount) {
    // Sidecar 快照只携带全局当前聊天的消息详情。保留本窗口其他
    // 已打开标签的缓存，只替换快照明确覆盖的聊天。
    const replacedConversationIds = Array.from(
      new Set(
        [
          snapshot.current_conversation_id,
          ...Object.keys(indexed.messageIdsByConversation),
          ...Object.keys(indexed.toolIdsByConversation),
          ...Object.keys(indexed.turnIdsByConversation),
          ...Object.keys(indexed.queueItemsByConversation),
        ].filter(Boolean),
      ),
    );
    const messages = mergeIndexedConversationCache(
      state.messagesById,
      state.messageIdsByConversation,
      indexed.messagesById,
      indexed.messageIdsByConversation,
      replacedConversationIds,
    );
    const tools = mergeIndexedConversationCache(
      state.toolRunsById,
      state.toolIdsByConversation,
      indexed.toolRunsById,
      indexed.toolIdsByConversation,
      replacedConversationIds,
    );
    const turns = mergeIndexedConversationCache(
      state.turnsById,
      state.turnIdsByConversation,
      indexed.turnsById,
      indexed.turnIdsByConversation,
      replacedConversationIds,
    );
    const queueItemsByConversation = { ...state.queueItemsByConversation };
    for (const conversationId of replacedConversationIds) {
      queueItemsByConversation[conversationId] =
        indexed.queueItemsByConversation[conversationId] ?? [];
    }
    indexed = {
      ...indexed,
      messagesById: messages.byId,
      messageIdsByConversation: messages.idsByConversation,
      toolRunsById: tools.byId,
      toolIdsByConversation: tools.idsByConversation,
      turnsById: turns.byId,
      turnIdsByConversation: turns.idsByConversation,
      queueItemsByConversation,
    };
  }
  // V0.3.2 M5：快照重建全账号会话目录后修剪标签（已归档/消失的会话关闭标签）。
  const pruned = pruneOpenTabs({
    openConversationIds: state.openConversationIds,
    activeConversationId: state.activeConversationId,
    conversationsById: indexed.conversationsById,
  });
  // 播种初始标签：本窗口没有打开任何标签且非聊天窗口（URL 带 conversation_id
  // 时等 conversation.open）时，跟随全局当前聊天打开一个标签。这保证主窗口
  // bootstrap/重连后工作区始终有内容；用户主动关闭全部标签后的下一次水合会
  // 重新播种一个标签（V0.3.2 已知取舍，见计划 5.9.5 的后续按标签恢复）。
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
  // V0.3.2 M5：模式和项目上下文跟随本窗口活动标签，而不是跟随
  // Sidecar 可能被另一个窗口改写的 current_conversation_id。
  const selectedConversation = activeConversationId
    ? indexed.conversationsById[activeConversationId]
    : undefined;
  const mode = selectedConversation
    ? selectedConversation.last_mode === "collaboration"
      ? "collaboration"
      : "chat"
    : state.mode;
  const pairs = snapshot.pairs ?? (snapshot.pair ? [snapshot.pair] : []);
  const selectedPair = selectedConversation
    ? pairs.find((item) => item.pair_id === selectedConversation.pair_id) ??
      state.pairs.find((item) => item.pair_id === selectedConversation.pair_id) ??
      snapshot.pair
    : snapshot.pair;
  const hydrated: DesktopState = {
    ...state,
    ...indexed,
    status: "ready",
    error: null,
    currentAccountId: snapshot.current_account_id,
    accountGeneration:
      state.currentAccountId !== "" && state.currentAccountId !== snapshot.current_account_id
        ? state.accountGeneration + 1
        : state.accountGeneration,
    currentAccount: snapshot.current_account ?? null,
    accounts: snapshot.accounts ?? [],
    currentProjectId: snapshot.current_project_id,
    currentConversationId: snapshot.current_conversation_id,
    pair: selectedPair,
    pairs,
    // V0.3.2 M5：活动任务集合按快照全量替换；busy/activeTask 由本窗口活动聊天推导。
    activeTasksByConversation: activeTasksFromSnapshot(snapshot),
    approvals: snapshot.approvals,
    approvalResolvingById: {},
    reviewActive: false,
    reviewText: null,
    voice: snapshot.voice,
    // V0.2 M4：快照水合保留仍有效的本地 Toast；configSnapshot 只在新快照显式
    // 携带 config 字段时覆盖，否则继续使用 config.get 的结果。
    toasts: state.toasts,
    configSnapshot:
      "config" in snapshot
        ? (snapshot as DesktopSnapshot & { config?: Record<string, unknown> }).config ?? null
        : state.configSnapshot,
    mode,
    // M4.4：任何路径进入 chat 模式（含切换会话水合）都重置发送对象为角色。
    composerTarget: mode === "chat" ? "character" : state.composerTarget,
    lastSequence: snapshot.sequence,
    needsBootstrap: false,
    streamId: snapshotStreamId ?? null,
    eventBuffer: [],
    openConversationIds,
    activeConversationId,
    activeProjectId:
      selectedConversation?.project_id ??
      (activeConversationId ? state.activeProjectId : null),
  };
  return { ...hydrated, ...refreshWindowTask(hydrated) };
}

function applyErrorReported(state: DesktopState, event: DesktopEvent): DesktopState {
  // V0.2 错误分级（问题 9）：fatal 接管整屏；recoverable/info 保留已加载
  // 内容，入 Toast 队列（同 code+message 去重，最多 5 条）。
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
  return {
    ...state,
    error: text,
    toasts: pushToast(state.toasts, {
      id: `${payload.code ?? "error"}:${text}`,
      kind: severity === "info" ? "info" : "warning",
      text,
      hasDetails: Boolean(payload.code),
    }),
  };
}

function applyConnectionStatus(state: DesktopState, event: DesktopEvent): DesktopState {
  const streamId = normalizeStreamId(event.stream_id);
  const status = String(event.payload.status ?? "");
  // connected 总是权威：新代次到达时用它切换 streamId。
  // disconnected 只接受当前代次；旧 reader 迟到的 disconnected 不能覆盖新连接。
  if (status === "connected") {
    return {
      ...state,
      streamId: streamId ?? state.streamId,
      status: "booting",
      needsBootstrap: true,
      eventBuffer: [],
    };
  }
  if (status === "disconnected") {
    if (
      state.streamId !== null &&
      streamId !== undefined &&
      streamId !== state.streamId
    ) {
      return state; // 旧代次的 disconnected
    }
    return { ...state, status: "disconnected", needsBootstrap: false, eventBuffer: [] };
  }
  return state;
}

function replayBufferedEvents(state: DesktopState): DesktopState {
  const buffered = state.eventBuffer;
  if (buffered.length === 0) return state;
  let current: DesktopState = { ...state, eventBuffer: [] };
  for (const event of buffered) {
    current = applyEvent(current, event);
  }
  return current;
}

function applyEvent(state: DesktopState, event: DesktopEvent): DesktopState {
  // M2.1：连接控制事件在业务序号过滤前处理，并携带对应 stream_id。
  if (event.event === "connection.status") {
    return applyConnectionStatus(state, event);
  }
  // 协议错误、旧插件事件等没有序号的消息不能参与快照序列校验。
  if (!Number.isFinite(event.sequence)) return state;
  // 旧代次事件直接丢弃，不参与当前业务投影。
  const eventStreamId = normalizeStreamId(event.stream_id);
  if (eventStreamId !== undefined && state.streamId !== null && eventStreamId !== state.streamId) {
    return state;
  }
  // 快照水合：旧代次快照被 hydrateSnapshotState 拒绝；水合后重放暂存事件。
  if (event.event === "state.snapshot") {
    const snapshot = event.payload as unknown as DesktopSnapshot;
    const snapshotStreamId = normalizeStreamId(snapshot.stream_id);
    // 事件路径下，当前已有代次时快照必须携带同一 stream_id；无 stream_id
    // 的旧协议快照不能覆盖新代次状态。
    if (
      state.streamId !== null &&
      (snapshotStreamId === undefined || snapshotStreamId !== state.streamId)
    ) {
      return state;
    }
    // 水合会清空 eventBuffer；先把待核对事件保留下来，水合后按快照序号重放。
    const buffered = state.eventBuffer;
    const hydrated = { ...hydrateSnapshotState(state, snapshot), eventBuffer: buffered };
    return replayBufferedEvents(hydrated);
  }
  // error.reported 是控制/错误通道：即使正在 bootstrap 也不能被暂存，
  // 否则致命启动错误在没有快照时会永远无法显示。
  if (event.event === "error.reported") {
    // 错误通道不参与业务序号过滤：bootstrap 期间/旧代次高序号之后都必须显示。
    return applyErrorReported(state, event);
  }
  // 新代次 bootstrap 或序号缺口期间：暂存业务事件，等快照水合后核对重放。
  if (state.needsBootstrap || state.status === "booting") {
    return { ...state, eventBuffer: [...state.eventBuffer, event] };
  }
  if (event.sequence <= state.lastSequence) {
    return state; // 同代次重复序号直接丢弃
  }
  if (state.lastSequence >= 0 && event.sequence !== state.lastSequence + 1) {
    // 序号缺口：触发 bootstrap，并保留缺口后的事件等待快照核对。
    return {
      ...state,
      needsBootstrap: true,
      eventBuffer: [...state.eventBuffer, event],
    };
  }

  return applyBusinessEvent(state, event);
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

function applyBusinessEvent(state: DesktopState, event: DesktopEvent): DesktopState {
  const next: DesktopState = { ...state, lastSequence: event.sequence };
  switch (event.event) {
    case "backend.ready":
      // M5.4：backend.ready 是新的 stream bootstrap 起点；等 state.snapshot
      // 水合前先暂存业务事件，AppController 看到 needsBootstrap 会重新拉快照。
      next.status = "booting";
      next.needsBootstrap = true;
      next.eventBuffer = [];
      break;
    case "state.snapshot":
      return hydrateSnapshotState(next, event.payload as unknown as DesktopSnapshot);
    case "message.created": {
      const message = event.payload.message as Message;
      const indexed = upsertIndexed(
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
      // V0.2 消息生命周期推进：按真实 id 对账（失败保留文字，可重试）。
      // M5.4：完整 Message 执行 upsert（即使 status_changed 先于 message.created
      // 到达也能落库）；缺少必要字段时触发 bootstrap，不能静默丢弃。
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
          eventBuffer: [...next.eventBuffer, event],
        };
      }
      const indexed = upsertIndexed(
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
      const payload = event.payload as unknown as {
        message_id: string;
        conversation_id: string;
        pair_id?: string;
        source: Message["source"];
        kind: Message["kind"];
        delta?: string;
        channel?: string;
        started?: boolean;
        completed?: boolean;
        reasoning_streaming?: boolean;
        task_id?: string | null;
        segment_index?: number | null;
        timeline_order?: number | null;
      };
      const current = next.messagesById[payload.message_id];
      const delta = String(payload.delta ?? "");
      const reasoningDelta =
        (payload.source === "character" && payload.channel === "reasoning") ||
        (payload.source === "assistant" && payload.kind === "assistant.reasoning");
      const messagePayload: Record<string, unknown> = { ...(current?.payload ?? {}) };
      let text = current?.text ?? "";
      if (payload.reasoning_streaming !== undefined) {
        messagePayload.reasoning_streaming = payload.reasoning_streaming;
      }
      if (payload.timeline_order !== undefined && payload.timeline_order !== null) {
        messagePayload.timeline_order = payload.timeline_order;
      }
      if (reasoningDelta) {
        const reasoning = typeof messagePayload.reasoning === "string" ? messagePayload.reasoning : "";
        messagePayload.reasoning = reasoning + delta;
        if (payload.reasoning_streaming === undefined && (payload.started || payload.completed !== undefined)) {
          messagePayload.reasoning_streaming = !payload.completed;
        }
      } else {
        text += delta;
      }
      const message: Message = current
        ? { ...current, text, payload: messagePayload, streaming: true }
        : {
            message_id: payload.message_id,
            conversation_id: payload.conversation_id,
            pair_id:
              payload.pair_id ??
              next.conversationsById[payload.conversation_id]?.pair_id ??
              next.pair?.pair_id ??
              "",
            engine_turn_id: null,
            source: payload.source,
            kind: payload.kind,
            text,
            payload: messagePayload,
            tts_eligible: payload.source === "character" || payload.source === "assistant",
            created_at: new Date().toISOString(),
            streaming: true,
            task_id: payload.task_id ?? null,
            timeline_order: payload.timeline_order ?? null,
          };
      next.messagesById = { ...next.messagesById, [message.message_id]: message };
      const ids = next.messageIdsByConversation[payload.conversation_id] ?? [];
      if (!ids.includes(payload.message_id)) {
        next.messageIdsByConversation = {
          ...next.messageIdsByConversation,
          [payload.conversation_id]: [...ids, payload.message_id],
        };
      }
      break;
    }
    case "message.finalized": {
      const messageId = String(event.payload.message_id ?? "");
      const current = next.messagesById[messageId];
      if (current) next.messagesById = { ...next.messagesById, [messageId]: { ...current, streaming: false } };
      break;
    }
    case "tool_run.upserted": {
      const toolRun = event.payload.tool_run as ToolRun;
      const key = toolRunKey(toolRun);
      const indexed = upsertIndexed(
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
      const payload = event.payload as {
        approval_id?: string;
        conversation_id?: string;
        decision?: string;
        resolved_by?: string;
        task_id?: string;
      };
      const approvalId = String(payload.approval_id ?? "");
      next.approvals = next.approvals.filter((item) => item.approval_id !== approvalId);
      next.resolvedApprovals = [
        ...next.resolvedApprovals.filter((item) => item.approval_id !== approvalId),
        {
          approval_id: approvalId,
          conversation_id: payload.conversation_id,
          // 真实协议 approval.resolved 总带合法 decision；缺失不伪造方向。
          decision: payload.decision ?? "",
          resolved_by: payload.resolved_by ?? "desktop",
          task_id: payload.task_id,
        },
      ];
      const { [approvalId]: _resolved, ...remaining } = next.approvalResolvingById;
      next.approvalResolvingById = remaining;
      break;
    }
    case "task.busy_changed": {
      // V0.3.2 M5：active_tasks 是事件发生后的完整权威集合，整体替换，
      // 避免增删事件丢失后形成幽灵忙碌状态；旧协议只带单值 active_task 时
      // 回退为单条目集合。
      const payload = event.payload as {
        busy?: boolean;
        active_task?: DesktopSnapshot["active_task"];
        active_tasks?: DesktopSnapshot["active_tasks"];
      };
      const map: Record<string, ActiveTask> = { ...next.activeTasksByConversation };
      if (Array.isArray(payload.active_tasks)) {
        // 新协议：事件携带事件发生后的完整权威集合，直接替换。
        for (const conversationId of Object.keys(map)) delete map[conversationId];
        for (const task of payload.active_tasks) {
          map[task.conversation_id] = task;
        }
      } else if (payload.active_task) {
        // 旧协议兼容：只更新它明确携带的任务，不抹掉其他聊天的活动状态。
        map[payload.active_task.conversation_id] = payload.active_task;
      } else if (payload.busy === false) {
        const conversationId = String(event.payload.conversation_id ?? "");
        if (conversationId) delete map[conversationId];
        else {
          // 没有归属字段的旧全局事件只能按旧语义清空全部活动任务。
          for (const id of Object.keys(map)) delete map[id];
        }
      }
      next.activeTasksByConversation = map;
      Object.assign(next, refreshWindowTask(next));
      break;
    }
    case "turn.started":
    case "turn.status_changed": {
      // V0.2 M2：Turn 生命周期推进（started → running → completed/failed/cancelled）。
      // 快照水合后同 turn 的事件按状态覆盖。
      const turn = event.payload.turn as Turn;
      if (!turn) break;
      const indexed = upsertIndexed(
        next.turnsById,
        next.turnIdsByConversation,
        turn.conversation_id,
        turn.turn_id,
        turn,
      );
      next.turnsById = indexed.byId;
      next.turnIdsByConversation = indexed.idsByConversation;
      // 回合失败/取消：清掉该会话内所有 streaming 占位，避免气泡永久停在
      // “三个点”（后端只在回合成功时用最终消息覆盖临时流）。
      if (
        event.event === "turn.status_changed" &&
        (turn.status === "failed" || turn.status === "cancelled")
      ) {
        const messageIds = next.messageIdsByConversation[turn.conversation_id] ?? [];
        let changed = false;
        const messages = { ...next.messagesById };
        for (const messageId of messageIds) {
          const message = messages[messageId];
          if (message?.streaming) {
            messages[messageId] = { ...message, streaming: false };
            changed = true;
          }
        }
        if (changed) next.messagesById = messages;
      }
      break;
    }
    case "queue.changed": {
      // V0.2 M2：队列变化推全量有序列表（按 position 升序），直接替换
      const payload = event.payload as { conversation_id?: string; items?: QueueItem[] };
      const conversationId = payload.conversation_id ?? next.currentConversationId;
      if (conversationId) {
        next.queueItemsByConversation = {
          ...next.queueItemsByConversation,
          [conversationId]: payload.items ?? [],
        };
      }
      break;
    }
    case "review.started":
      // V0.2 问题 14：只有审查智能体真正被调用时才显示审查状态
      next.reviewActive = true;
      next.reviewText = null;
      break;
    case "review.completed": {
      const payload = event.payload as { allow?: boolean; reason?: string };
      next.reviewActive = false;
      if (payload.allow === false) {
        next.reviewText = `审查否决：${payload.reason ?? ""}`;
      } else if (payload.allow === true) {
        next.reviewText = "审查通过";
      } else {
        next.reviewText = null;
      }
      break;
    }
    case "review.failed":
      next.reviewActive = false;
      next.reviewText = "审查失败：已按安全默认否决";
      break;
    case "project.changed": {
      const project = event.payload.project as ProjectRecord;
      // 设置类命令（审批模式/推理档位）的 project.changed 只携带项目字段，
      // 不含 conversations；与现有记录合并，避免渲染层对 undefined 调用 map 白屏。
      const existing = next.projectsById[project.project_id];
      const merged = existing ? { ...existing, ...project } : project;
      next.projectsById = {
        ...next.projectsById,
        [project.project_id]: merged,
      };
      // V0.3.2 M5：项目归档或其会话被移除/归档时，本窗口相关标签同步清理。
      const knownConversationIds = new Set(
        (merged.conversations ?? []).map((item) => item.conversation_id),
      );
      if (merged.archived || Array.isArray(project.conversations)) {
        for (const id of next.openConversationIds) {
          const conversation = next.conversationsById[id];
          const belongsToProject =
            conversation?.project_id === merged.project_id || knownConversationIds.has(id);
          const shouldClose =
            belongsToProject &&
            (merged.archived ||
              conversation?.archived === true ||
              (Array.isArray(project.conversations) && !knownConversationIds.has(id)));
          if (shouldClose) {
            const closed = closeTabOn(next.openConversationIds, next.activeConversationId, id);
            next.openConversationIds = closed.ids;
            next.activeConversationId = closed.active;
          }
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
      if (conversation) {
        next.conversationsById = {
          ...next.conversationsById,
          [conversation.conversation_id]: conversation,
        };
        // 侧栏标题渲染自 projectsById[].conversations（标题自动生成只广播
        // conversation.changed），同步更新项目内的会话条目，否则新标题不显示。
        const projectId = conversation.project_id ?? "";
        const project = projectId ? next.projectsById[projectId] : undefined;
        if (project && Array.isArray(project.conversations)) {
          const replaced = project.conversations.map((item) =>
            item.conversation_id === conversation.conversation_id ? conversation : item,
          );
          const exists = replaced.some((item) => item.conversation_id === conversation.conversation_id);
          const conversations = exists ? replaced : [...replaced, conversation];
          next.projectsById = { ...next.projectsById, [projectId]: { ...project, conversations } };
        }
        // V0.3.2 M5：会话被归档时关闭本窗口对应标签（只关视图，不取消任务）。
        if (conversation.archived) {
          const closed = closeTabOn(
            next.openConversationIds,
            next.activeConversationId,
            conversation.conversation_id,
          );
          next.openConversationIds = closed.ids;
          next.activeConversationId = closed.active;
          next.activeProjectId = next.activeConversationId
            ? next.conversationsById[next.activeConversationId]?.project_id ?? null
            : null;
          Object.assign(next, refreshWindowTask(next));
        }
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
      // V0.3.5：卡音色状态变化同步到角色库与创作页（若正在编辑同一张卡）。
      const payload = event.payload as {
        card_id?: string;
        state?: CharacterVoiceState;
        voice_id?: string | null;
        error?: string | null;
      };
      const cardId = String(payload.card_id ?? "");
      const voiceState = payload.state ?? next.characterLibrary.cards.find((c) => c.cardId === cardId)?.voiceState ?? "voice_unconfigured";
      if (cardId) {
        next.characterLibrary = {
          ...next.characterLibrary,
          cards: next.characterLibrary.cards.map((card) =>
            card.cardId === cardId ? { ...card, voiceState } : card,
          ),
        };
        if (next.characterCreate.cardId === cardId) {
          next.characterCreate = {
            ...next.characterCreate,
            card: {
              ...next.characterCreate.card,
              voice_state: voiceState,
              voice_id: payload.voice_id ?? undefined,
            },
          };
        }
      }
      break;
    }
    case "voice.provision_changed": {
      // V0.3.2 M6：逐项进度直接投影到 configSnapshot.voice.speakers；
      // 设置页无需猜测请求是否成功，命令结束后仍会再取一次 config.get。
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
    case "connection.status": {
      // V0.2 M2-5 连接恢复（问题 12）：断线保留已加载内容（不整屏接管），
      // 恢复后进入 booting 并请求重新 bootstrap 水合最新快照。
      const status = String(event.payload.status ?? "");
      if (status === "disconnected") {
        next.status = "disconnected";
        next.needsBootstrap = false; // 断线中不发起 bootstrap，等 connected 后恢复
      } else if (status === "connected") {
        next.status = "booting";
        next.needsBootstrap = true; // AppController 会随后重新 loadBootstrap
      }
      break;
    }
    case "error.reported":
      return applyErrorReported(next, event);
    case "serve.started": {
      // V0.3.4 缺陷 6：Sidecar --serve 上报真实监听地址，二维码按它生成。
      const payload = event.payload as { host?: unknown; port?: unknown };
      if (typeof payload.host === "string" && typeof payload.port === "number") {
        next.remotePairing = {
          ...next.remotePairing,
          serveAddress: { host: payload.host, port: payload.port },
        };
      }
      break;
    }
    case "power.status_changed": {
      // V0.3.7 §2.1：payload 与 power.get_status result 完全同形；事件即权威读取，
      // 覆盖旧状态与旧查询错误。at_risk 消失时复位「本次持续期内不再提示」，
      // 状态再次出现时允许重新提示。
      const payload = event.payload as unknown as PowerStatusPayload | null;
      if (!payload || typeof payload !== "object") break;
      next.powerStatus = payload;
      next.powerError = null;
      if (!payload.at_risk) next.powerPromptDismissed = false;
      break;
    }
    case "account.changed": {
      // V0.2 M4：账号变更事件水合当前账号与账号列表（登录/注册/切换）
      const payload = event.payload as { account?: AccountRecord; accounts?: AccountListItem[] };
      if (payload.account) {
        // V0.3.2 M5：账号切换（account_id 变化）清空本窗口全部标签；
        // 同账号的资料更新不影响标签。
        if (
          next.currentAccountId !== "" &&
          payload.account.account_id !== next.currentAccountId
        ) {
          next.openConversationIds = [];
          next.activeConversationId = null;
          next.activeProjectId = null;
          next.projectsById = {};
          next.conversationsById = {};
          next.messagesById = {};
          next.messageIdsByConversation = {};
          next.toolRunsById = {};
          next.toolIdsByConversation = {};
          next.turnsById = {};
          next.turnIdsByConversation = {};
          next.queueItemsByConversation = {};
          next.currentProjectId = "";
          next.currentConversationId = "";
          next.pair = null;
          next.pairs = [];
          next.activeTask = null;
          next.activeTasksByConversation = {};
          next.busy = false;
          next.approvals = [];
          next.resolvedApprovals = [];
          next.approvalResolvingById = {};
          next.voice = { ...emptyVoice };
          next.composerDraft = "";
          next.reviewActive = false;
          next.reviewText = null;
          next.mainView = "chat";
          next.characterLibrary = { cards: [], loading: false, error: null, loaded: false };
          next.characterCreate = {
            cardId: null,
            card: null,
            readOnly: false,
            loading: false,
            error: null,
          };
          next.remotePairing = {
            code: null,
            ttlSeconds: 300,
            issuedAtEpochMs: null,
            devices: [],
            loading: false,
            error: null,
            serveAddress: null,
          };
          // 设置页重新打开后从新账号 config.get 和 remote.list_devices 水合。
          next.configSnapshot = null;
        }
        if (payload.account.account_id !== next.currentAccountId) {
          next.accountGeneration += 1;
        }
        next.currentAccountId = payload.account.account_id;
        next.currentAccount = payload.account;
      }
      if (payload.accounts) next.accounts = payload.accounts;
      break;
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
      return replayBufferedEvents({ ...hydrated, eventBuffer: state.eventBuffer });
    });
  },
  hydrateConversationView(result, bufferedEvents = []) {
    set((state) => {
      const resultStream = result.stream_id == null ? null : String(result.stream_id);
      if (
        state.streamId !== null &&
        (resultStream === null || resultStream !== state.streamId)
      ) return state;
      const conversation = result.conversation;
      const conversationId = conversation.conversation_id;
      // 会话目录：只读装载不改变全局当前聊天，仅合并该会话与其项目条目。
      const conversationsById = {
        ...state.conversationsById,
        [conversationId]: conversation,
      };
      const projectId = conversation.project_id ?? result.project?.project_id ?? "";
      let projectsById = state.projectsById;
      if (projectId) {
        const existing = projectsById[projectId];
        const baseConversations =
          existing?.conversations ?? result.project?.conversations ?? [];
        const conversations = baseConversations.some(
          (item) => item.conversation_id === conversationId,
        )
          ? baseConversations.map((item) =>
              item.conversation_id === conversationId ? conversation : item,
            )
          : [...baseConversations, conversation];
        const projectRecord = {
          ...(result.project as ProjectRecord),
          conversations,
        };
        projectsById = { ...projectsById, [projectId]: projectRecord };
      }
      // 消息/工具/Turn/队列按会话整体替换为本次装载结果（全量装载语义），
      // 其他会话的缓存不受影响。
      const messagesById = { ...state.messagesById };
      for (const item of result.messages ?? []) {
        messagesById[item.message_id] = item;
      }
      const messageIdsByConversation = {
        ...state.messageIdsByConversation,
        [conversationId]: (result.messages ?? []).map((item) => item.message_id),
      };
      const toolRunsById = { ...state.toolRunsById };
      const toolKeys: string[] = [];
      for (const run of result.tool_runs ?? []) {
        const key = toolRunKey(run);
        toolRunsById[key] = run;
        toolKeys.push(key);
      }
      const toolIdsByConversation = {
        ...state.toolIdsByConversation,
        [conversationId]: toolKeys,
      };
      const turnsById = { ...state.turnsById };
      for (const turn of result.turns ?? []) {
        turnsById[turn.turn_id] = turn;
      }
      const turnIdsByConversation = {
        ...state.turnIdsByConversation,
        [conversationId]: (result.turns ?? []).map((item) => item.turn_id),
      };
      const queueItemsByConversation = {
        ...state.queueItemsByConversation,
        [conversationId]: result.queue_items ?? [],
      };
      // 活动任务集合只更新本会话条目；其余聊天的运行中任务不受影响。
      const activeTasksByConversation = { ...state.activeTasksByConversation };
      if (result.active_task) {
        activeTasksByConversation[conversationId] = result.active_task;
      } else {
        delete activeTasksByConversation[conversationId];
      }
      // 打开本窗口标签并聚焦；模式随该会话的 last_mode 采纳。
      const openConversationIds = state.openConversationIds.includes(conversationId)
        ? state.openConversationIds
        : [...state.openConversationIds, conversationId];
      const mode =
        conversation.last_mode === "collaboration" ? "collaboration" : "chat";
      const next: DesktopState = {
        ...state,
        conversationsById,
        projectsById,
        messagesById,
        messageIdsByConversation,
        toolRunsById,
        toolIdsByConversation,
        turnsById,
        turnIdsByConversation,
        queueItemsByConversation,
        activeTasksByConversation,
        openConversationIds,
        activeConversationId: conversationId,
        activeProjectId: projectId || null,
        pair: result.pair ?? state.pair,
        pairs:
          result.pair && !state.pairs.some((item) => item.pair_id === result.pair!.pair_id)
            ? [...state.pairs, result.pair]
            : state.pairs,
        mode,
        // M4.4：进入 chat 模式时发送对象重置为角色。
        composerTarget: mode === "chat" ? "character" : state.composerTarget,
      };
      const hydrated = {
        ...next,
        ...refreshWindowTask(next),
        // conversation.open 只替换目标会话；窗口全局游标继续保持常驻订阅的进度。
        lastSequence: state.lastSequence,
        streamId: resultStream,
      };
      const seenSequences = new Set<number>();
      const targetEvents = bufferedEvents
        .filter((event) => {
          if (event.event === "connection.status" || event.event === "state.snapshot") return false;
          const eventStream = event.stream_id == null ? null : String(event.stream_id);
          if (resultStream && eventStream !== resultStream) return false;
          if (event.sequence <= result.sequence || seenSequences.has(event.sequence)) return false;
          if (!eventTargetsConversation(event, conversationId)) return false;
          seenSequences.add(event.sequence);
          return true;
        })
        .sort((left, right) => left.sequence - right.sequence);
      const globalSequence = hydrated.lastSequence;
      return targetEvents.reduce(
        (current, event) => ({ ...applyBusinessEvent(current, event), lastSequence: globalSequence }),
        hydrated,
      );
    });
  },
  setViewId(viewId) {
    set({ viewId });
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
  setActiveConversation(conversationId) {
    set((state) => {
      // 只允许聚焦已打开的标签；未打开的标签必须走 openConversationTab。
      if (!state.openConversationIds.includes(conversationId)) return state;
      const derived = refreshWindowTask({
        ...state,
        activeConversationId: conversationId,
      });
      return {
        activeConversationId: conversationId,
        activeProjectId: state.conversationsById[conversationId]?.project_id ?? null,
        ...derived,
      };
    });
  },
  applyEvents(events) {
    set((state) => events.reduce(applyEvent, state));
  },
  setStatus(status, error = null) {
    set({ status, error });
  },
  setTheme(theme) {
    set({ theme });
  },
  setMode(mode) {
    // M4.4：切回聊天时发送对象强制回到角色，store 是唯一状态源。
    set(mode === "chat" ? { mode, composerTarget: "character" } : { mode });
  },
  setComposerTarget(target) {
    set({ composerTarget: target });
  },
  setComposerDraft(draft) {
    set({ composerDraft: draft });
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
  setReviewStatus(active, text = null) {
    set({ reviewActive: active, reviewText: text });
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
}));

export function useDesktopStore<T>(selector: (state: DesktopState) => T): T {
  return useStore(desktopStore, selector);
}

export const selectCurrentProject = (state: DesktopState) =>
  state.projectsById[state.currentProjectId];
export const selectCurrentConversation = (state: DesktopState) =>
  state.conversationsById[state.currentConversationId];

/** V0.3.2 M5：本窗口当前聊天只由活动标签决定；无标签时返回 null。 */
export const selectWindowConversationId = (state: DesktopState): string | null =>
  state.activeConversationId;

/** V0.3.2 M5：本窗口当前项目由活动标签所属项目决定，最后回退到后端快照指针。 */
export const selectWindowProjectId = (state: DesktopState): string | null =>
  state.activeProjectId ?? (state.currentProjectId || null);

export const selectDesktopRenderState = (state: DesktopState): DesktopRenderState => ({
  status: state.status,
  error: state.error,
  theme: state.theme,
  mode: state.mode,
  composerTarget: state.composerTarget,
  composerDraft: state.composerDraft,
  projectsById: state.projectsById,
  conversationsById: state.conversationsById,
  messagesById: state.messagesById,
  messageIdsByConversation: state.messageIdsByConversation,
  toolRunsById: state.toolRunsById,
  toolIdsByConversation: state.toolIdsByConversation,
  turnsById: state.turnsById,
  turnIdsByConversation: state.turnIdsByConversation,
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
  resolvedApprovals: state.resolvedApprovals,
  approvalResolvingById: state.approvalResolvingById,
  reviewActive: state.reviewActive,
  reviewText: state.reviewText,
  voice: state.voice,
  toasts: state.toasts,
  configSnapshot: state.configSnapshot,
  viewId: state.viewId,
  openConversationIds: state.openConversationIds,
  activeConversationId: state.activeConversationId,
  activeProjectId: state.activeProjectId,
  mainView: state.mainView,
  characterLibrary: state.characterLibrary,
  characterCreate: state.characterCreate,
  remotePairing: state.remotePairing,
});
