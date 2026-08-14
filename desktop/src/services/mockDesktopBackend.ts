import type {
  ConversationRecord,
  DesktopCommand,
  DesktopEvent,
  DesktopSnapshot,
  Message,
  PendingApproval,
  ProjectRecord,
  QueueItem,
  ToolRun,
  Turn,
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
  /** 记录全部 request 命令（供测试断言接线与参数，不参与 mock 行为）。 */
  readonly recordedRequests: DesktopCommand[] = [];

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
    this.recordedRequests.push(command);
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
      case "queue.edit":
        return this.editQueueItem(command.params) as T;
      case "queue.withdraw":
        return this.withdrawQueueItem(command.params) as T;
      case "queue.prioritize":
        return this.prioritizeQueueItem(command.params) as T;
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
      case "voice.tts_skip":
        // V0.2 M4：mock 简化——跳下一条等价于停止播放（tts 回 idle）
        return this.setVoiceState({ tts: "idle" }) as T;
      case "account.list":
        return this.accountList() as T;
      case "account.register":
        return this.accountRegister(command.params) as T;
      case "account.login":
        return this.accountLogin(command.params) as T;
      case "account.logout":
        return this.accountLogin({ account_id: "default-local", password: "" }) as T;
      case "account.onboarding_complete":
        return this.accountCompleteOnboarding() as T;
      case "account.update_profile":
        return this.updateAccountProfile(command.params) as T;
      case "account.change_password":
        return { changed: true } as T;
      case "config.get":
        return this.configGet() as T;
      case "config.set":
        return this.configSet(command.params) as T;
      case "config.test_connection":
        return { ok: true, message: "连接正常（延迟 12 ms）" } as T;
      case "codex.oauth_start":
        return { status: "waiting", note: "mock 登录" } as T;
      case "codex.oauth_status":
        return { status: "logged_in", account_label: "mock@openai" } as T;
      case "codex.logout":
        return { status: "logged_out" } as T;
      case "codex.api_login":
        return { status: "logged_in", account_label: "OpenAI API Key" } as T;
      case "voice.preview":
        return { voice: this.scenario.snapshot.voice } as T;
      default:
        // 尚未实现的 V0.2 命令在 mock 中返回空对象（不阻断前端流程）
        return {} as T;
    }
  }

  async pickFolder(): Promise<string | null> {
    return null;
  }

  async reconnectSidecar(): Promise<void> {
    // 模拟一次断线-恢复：先断开并上报可恢复错误，随后立即恢复
    // （connection.status connected 会驱动 store 进入 booting 并重新 bootstrap）。
    this.emit("connection.status", { status: "disconnected" });
    this.emit("error.reported", {
      code: "backend_disconnected",
      message: "Python Sidecar 已断开，正在重连…",
      severity: "recoverable",
      source: "sidecar",
    });
    this.emit("connection.status", { status: "connected" });
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
    const pairId =
      typeof params.pair_id === "string"
        ? params.pair_id
        : this.scenario.snapshot.pair?.pair_id ?? "phainon_ancient_machine";
    const newConversation = conversation(
      conversationId,
      projectId,
      String(params.title ?? "新聊天"),
      pairId,
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
    const turn = (status: Turn["status"]): Turn =>
      mockTurn(turnId, projectId, conversationId, target, userMessageId, status);
    this.emit("turn.status_changed", { turn: turn("accepted") });
    const events =
      this.scenario.name === "chat-streaming" && conversationId === "conv-1"
        ? this.scenario.submitEvents
        : createSubmitEvents(conversationId, text, target);
    for (const event of events) this.emit(event.event, event.payload);
    this.emit("turn.started", { turn: turn("running") });
    this.emit("turn.status_changed", { turn: turn("completed") });
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

  private accountList(): { accounts: DesktopSnapshot["accounts"]; current_account_id: string } {
    return {
      accounts: this.scenario.snapshot.accounts,
      current_account_id: this.scenario.snapshot.current_account_id,
    };
  }

  private accountRegister(params: Record<string, unknown>): {
    account: DesktopSnapshot["current_account"];
    accounts: DesktopSnapshot["accounts"];
  } {
    const username = String(params.username ?? "mock-user");
    const account = {
      account_id: `mock-account-${this.scenario.snapshot.accounts.length + 1}`,
      username,
      display_name: String(params.display_name ?? username),
      avatar: "",
      last_login_at: null,
      onboarding_complete: false,
      theme: "dark" as const,
    };
    this.scenario.snapshot.accounts = [
      ...this.scenario.snapshot.accounts.map((item) => ({ ...item, is_last_login: false })),
      { ...account, is_last_login: true },
    ];
    this.scenario.snapshot.current_account = account;
    this.scenario.snapshot.current_account_id = account.account_id;
    this.scenario.snapshot.projects = [];
    this.scenario.snapshot.current_project_id = "";
    this.scenario.snapshot.current_conversation_id = "";
    this.emit("account.changed", {
      account,
      accounts: this.scenario.snapshot.accounts,
    });
    return { account, accounts: this.clone(this.scenario.snapshot.accounts) };
  }

  private accountLogin(params: Record<string, unknown>): {
    account: DesktopSnapshot["current_account"];
    accounts: DesktopSnapshot["accounts"];
  } {
    const accountId = String(params.account_id ?? "default-local");
    const account = this.scenario.snapshot.accounts.find(
      (item) => item.account_id === accountId,
    ) ?? this.scenario.snapshot.accounts[0];
    const next: DesktopSnapshot["current_account"] = {
      account_id: account.account_id,
      username: account.username,
      display_name: account.display_name,
      avatar: account.avatar,
      last_login_at: new Date().toISOString(),
      onboarding_complete: account.onboarding_complete,
      theme: account.theme,
    };
    this.scenario.snapshot.accounts = this.scenario.snapshot.accounts.map((item) => ({
      ...item,
      is_last_login: item.account_id === account.account_id,
    }));
    this.scenario.snapshot.current_account = next;
    this.scenario.snapshot.current_account_id = account.account_id;
    this.emit("account.changed", {
      account: next,
      accounts: this.scenario.snapshot.accounts,
    });
    return { account: next, accounts: this.clone(this.scenario.snapshot.accounts) };
  }

  private accountCompleteOnboarding(): { account: DesktopSnapshot["current_account"] } {
    // V0.2 M4：首次引导完成——置 onboarding_complete 并广播 account.changed
    const current = this.scenario.snapshot.current_account;
    const next = { ...current, onboarding_complete: true };
    this.scenario.snapshot.current_account = next;
    this.scenario.snapshot.accounts = this.scenario.snapshot.accounts.map((item) =>
      item.account_id === next.account_id ? { ...item, onboarding_complete: true } : item,
    );
    this.emit("account.changed", {
      account: next,
      accounts: this.scenario.snapshot.accounts,
    });
    return { account: next };
  }

  private updateAccountProfile(params: Record<string, unknown>): { account: DesktopSnapshot["current_account"] } {
    const current = this.scenario.snapshot.current_account;
    const next = {
      ...current,
      display_name: String(params.display_name ?? current.display_name),
      avatar: params.avatar === undefined ? current.avatar : String(params.avatar),
    };
    this.scenario.snapshot.current_account = next;
    this.scenario.snapshot.accounts = this.scenario.snapshot.accounts.map((item) =>
      item.account_id === next.account_id ? { ...item, ...next } : item,
    );
    this.emit("account.changed", {
      account: next,
      accounts: this.scenario.snapshot.accounts,
    });
    return { account: next };
  }

  private configGet(): {
    engine: string;
    dialogue: Record<string, string>;
    voice: Record<string, string>;
    codex: Record<string, string | null>;
  } {
    return {
      engine: "deepseek",
      dialogue: {
        provider: "deepseek",
        model: "deepseek-chat",
        base_url: "https://api.deepseek.com",
        api_key_masked: "sk-d…1234",
        reasoning_effort: "auto",
      },
      voice: {
        enabled: "true",
        assistant_voice_enabled: "false",
        base_url: "https://dashscope.aliyuncs.com/api/v1",
        api_key_masked: "sk-v…5678",
        asr_model: "qwen-audio-3.0-asr-flash-streaming",
        tts_model: "qwen-audio-3.0-tts-flash",
        character_voice: "qwen-audio-3.0-tts-flash-phainon-46e9bd0087cd4c4c8d29e1b9f1b5db32",
        character_voice_name: "白厄",
        assistant_voice: "qwen-audio-3.0-tts-flash-vd-ancientmac-a26ce26e55414e219fe00360e24b4f19",
        assistant_voice_name: "神秘的古代机械",
        vad_enabled: "false",
      },
      codex: { status: "logged_in", account_label: "mock@openai" },
    };
  }

  private configSet(_params: Record<string, unknown>): {
    config: ReturnType<MockDesktopBackend["configGet"]>;
  } {
    return { config: this.configGet() };
  }

  emitQueueChanged(conversationId: string, items: QueueItem[]): void {
    this.scenario.snapshot.queue_items = items;
    this.emit("queue.changed", { conversation_id: conversationId, items });
  }

  private editQueueItem(params: Record<string, unknown>): { queue_item: QueueItem } {
    const queueItemId = String(params.queue_item_id ?? "");
    const text = String(params.text ?? "");
    const items = this.scenario.snapshot.queue_items.map((item) =>
      item.queue_item_id === queueItemId && item.status === "queued"
        ? { ...item, text }
        : item,
    );
    const queueItem = items.find((item) => item.queue_item_id === queueItemId)!;
    this.emitQueueChanged(queueItem.conversation_id, items);
    return { queue_item: queueItem };
  }

  private withdrawQueueItem(params: Record<string, unknown>): { queue_item: QueueItem } {
    const queueItemId = String(params.queue_item_id ?? "");
    const items = this.scenario.snapshot.queue_items.map((item) =>
      item.queue_item_id === queueItemId ? { ...item, status: "withdrawn" as const } : item,
    );
    const queueItem = items.find((item) => item.queue_item_id === queueItemId)!;
    this.emitQueueChanged(queueItem.conversation_id, items);
    return { queue_item: queueItem };
  }

  private prioritizeQueueItem(params: Record<string, unknown>): { queue_item: QueueItem } {
    const queueItemId = String(params.queue_item_id ?? "");
    // 与后端一致：其余 queued 项 position + 1，目标项置队首
    const items = this.scenario.snapshot.queue_items
      .map((item) =>
        item.queue_item_id === queueItemId && item.status === "queued"
          ? { ...item, position: 0 }
          : item.status === "queued"
            ? { ...item, position: item.position + 1 }
            : item,
      )
      .sort((a, b) => a.position - b.position);
    const queueItem = items.find((item) => item.queue_item_id === queueItemId)!;
    this.emitQueueChanged(queueItem.conversation_id, items);
    return { queue_item: queueItem };
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
      const payload = event.payload as {
        message_id: string;
        conversation_id: string;
        source: Message["source"];
        kind: Message["kind"];
        delta?: string;
        channel?: string;
        started?: boolean;
        completed?: boolean;
        reasoning_streaming?: boolean;
      };
      const current = snapshot.messages.find((item) => item.message_id === payload.message_id);
      const delta = String(payload.delta ?? "");
      const reasoningDelta =
        (payload.source === "character" && payload.channel === "reasoning") ||
        (payload.source === "assistant" && payload.kind === "assistant.reasoning");
      const messagePayload: Record<string, unknown> = { ...(current?.payload ?? {}) };
      let text = current?.text ?? "";
      if (payload.reasoning_streaming !== undefined) {
        messagePayload.reasoning_streaming = payload.reasoning_streaming;
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
      const nextMessage: Message = current
        ? { ...current, text, payload: messagePayload, streaming: true }
        : {
            message_id: payload.message_id,
            conversation_id: payload.conversation_id,
            pair_id: snapshot.pair.pair_id,
            engine_turn_id: null,
            source: payload.source,
            kind: payload.kind,
            text,
            payload: messagePayload,
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

function mockTurn(
  turnId: string,
  projectId: string,
  conversationId: string,
  target: Turn["target"],
  sourceMessageId: string,
  status: Turn["status"],
): Turn {
  return {
    turn_id: turnId,
    account_id: "",
    project_id: projectId,
    conversation_id: conversationId,
    target,
    source_message_id: sourceMessageId,
    status,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
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
