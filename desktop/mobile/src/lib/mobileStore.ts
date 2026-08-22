import { create } from "zustand";
import type {
  ActiveTask,
  ConversationMode,
  ConversationOpenResult,
  ConversationRecord,
  DesktopSnapshot,
  Message,
  PairRecord,
  PendingApproval,
  ProjectRecord,
  ToolRun,
} from "@shared/contracts/protocol";
import type { MobileConnectionState, WireEvent } from "./wsClient";
import {
  clearCredentials,
  getStoredDeviceName,
  getStoredToken,
  MobileWsClient,
  saveCredentials,
} from "./wsClient";

/**
 * V0.3.3 手机端业务 store。
 *
 * 骨架范围：连接状态、bootstrap 水合、会话索引、当前会话消息装载、
 * 审批列表与决议、委派提交。消息流式事件（message.delta 等）的细粒度
 * 渲染由 W5 填充；骨架只对事件做 sequence 去重与缺口检测，缺口发生时
 * 如实重新 bootstrap，不丢弃也不伪造中间状态。
 */

export interface MobileState {
  connection: MobileConnectionState;
  deviceName: string | null;
  projects: ProjectRecord[];
  conversationsById: Record<string, ConversationRecord>;
  activeConversationId: string | null;
  messages: Message[];
  toolRuns: ToolRun[];
  approvals: PendingApproval[];
  /** V0.3.4：当前配对（委派卡「来自 <角色名> 的委派」数据源）。 */
  pair: PairRecord | null;
  /** V0.3.4：当前活动任务（委派卡运行状态与 delegation_id 对齐）。 */
  activeTask: ActiveTask | null;
  lastSequence: number;
  bootstrapped: boolean;

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
): void {
  set({
    projects: snapshot.projects,
    conversationsById: indexConversations(snapshot.projects),
    messages: snapshot.messages,
    toolRuns: snapshot.tool_runs,
    approvals: snapshot.approvals,
    pair: snapshot.pair,
    activeTask: snapshot.active_task,
    lastSequence: snapshot.sequence,
    bootstrapped: true,
  });
}

export const useMobileStore = create<MobileState>((set, get) => {
  let wired = false;
  let bootstrapping: Promise<void> | null = null;

  /** connect() 只发起握手；pair 等调用必须等 connected 后才能发请求。 */
  const waitForConnected = (): Promise<void> => {
    if (client.getState() === "connected") return Promise.resolve();
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

  const bootstrap = async (): Promise<void> => {
    if (bootstrapping) return bootstrapping;
    bootstrapping = (async () => {
      try {
        const snapshot = await client.request<DesktopSnapshot>("app.bootstrap");
        applySnapshot(set, snapshot);
      } finally {
        bootstrapping = null;
      }
    })();
    return bootstrapping;
  };

  const handleEvent = (event: WireEvent): void => {
    const state = get();
    if (typeof event.sequence === "number") {
      if (event.sequence <= state.lastSequence) return;
      if (event.sequence > state.lastSequence + 1 && state.bootstrapped) {
        // 事件缺口：不猜中间态，如实重新水合。
        void bootstrap();
        return;
      }
      set({ lastSequence: event.sequence });
    }
    switch (event.event) {
      case "state.snapshot": {
        const payload = event.payload as unknown as DesktopSnapshot;
        applySnapshot(set, payload);
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
        const approvalId = (event.payload as { approval_id?: string }).approval_id;
        if (approvalId) {
          set({ approvals: get().approvals.filter((item) => item.approval_id !== approvalId) });
        }
        break;
      }
      // TODO(W5)：message.created/delta/finalized、tool_run.upserted 等
      // 流式事件的细粒度合并，在聊天页实现时补齐；骨架依赖缺口重 bootstrap
      // 与 conversation.open 重新装载保证一致性。
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
    pair: null,
    activeTask: null,
    lastSequence: 0,
    bootstrapped: false,

    start() {
      if (wired) return;
      wired = true;
      client.onStateChange((connection) => {
        set({ connection });
        if (connection === "connected" && getStoredToken()) {
          void bootstrap();
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
      // 页面刷新直接落在聊天页时，装载可能先于 WS 握手完成；
      // 与 pairDevice() 同模式等待连接就绪，避免 mount 竞态报「WebSocket 未连接」。
      client.connect();
      await waitForConnected();
      const result = await client.request<ConversationOpenResult>("conversation.open", {
        conversation_id: conversationId,
        view_id: mobileViewId,
      });
      set({
        activeConversationId: conversationId,
        messages: result.messages,
        toolRuns: result.tool_runs,
        pair: result.pair,
        activeTask: result.active_task,
      });
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

    async resolveApproval(approvalId, decision) {
      await client.request("approval.resolve", { approval_id: approvalId, decision });
    },

    disconnect() {
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
        pair: null,
        activeTask: null,
        lastSequence: 0,
        bootstrapped: false,
      });
    },
  };
});

/** 测试专用：暴露底层 client 以便注入 FakeWebSocket 后断言帧。 */
export const mobileWsClient = client;
