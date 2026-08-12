import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";

import type {
  AccountListItem,
  AccountRecord,
  ConversationRecord,
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PairRecord,
  PendingApproval,
  ProjectRecord,
  QueueItem,
  ToolRun,
  Turn,
  VoiceState,
} from "../contracts/protocol";

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
  currentAccount: AccountRecord | null;
  accounts: AccountListItem[];
  currentProjectId: string;
  currentConversationId: string;
  pair: PairRecord | null;
  activeTask: DesktopSnapshot["active_task"];
  busy: boolean;
  approvals: PendingApproval[];
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
  hydrate(snapshot: DesktopSnapshot): void;
  applyEvents(events: DesktopEvent[]): void;
  setStatus(status: DesktopStatus, error?: string | null): void;
  setTheme(theme: "dark" | "light"): void;
  setMode(mode: "chat" | "collaboration"): void;
  setComposerTarget(target: "character" | "assistant"): void;
  setComposerDraft(draft: string): void;
  setApprovalResolving(approvalId: string, resolving: boolean): void;
  setReviewStatus(active: boolean, text?: string | null): void;
  dismissToast(id: string): void;
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
  | "activeTask"
  | "busy"
  | "approvals"
  | "approvalResolvingById"
  | "reviewActive"
  | "reviewText"
  | "voice"
  | "toasts"
  | "configSnapshot"
>;

const emptyVoice: VoiceState = {
  supported: false,
  vad: "idle",
  vad_enabled: false,
  ptt: false,
  tts: "idle",
  asr_partial: "",
  error: null,
  speech_queue_len: 0,
};

function createInitialState(): Omit<
  DesktopState,
  | "hydrate"
  | "applyEvents"
  | "setStatus"
  | "setTheme"
  | "setMode"
  | "setComposerTarget"
  | "setComposerDraft"
  | "setApprovalResolving"
  | "setReviewStatus"
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
    currentAccount: null,
    accounts: [],
    currentProjectId: "",
    currentConversationId: "",
    pair: null,
    activeTask: null,
    busy: false,
    approvals: [],
    approvalResolvingById: {},
    reviewActive: false,
    reviewText: null,
    voice: emptyVoice,
    toasts: [],
    configSnapshot: null,
    lastSequence: -1,
    needsBootstrap: false,
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
    toolRunsById[toolRun.tool_call_id] = toolRun;
    (toolIdsByConversation[toolRun.conversation_id] ??= []).push(toolRun.tool_call_id);
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

function pushToast(toasts: StoreToast[], toast: StoreToast): StoreToast[] {
  // V0.2 M4：同 code+message 去重（以 id 为准），最多保留 5 条
  if (toasts.some((item) => item.id === toast.id)) return toasts;
  return [...toasts, toast].slice(-5);
}

function hydrateSnapshotState(state: DesktopState, snapshot: DesktopSnapshot): DesktopState {
  // V0.2 模式独立（问题 3）：设置类命令的快照不得回推覆盖本地模式。
  // 只有首次水合（boot）或切换会话时才从后端 last_mode 采纳模式；
  // 其余增量快照（如推理档位/审批方式修改）保持当前模式不变。
  const conversationChanged =
    state.lastSequence >= 0 && state.currentConversationId !== snapshot.current_conversation_id;
  const mode =
    state.lastSequence === -1 || conversationChanged
      ? snapshot.current_conversation.last_mode === "collaboration"
        ? "collaboration"
        : "chat"
      : state.mode;
  return {
    ...state,
    ...indexSnapshot(snapshot),
    status: "ready",
    error: null,
    currentAccountId: snapshot.current_account_id,
    currentAccount: snapshot.current_account ?? null,
    accounts: snapshot.accounts ?? [],
    currentProjectId: snapshot.current_project_id,
    currentConversationId: snapshot.current_conversation_id,
    pair: snapshot.pair,
    activeTask: snapshot.active_task,
    busy: snapshot.busy,
      approvals: snapshot.approvals,
      approvalResolvingById: {},
    reviewActive: false,
    reviewText: null,
    voice: snapshot.voice,
    // V0.2 M4：快照水合（重启/重连/切换账号）重置本地 UI 缓存——
    // Toast 与配置快照不属于后端快照，旧值不得跨水合残留
    toasts: [],
    configSnapshot: null,
    mode,
    lastSequence: snapshot.sequence,
    needsBootstrap: false,
  };
}

function applyEvent(state: DesktopState, event: DesktopEvent): DesktopState {
  if (event.sequence <= state.lastSequence) return state;
  if (state.lastSequence >= 0 && event.sequence !== state.lastSequence + 1) {
    return { ...state, needsBootstrap: true, lastSequence: event.sequence };
  }

  const next: DesktopState = { ...state, lastSequence: event.sequence };
  switch (event.event) {
    case "backend.ready":
      next.status = "booting";
      break;
    case "state.snapshot":
      return hydrateSnapshotState(next, event.payload as unknown as DesktopSnapshot);
    case "message.created": {
      const message = event.payload.message as Message;
      next.messagesById = { ...next.messagesById, [message.message_id]: message };
      const ids = next.messageIdsByConversation[message.conversation_id] ?? [];
      if (!ids.includes(message.message_id)) {
        next.messageIdsByConversation = {
          ...next.messageIdsByConversation,
          [message.conversation_id]: [...ids, message.message_id],
        };
      }
      break;
    }
    case "message.status_changed": {
      // V0.2 消息生命周期推进：按真实 id 对账（失败保留文字，可重试）
      const message = event.payload.message as Message;
      const current = next.messagesById[message.message_id];
      if (current) {
        next.messagesById = { ...next.messagesById, [message.message_id]: message };
      }
      break;
    }
    case "message.delta": {
      const payload = event.payload as unknown as {
        message_id: string;
        conversation_id: string;
        source: Message["source"];
        kind: Message["kind"];
        delta: string;
      };
      const current = next.messagesById[payload.message_id];
      const message: Message = current
        ? { ...current, text: current.text + payload.delta, streaming: true }
        : {
            message_id: payload.message_id,
            conversation_id: payload.conversation_id,
            pair_id: next.pair?.pair_id ?? "",
            engine_turn_id: null,
            source: payload.source,
            kind: payload.kind,
            text: payload.delta,
            payload: {},
            tts_eligible: payload.source === "character" || payload.source === "assistant",
            created_at: new Date().toISOString(),
            streaming: true,
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
      next.toolRunsById = { ...next.toolRunsById, [toolRun.tool_call_id]: toolRun };
      const ids = next.toolIdsByConversation[toolRun.conversation_id] ?? [];
      if (!ids.includes(toolRun.tool_call_id)) {
        next.toolIdsByConversation = {
          ...next.toolIdsByConversation,
          [toolRun.conversation_id]: [...ids, toolRun.tool_call_id],
        };
      }
      break;
    }
    case "approval.requested":
      {
        const approval = event.payload as unknown as PendingApproval;
        next.approvals = [
          ...next.approvals.filter((item) => item.approval_id !== approval.approval_id),
          approval,
        ];
      }
      break;
    case "approval.resolved": {
      const approvalId = String(event.payload.approval_id ?? "");
      next.approvals = next.approvals.filter((item) => item.approval_id !== approvalId);
      const { [approvalId]: _resolved, ...remaining } = next.approvalResolvingById;
      next.approvalResolvingById = remaining;
      break;
    }
    case "task.busy_changed":
      next.busy = Boolean(event.payload.busy);
      next.activeTask = (event.payload.active_task as DesktopSnapshot["active_task"]) ?? null;
      break;
    case "turn.started":
    case "turn.status_changed": {
      // V0.2 M2：Turn 生命周期推进（started → running → completed/failed/cancelled）。
      // 快照水合后同 turn 的事件按状态覆盖。
      const turn = event.payload.turn as Turn;
      if (!turn) break;
      next.turnsById = { ...next.turnsById, [turn.turn_id]: turn };
      const ids = next.turnIdsByConversation[turn.conversation_id] ?? [];
      if (!ids.includes(turn.turn_id)) {
        next.turnIdsByConversation = {
          ...next.turnIdsByConversation,
          [turn.conversation_id]: [...ids, turn.turn_id],
        };
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
      next.reviewText = payload.allow === false
        ? `审查否决：${payload.reason ?? ""}`
        : payload.allow === true
          ? "审查通过"
          : null;
      break;
    }
    case "review.failed":
      next.reviewActive = false;
      next.reviewText = "审查失败：已按安全默认否决";
      break;
    case "project.changed": {
      const project = event.payload.project as ProjectRecord;
      next.projectsById = { ...next.projectsById, [project.project_id]: project };
      break;
    }
    case "conversation.changed": {
      const conversation = event.payload.conversation as ConversationRecord;
      if (conversation) next.conversationsById = { ...next.conversationsById, [conversation.conversation_id]: conversation };
      break;
    }
    case "voice.asr_partial":
      next.voice = { ...next.voice, asr_partial: String(event.payload.text ?? "") };
      break;
    case "voice.state_changed":
      next.voice = { ...next.voice, ...(event.payload.voice as Partial<VoiceState>) };
      break;
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
    case "error.reported": {
      // V0.2 错误分级（问题 9）：fatal 接管整屏；recoverable/info 保留已加载
      // 内容，入 Toast 队列（同 code+message 去重，最多 5 条）。
      const payload = event.payload as { message?: string; severity?: string; code?: string };
      const severity = payload.severity ?? "fatal";
      if (severity === "fatal") {
        next.status = "error";
        next.error = String(payload.message ?? "桌面后端错误");
      } else {
        const text = String(payload.message ?? "");
        next.error = text;
        next.toasts = pushToast(next.toasts, {
          id: `${payload.code ?? "error"}:${text}`,
          kind: severity === "info" ? "info" : "warning",
          text,
          hasDetails: Boolean(payload.code),
        });
      }
      break;
    }
    case "account.changed": {
      // V0.2 M4：账号变更事件水合当前账号与账号列表（登录/注册/切换）
      const payload = event.payload as { account?: AccountRecord; accounts?: AccountListItem[] };
      if (payload.account) {
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
    set((state) => hydrateSnapshotState(state, snapshot));
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
    set({ mode });
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
  setConfigSnapshot(snapshot) {
    set({ configSnapshot: snapshot });
  },
}));

export function useDesktopStore<T>(selector: (state: DesktopState) => T): T {
  return useStore(desktopStore, selector);
}

export const selectCurrentProject = (state: DesktopState) =>
  state.projectsById[state.currentProjectId];
export const selectCurrentConversation = (state: DesktopState) =>
  state.conversationsById[state.currentConversationId];

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
  activeTask: state.activeTask,
  busy: state.busy,
  approvals: state.approvals,
  approvalResolvingById: state.approvalResolvingById,
  reviewActive: state.reviewActive,
  reviewText: state.reviewText,
  voice: state.voice,
  toasts: state.toasts,
  configSnapshot: state.configSnapshot,
});
