import { create } from "zustand";
import type {
  ActiveTask,
  ConversationMode,
  ApprovalMode,
  ConversationOpenResult,
  ConversationRecord,
  DesktopSnapshot,
  Message,
  PairRecord,
  PendingApproval,
  PowerStatusPayload,
  ProjectRecord,
  ToolRun,
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
}

export interface MobileVoiceAvailability {
  secureContext: boolean;
  micPermission: "unknown" | "granted" | "denied" | "prompt";
  supported: boolean;
}

export interface MobileState {
  connection: MobileConnectionState;
  deviceName: string | null;
  projects: ProjectRecord[];
  conversationsById: Record<string, ConversationRecord>;
  activeConversationId: string | null;
  messages: Message[];
  toolRuns: ToolRun[];
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
  }>;
  /** V0.3.4：当前配对（委派卡「来自 <角色名> 的委派」数据源）。 */
  pair: PairRecord | null;
  /** V0.3.4：当前活动任务（委派卡运行状态与 delegation_id 对齐）。 */
  activeTask: ActiveTask | null;
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
    /** 下行 TTS 分片缓冲：message_id → 有序分片。 */
    ttsChunks: Record<string, Array<{ seq: number; mime: string; data: string }>>;
  };

  start: () => void;
  /** 手动重连入口（unreachable/auth_failed 后由 UI 重试按钮调用）。 */
  reconnect: () => void;
  pairDevice: (code: string, deviceName: string) => Promise<void>;
  openConversation: (conversationId: string) => Promise<void>;
  submitDelegation: (text: string) => Promise<void>;
  /** V0.3.4 缺陷 3：手机端普通角色消息输入（target=character，任何模式可用）。 */
  submitMessage: (text: string) => Promise<void>;
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
  refreshVoiceAvailability: () => Promise<void>;
  disconnect: () => void;
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

  set({
    projects: snapshot.projects,
    conversationsById: indexConversations(snapshot.projects),
    messages,
    toolRuns,
    approvals: snapshot.approvals,
    pair,
    activeTask,
    streamId: snapshot.stream_id == null ? get().streamId : String(snapshot.stream_id),
    lastSequence: snapshot.sequence,
    bootstrapped: true,
  });
}

export const useMobileStore = create<MobileState>((set, get) => {
  let wired = false;
  let bootstrapping: Promise<void> | null = null;
  let bootstrapGeneration = 0;
  let openConversationGeneration = 0;
  let stableConversationView: Pick<
    MobileState,
    "activeConversationId" | "messages" | "toolRuns" | "pair" | "activeTask"
  > | null = null;
  const eventCollectors = new Set<WireEvent[]>();

  /** connect() 只发起握手；pair 等调用必须等 connected 后才能发请求。 */
  const waitForConnected = (): Promise<void> => {
    if (client.getState() === "connected") return Promise.resolve();
    if (client.getState() === "disconnected") {
      return Promise.reject(new Error("连接已断开"));
    }
    return new Promise<void>((resolve, reject) => {
      const unsubscribe = client.onStateChange((connection) => {
        if (connection === "connected") {
          unsubscribe();
          resolve();
        }
        if (connection === "unreachable" || connection === "auth_failed") {
          unsubscribe();
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
    set({ bootstrapped: false });
  };

  const bootstrap = async (): Promise<void> => {
    if (bootstrapping) return bootstrapping;
    const generation = ++bootstrapGeneration;
    const activeConversationId = get().activeConversationId;
    const collector = collectEvents();
    let tracked: Promise<void>;
    const request = (async () => {
      const snapshot = await client.request<DesktopSnapshot>("app.bootstrap");
      if (generation !== bootstrapGeneration) return;
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
          pair: conversation.pair,
          activeTask: conversation.active_task,
          streamId: conversationStream,
          lastSequence: conversation.sequence,
          bootstrapped: true,
        });
        replayEventsAfter(collector.events, conversation.sequence, conversationStream);
        return;
      }
      replayEventsAfter(collector.events, snapshot.sequence, snapshotStream ?? get().streamId);
    })();
    tracked = request.finally(() => {
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
        const payload = event.payload as {
          approval_id?: string;
          conversation_id?: string;
          decision?: string;
          resolved_by?: string;
          task_id?: string;
        };
        if (payload.approval_id) {
          const existing = get().approvals.find((item) => item.approval_id === payload.approval_id);
          set({
            approvals: get().approvals.filter((item) => item.approval_id !== payload.approval_id),
            resolvedApprovals: [
              ...get().resolvedApprovals.filter((item) => item.approval_id !== payload.approval_id),
              {
                approval_id: payload.approval_id,
                conversation_id: payload.conversation_id ?? get().activeConversationId ?? undefined,
                // 真实协议 approval.resolved 总带合法 decision（allow/allow_for_conversation/deny）；
                // 缺失时不伪造方向，置空串由展示层给中性文案。
                decision: payload.decision ?? "",
                resolved_by: payload.resolved_by ?? "remote",
                task_id: payload.task_id,
                operation: existing?.operation,
                reason: existing?.reason,
              },
            ],
          });
        }
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
        const voice = get().voice;
        const chunks = voice.ttsChunks[payload.message_id] ?? [];
        const exists = chunks.some((item) => item.seq === payload.seq);
        const nextChunks = exists
          ? chunks
          : [...chunks, { seq: payload.seq, mime: payload.mime ?? "audio/pcm;rate=24000", data: payload.data ?? "" }].sort(
              (a, b) => a.seq - b.seq,
            );
        set({
          voice: {
            ...voice,
            playback: {
              messageId: payload.message_id,
              state: voice.playback.state === "idle" ? "buffering" : voice.playback.state,
              error: null,
            },
            ttsChunks: { ...voice.ttsChunks, [payload.message_id]: nextChunks },
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
        };
        if (failedPayload.message_id) {
          const failedVoice = get().voice;
          set({
            voice: {
              ...failedVoice,
              ttsChunks: Object.fromEntries(
                Object.entries(failedVoice.ttsChunks).filter(
                  ([id]) => id !== failedPayload.message_id,
                ),
              ),
              playback: {
                messageId: failedPayload.message_id,
                state: "failed",
                error: failedPayload.error ?? "角色语音合成失败",
              },
            },
          });
        }
        break;
      }
      case "voice.mobile_tts_end": {
        const payload = event.payload as { message_id?: string };
        if (payload.message_id) {
          set({
            voice: {
              ...get().voice,
              playback: {
                messageId: payload.message_id,
                state: "playing",
                error: null,
              },
            },
          });
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
        if (Array.isArray(payload.active_tasks)) {
          activeTask = payload.active_tasks.find((t) => t.conversation_id === convId) ?? null;
        } else if (payload.active_task?.conversation_id === convId) {
          activeTask = payload.active_task;
        } else if (payload.busy === false && payload.conversation_id === convId) {
          activeTask = null;
        }
        set({ activeTask });
        break;
      }
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
    approvals: [],
    resolvedApprovals: [],
    pair: null,
    activeTask: null,
    streamId: null,
    lastSequence: 0,
    bootstrapped: false,
    powerStatus: null,
    voice: {
      capture: { state: "idle", sessionId: null, error: null },
      transcript: null,
      playback: { messageId: null, state: "idle", error: null },
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
        if (connection === "connected" && getStoredToken()) {
          void bootstrap().catch(reportBootstrapFailure);
        }
      });
      client.onEvent(handleEvent);
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
        pair: result.pair,
        activeTask: result.active_task,
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
      await client.request("chat.submit", {
        conversation_id: conversationId,
        target: "assistant",
        mode,
        text,
      });
    },

    async submitMessage(text) {
      const conversationId = get().activeConversationId;
      if (!conversationId) throw new Error("尚未打开会话");
      // 角色消息任何模式都可发送；不带 mode 参数，避免顺带切换会话模式。
      await client.request("chat.submit", {
        conversation_id: conversationId,
        target: "character",
        text,
      });
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

    disconnect() {
      bootstrapGeneration += 1;
      openConversationGeneration += 1;
      bootstrapping = null;
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
        streamId: null,
        lastSequence: 0,
        bootstrapped: false,
        powerStatus: null,
        voice: {
          capture: { state: "idle", sessionId: null, error: null },
          transcript: null,
          playback: { messageId: null, state: "idle", error: null },
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
      const voice = get().voice;
      set({
        voice: {
          ...voice,
          playback: { messageId, state: "stopping", error: null },
        },
      });
      try {
        await client.request("voice.mobile_tts_stop", { message_id: messageId });
        set({
          voice: {
            ...get().voice,
            playback: { messageId: null, state: "idle", error: null },
          },
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        set({
          voice: {
            ...get().voice,
            playback: { messageId, state: "idle", error: message },
          },
        });
        throw error;
      }
    },

    finishVoicePlayback(messageId) {
      const voice = get().voice;
      if (voice.playback.messageId !== messageId) return;
      const nextChunks = { ...voice.ttsChunks };
      delete nextChunks[messageId];
      set({
        voice: {
          ...voice,
          playback: { messageId: null, state: "idle", error: null },
          ttsChunks: nextChunks,
        },
      });
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
