import type {
  ConversationRecord,
  DesktopCommand,
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PendingApproval,
  ProjectRecord,
  ToolRun,
} from "../contracts/protocol";
import type { DesktopBackend } from "./backend";
import { RequestIdFactory } from "./backend";
import {
  createMockScenario,
  conversation,
  message,
  project,
  type MockScenario,
  type MockScenarioName,
} from "../mocks/scenarios";

export class MockDesktopBackend implements DesktopBackend {
  private readonly listeners = new Set<(event: DesktopEvent) => void>();
  private readonly requestIds = new RequestIdFactory();
  private scenario: MockScenario;
  private sequence: number;

  constructor(scenarioName: MockScenarioName = "single-project") {
    this.scenario = createMockScenario(scenarioName);
    this.sequence = this.scenario.snapshot.sequence;
  }

  setScenario(name: MockScenarioName): void {
    this.scenario = createMockScenario(name);
    this.sequence = this.scenario.snapshot.sequence;
  }

  get scenarioName(): MockScenarioName {
    return this.scenario.name;
  }

  async request<T>(command: DesktopCommand): Promise<T> {
    switch (command.method) {
      case "app.bootstrap":
        return this.snapshotResult<T>();
      case "app.shutdown":
        return { stopped: true } as T;
      case "project.create":
        return this.createProject(command.params) as T;
      case "project.select":
        return this.selectProject(command.params) as T;
      case "project.update_settings":
        return this.updateProjectSettings(command.params) as T;
      case "project.archive":
        return this.archiveProject(command.params) as T;
      case "conversation.create":
        return this.createConversation(command.params) as T;
      case "conversation.select":
        return this.selectConversation(command.params) as T;
      case "conversation.rename":
        return this.renameConversation(command.params) as T;
      case "conversation.archive":
        return this.archiveConversation(command.params) as T;
      case "conversation.set_mode":
        return this.setConversationMode(command.params) as T;
      case "chat.submit":
        return this.submitMessage(command.params) as T;
      case "task.cancel":
        this.emit("task.busy_changed", { busy: false, active_task: null });
        return { cancelled: true } as T;
      case "approval.resolve":
        this.emit("approval.resolved", {
          approval_id: String(command.params.approval_id ?? ""),
        });
        return { accepted: true } as T;
      case "voice.vad_set":
        return this.setVoiceState({
          vad_enabled: Boolean(command.params.enabled),
          vad: command.params.enabled ? "listening" : "idle",
        }) as T;
      case "voice.ptt_start":
        return this.setVoiceState({ ptt: true, vad: "listening" }) as T;
      case "voice.ptt_stop":
        return this.setVoiceState({ ptt: false, vad: "idle" }) as T;
      case "voice.tts_stop":
        return this.setVoiceState({ tts: "idle" }) as T;
      default:
        // 尚未实现的 V0.2 命令在 mock 中返回空对象（不阻断前端流程）
        return {} as T;
    }
  }

  async pickFolder(): Promise<string | null> {
    return null;
  }

  subscribe(listener: (event: DesktopEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event: DesktopEvent["event"], payload: Record<string, unknown>): void {
    const message: DesktopEvent = {
      kind: "event",
      event,
      sequence: this.sequence + 1,
      payload,
    };
    this.sequence += 1;
    this.applyEventToSnapshot(message);
    this.scenario.snapshot.sequence = this.sequence;
    for (const listener of this.listeners) listener(message);
  }

  private snapshotResult<T>(): T {
    this.refreshCurrentPointers();
    this.scenario.snapshot.sequence = this.sequence;
    return this.clone(this.scenario.snapshot) as T;
  }

  private createProject(params: Record<string, unknown>): DesktopSnapshot {
    const rootPath = String(params.root_path ?? "C:/Projects/mock-project");
    const projectId = `mock-project-${this.scenario.snapshot.projects.length + 1}`;
    const conversationId = `${projectId}-conversation-1`;
    const firstConversation = conversation(
      conversationId,
      projectId,
      String(params.title ?? "新聊天"),
    );
    const requestedName = String(params.name ?? "").trim();
    const newProject = project(
      projectId,
      requestedName || folderNameFromPath(rootPath) || `项目 ${this.scenario.snapshot.projects.length + 1}`,
      rootPath,
      [firstConversation],
    );
    this.scenario.snapshot.projects = [...this.scenario.snapshot.projects, newProject];
    this.scenario.snapshot.current_project_id = projectId;
    this.scenario.snapshot.current_conversation_id = conversationId;
    return this.snapshotResult<DesktopSnapshot>();
  }

  private selectProject(params: Record<string, unknown>): DesktopSnapshot {
    const projectId = String(params.project_id ?? "");
    const selected = this.scenario.snapshot.projects.find((item) => item.project_id === projectId);
    if (!selected) return this.snapshotResult<DesktopSnapshot>();
    const requestedConversationId = String(params.conversation_id ?? "");
    const selectedConversation = selected.conversations.find(
      (item) => item.conversation_id === requestedConversationId,
    ) ?? selected.conversations.find((item) => !item.archived) ?? selected.conversations[0];
    this.scenario.snapshot.current_project_id = selected.project_id;
    this.scenario.snapshot.current_conversation_id = selectedConversation?.conversation_id ?? "";
    return this.snapshotResult<DesktopSnapshot>();
  }

  private updateProjectSettings(params: Record<string, unknown>): { project: ProjectRecord } {
    const projectId = String(params.project_id ?? this.scenario.snapshot.current_project_id);
    const projects = this.scenario.snapshot.projects.map((item) =>
      item.project_id === projectId
        ? {
            ...item,
            name: String(params.name ?? item.name),
            root_path: String(params.root_path ?? item.root_path),
            path_available: params.root_path ? true : item.path_available,
            approval_mode: (params.approval_mode as ProjectRecord["approval_mode"]) ?? item.approval_mode,
            reasoning_effort: String(params.reasoning_effort ?? item.reasoning_effort),
          }
        : item,
    );
    this.scenario.snapshot.projects = projects;
    const project = projects.find((item) => item.project_id === projectId)!;
    this.emit("project.changed", { project });
    return { project: this.clone(project) };
  }

  private setConversationMode(params: Record<string, unknown>): {
    conversation_id: string;
    mode: "chat" | "collaboration";
  } {
    const conversationId = String(
      params.conversation_id ?? this.scenario.snapshot.current_conversation_id,
    );
    const mode = params.mode === "collaboration" ? "collaboration" : "chat";
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
      ...item,
      conversations: item.conversations.map((candidate) =>
        candidate.conversation_id === conversationId
          ? { ...candidate, last_mode: mode }
          : candidate,
      ),
    }));
    const conversation = this.scenario.snapshot.projects
      .flatMap((item) => item.conversations)
      .find((item) => item.conversation_id === conversationId);
    if (conversation) this.emit("conversation.changed", { conversation });
    return { conversation_id: conversationId, mode };
  }

  private createConversation(params: Record<string, unknown>): DesktopSnapshot {
    const projectId = String(params.project_id ?? this.scenario.snapshot.current_project_id);
    const projectIndex = this.scenario.snapshot.projects.findIndex(
      (item) => item.project_id === projectId,
    );
    if (projectIndex < 0) return this.snapshotResult<DesktopSnapshot>();
    const selectedProject = this.scenario.snapshot.projects[projectIndex];
    const conversationId = `${projectId}-conversation-${selectedProject.conversations.length + 1}`;
    const newConversation = conversation(
      conversationId,
      projectId,
      String(params.title ?? "新聊天"),
    );
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item, index) =>
      index === projectIndex
        ? { ...item, conversations: [...item.conversations, newConversation] }
        : item,
    );
    this.scenario.snapshot.current_project_id = projectId;
    this.scenario.snapshot.current_conversation_id = conversationId;
    return this.snapshotResult<DesktopSnapshot>();
  }

  private selectConversation(params: Record<string, unknown>): DesktopSnapshot {
    const conversationId = String(params.conversation_id ?? "");
    for (const item of this.scenario.snapshot.projects) {
      const selected = item.conversations.find(
        (candidate) => candidate.conversation_id === conversationId && !candidate.archived,
      );
      if (selected) {
        this.scenario.snapshot.current_project_id = item.project_id;
        this.scenario.snapshot.current_conversation_id = selected.conversation_id;
        break;
      }
    }
    return this.snapshotResult<DesktopSnapshot>();
  }

  private renameConversation(params: Record<string, unknown>): DesktopSnapshot {
    const conversationId = String(params.conversation_id ?? "");
    const title = String(params.title ?? "");
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
      ...item,
      conversations: item.conversations.map((candidate) =>
        candidate.conversation_id === conversationId ? { ...candidate, title } : candidate,
      ),
    }));
    return this.snapshotResult<DesktopSnapshot>();
  }

  private archiveConversation(params: Record<string, unknown>): DesktopSnapshot {
    const conversationId = String(
      params.conversation_id ?? this.scenario.snapshot.current_conversation_id,
    );
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
      ...item,
      conversations: item.conversations.map((candidate) =>
        candidate.conversation_id === conversationId ? { ...candidate, archived: true } : candidate,
      ),
    }));
    if (conversationId === this.scenario.snapshot.current_conversation_id) {
      const fallback = this.scenario.snapshot.projects
        .flatMap((item) => item.conversations)
        .find((candidate) => !candidate.archived);
      this.scenario.snapshot.current_conversation_id = fallback?.conversation_id ?? "";
    }
    return this.snapshotResult<DesktopSnapshot>();
  }

  private archiveProject(params: Record<string, unknown>): DesktopSnapshot {
    const projectId = String(
      params.project_id ?? this.scenario.snapshot.current_project_id,
    );
    this.scenario.snapshot.projects = this.scenario.snapshot.projects.filter(
      (item) => item.project_id !== projectId,
    );
    if (projectId === this.scenario.snapshot.current_project_id) {
      this.scenario.snapshot.current_project_id = "";
      this.scenario.snapshot.current_conversation_id = "";
    }
    return this.snapshotResult<DesktopSnapshot>();
  }

  private submitMessage(params: Record<string, unknown>): {
    message_id: string;
    conversation_id: string;
    status: string;
    target: string;
    turn_id: string;
  } {
    const conversationId = String(
      params.conversation_id ?? this.scenario.snapshot.current_conversation_id,
    );
    const target = params.target === "assistant" ? "assistant" : "character";
    const hadUserMessage = this.scenario.snapshot.messages.some(
      (item) => item.conversation_id === conversationId && item.source === "user",
    );
    const text = String(params.text ?? "");
    const userMessageId = `mock-user-${this.sequence + 1}`;
    // 快速接受：用户消息立即落库并返回真实 id
    const userMessage = message(
      userMessageId,
      conversationId,
      "user",
      "user.text",
      text,
    );
    userMessage.target = target;
    userMessage.origin = "user";
    userMessage.status = "received";
    this.emit("message.created", { message: userMessage });
    // V0.2 M2：Turn 生命周期模拟——accepted → running → completed
    const turnId = `mock-turn-${this.sequence + 1}`;
    const projectId = this.scenario.snapshot.projects.find((item) =>
      item.conversations.some((item) => item.conversation_id === conversationId),
    )?.project_id ?? "";
    this.emit("turn.status_changed", {
      turn: {
        turn_id: turnId,
        account_id: "",
        project_id: projectId,
        conversation_id: conversationId,
        target,
        source_message_id: userMessageId,
        status: "accepted",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    });
    const events =
      this.scenario.name === "chat-streaming" && conversationId === "conv-1"
        ? this.scenario.submitEvents
        : createSubmitEvents(conversationId, text, target);
    for (const event of events) this.emit(event.event, event.payload);
    this.emit("turn.started", {
      turn: {
        turn_id: turnId,
        account_id: "",
        project_id: projectId,
        conversation_id: conversationId,
        target,
        source_message_id: userMessageId,
        status: "running",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    });
    this.emit("turn.status_changed", {
      turn: {
        turn_id: turnId,
        account_id: "",
        project_id: projectId,
        conversation_id: conversationId,
        target,
        source_message_id: userMessageId,
        status: "completed",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    });
    if (!hadUserMessage) {
      const title = titleFromMessage(text);
      this.scenario.snapshot.projects = this.scenario.snapshot.projects.map((item) => ({
        ...item,
        conversations: item.conversations.map((candidate) =>
          candidate.conversation_id === conversationId && candidate.title === "新聊天"
            ? { ...candidate, title, updated_at: new Date().toISOString() }
            : candidate,
        ),
      }));
      const conversation = this.scenario.snapshot.projects
        .flatMap((item) => item.conversations)
        .find((item) => item.conversation_id === conversationId);
      if (conversation) this.emit("conversation.changed", { conversation });
    }
    return {
      message_id: userMessageId,
      conversation_id: conversationId,
      status: "received",
      target,
      turn_id: turnId,
    };
  }

  private setVoiceState(changes: Record<string, unknown>): { voice: DesktopSnapshot["voice"] } {
    const voice = { ...this.scenario.snapshot.voice, ...changes };
    this.emit("voice.state_changed", { voice });
    return { voice: this.clone(voice) };
  }

  private refreshCurrentPointers(): void {
    const snapshot = this.scenario.snapshot;
    const projectRecord = snapshot.projects.find(
      (item) => item.project_id === snapshot.current_project_id,
    ) ?? snapshot.projects.find((item) => !item.archived);
    const conversationRecord = projectRecord?.conversations.find(
      (item) => item.conversation_id === snapshot.current_conversation_id && !item.archived,
    ) ?? projectRecord?.conversations.find((item) => !item.archived);
    snapshot.current_project_id = projectRecord?.project_id ?? "";
    snapshot.current_conversation_id = conversationRecord?.conversation_id ?? "";
    snapshot.current_project = projectRecord
      ? projectWithoutConversations(projectRecord)
      : emptyProject();
    snapshot.current_conversation = conversationRecord ?? emptyConversation();
  }

  private applyEventToSnapshot(event: DesktopEvent): void {
    const snapshot = this.scenario.snapshot;
    if (event.event === "message.created") {
      const message = event.payload.message as Message;
      snapshot.messages = [
        ...snapshot.messages.filter((item) => item.message_id !== message.message_id),
        message,
      ];
    } else if (event.event === "message.delta") {
      const payload = event.payload as { message_id: string; conversation_id: string; source: Message["source"]; kind: Message["kind"]; delta: string };
      const current = snapshot.messages.find((item) => item.message_id === payload.message_id);
      const nextMessage: Message = current
        ? { ...current, text: current.text + payload.delta, streaming: true }
        : {
            message_id: payload.message_id,
            conversation_id: payload.conversation_id,
            pair_id: snapshot.pair.pair_id,
            engine_turn_id: null,
            source: payload.source,
            kind: payload.kind,
            text: payload.delta,
            payload: {},
            tts_eligible: payload.source === "character" || payload.source === "assistant",
            created_at: new Date().toISOString(),
            streaming: true,
          };
      snapshot.messages = [
        ...snapshot.messages.filter((item) => item.message_id !== payload.message_id),
        nextMessage,
      ];
    } else if (event.event === "message.finalized") {
      const messageId = String(event.payload.message_id ?? "");
      snapshot.messages = snapshot.messages.map((item) =>
        item.message_id === messageId ? { ...item, streaming: false } : item,
      );
    } else if (event.event === "message.status_changed") {
      const message = event.payload.message as Message;
      snapshot.messages = snapshot.messages.map((item) =>
        item.message_id === message.message_id ? message : item,
      );
    } else if (event.event === "tool_run.upserted") {
      const toolRun = event.payload.tool_run as ToolRun;
      snapshot.tool_runs = [
        ...snapshot.tool_runs.filter((item) => item.tool_call_id !== toolRun.tool_call_id),
        toolRun,
      ];
    } else if (event.event === "conversation.changed") {
      const conversation = event.payload.conversation as ConversationRecord | undefined;
      if (conversation) {
        snapshot.projects = snapshot.projects.map((item) => ({
          ...item,
          conversations: item.conversations.map((candidate) =>
            candidate.conversation_id === conversation.conversation_id
              ? conversation
              : candidate,
          ),
        }));
      }
    } else if (event.event === "turn.started" || event.event === "turn.status_changed") {
      const turn = event.payload.turn as DesktopSnapshot["turns"][number];
      snapshot.turns = [
        ...snapshot.turns.filter((item) => item.turn_id !== turn.turn_id),
        turn,
      ];
    } else if (event.event === "task.busy_changed") {
      snapshot.busy = Boolean(event.payload.busy);
      snapshot.active_task = (event.payload.active_task as DesktopSnapshot["active_task"]) ?? null;
    } else if (event.event === "approval.requested") {
      snapshot.approvals = [
        ...snapshot.approvals,
        event.payload as unknown as PendingApproval,
      ];
    } else if (event.event === "approval.resolved") {
      const approvalId = String(event.payload.approval_id ?? "");
      snapshot.approvals = snapshot.approvals.filter((item) => item.approval_id !== approvalId);
    } else if (event.event === "voice.state_changed") {
      snapshot.voice = { ...snapshot.voice, ...(event.payload.voice as Partial<DesktopSnapshot["voice"]>) };
    } else if (event.event === "voice.asr_partial") {
      snapshot.voice = { ...snapshot.voice, asr_partial: String(event.payload.text ?? "") };
    }
  }

  private clone<T>(value: T): T {
    return JSON.parse(JSON.stringify(value)) as T;
  }

  nextRequestId(): string {
    return this.requestIds.next();
  }
}

function projectWithoutConversations(projectRecord: ProjectRecord): DesktopSnapshot["current_project"] {
  const { conversations: _conversations, ...currentProject } = projectRecord;
  return currentProject;
}

function emptyProject(): DesktopSnapshot["current_project"] {
  return {
    project_id: "",
    name: "",
    root_path: "",
    approval_mode: "request_approval",
    reasoning_effort: "low",
    archived: false,
    created_at: null,
    last_opened_at: null,
    path_available: false,
  };
}

function emptyConversation(): ConversationRecord {
  return {
    conversation_id: "",
    project_id: null,
    pair_id: "phainon_ancient_machine",
    title: "",
    last_mode: "chat",
    archived: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function createSubmitEvents(
  conversationId: string,
  _text: string,
  target: "character" | "assistant",
): DesktopEvent[] {
  const source = target === "assistant" ? "assistant" : "character";
  const kind = target === "assistant" ? "assistant.natural_language" : "character.speech";
  const messageId = `mock-${source}-${Date.now()}`;
  return [
    {
      kind: "event",
      event: "message.delta",
      sequence: 0,
      payload: {
        message_id: messageId,
        conversation_id: conversationId,
        source,
        kind,
        delta: target === "assistant" ? "我会先检查这个任务。" : "好，我们继续。",
      },
    },
    {
      kind: "event",
      event: "message.finalized",
      sequence: 0,
      payload: { message_id: messageId, conversation_id: conversationId },
    },
  ];
}

function titleFromMessage(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return "新聊天";
  return `关于${compact.slice(0, 14)}`;
}

function folderNameFromPath(rootPath: string): string | null {
  const parts = rootPath.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? null;
}

export function isDesktopSnapshot(value: unknown): value is DesktopSnapshot {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as DesktopSnapshot).projects) &&
    typeof (value as DesktopSnapshot).current_conversation_id === "string"
  );
}
