import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";

import type {
  ApprovalMode,
  ConversationRecord,
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PairRecord,
  PendingApproval,
  ProjectRecord,
  ToolRun,
  VoiceState,
} from "../contracts/protocol";

export type DesktopStatus = "booting" | "ready" | "disconnected" | "error";

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
  currentProjectId: string;
  currentConversationId: string;
  pair: PairRecord | null;
  activeTask: DesktopSnapshot["active_task"];
  busy: boolean;
  approvals: PendingApproval[];
  approvalResolvingById: Record<string, boolean>;
  voice: VoiceState;
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
}

const emptyVoice: VoiceState = {
  supported: false,
  vad: "idle",
  vad_enabled: false,
  ptt: false,
  tts: "idle",
  asr_partial: "",
  error: null,
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
    currentProjectId: "",
    currentConversationId: "",
    pair: null,
    activeTask: null,
    busy: false,
    approvals: [],
    approvalResolvingById: {},
    voice: emptyVoice,
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
  return {
    projectsById,
    conversationsById,
    messagesById,
    messageIdsByConversation,
    toolRunsById,
    toolIdsByConversation,
  };
}

function hydrateSnapshotState(state: DesktopState, snapshot: DesktopSnapshot): DesktopState {
  return {
    ...state,
    ...indexSnapshot(snapshot),
    status: "ready",
    error: null,
    currentProjectId: snapshot.current_project_id,
    currentConversationId: snapshot.current_conversation_id,
    pair: snapshot.pair,
    activeTask: snapshot.active_task,
    busy: snapshot.busy,
      approvals: snapshot.approvals,
      approvalResolvingById: {},
    voice: snapshot.voice,
    mode: snapshot.current_conversation.last_mode === "collaboration" ? "collaboration" : "chat",
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
    case "error.reported":
      next.status = "error";
      next.error = String(event.payload.message ?? "桌面后端错误");
      break;
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
}));

export function useDesktopStore<T>(selector: (state: DesktopState) => T): T {
  return useStore(desktopStore, selector);
}

export const selectCurrentProject = (state: DesktopState) =>
  state.projectsById[state.currentProjectId];
export const selectCurrentConversation = (state: DesktopState) =>
  state.conversationsById[state.currentConversationId];
