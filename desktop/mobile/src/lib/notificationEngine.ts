/**
 * V0.3.7 L13 本地通知规则引擎（冻结契约 §2.3）。
 *
 * 事件源 = 既有 WS 事件流（mobileWsClient.onEvent 多播，不经 store）：
 * - 任务完成 = turn.status_changed（turn.target=character，status 进入终态）；
 * - 委派结果 = turn.status_changed（turn.target=assistant，status 进入终态）；
 * - 审批请求 = approval.requested（payload 自带 operation.summary / reason 摘要）。
 * message.finalized 不带角色与文本，无法区分任务完成/委派，不作为触发源。
 *
 * 规则全部在壳内本地处理（§2.3：通知只承载状态摘要，不是事件来源）：
 * - 仅应用在后台（document.visibilityState=hidden）时发送，前台不打扰；
 * - 发送前现读 localStorage 偏好（phm.notificationPreferences.v1），enabled=false
 *   或静默档跳过；偏好读取失败按默认值，不阻塞通知链路；
 * - 通知权限未授权时不发送（NotificationPreferences UI 已如实呈现授权状态）；
 * - 点击通知进壳由「回前台时导航到最后一条通知的会话」近似——官方插件无
 *   点击回调，回前台后按既有 sequence 对齐机制（bootstrap）自动补增量，
 *   不合成离线期间的事件。
 *
 * Let It Fail 边界：插件调用失败保留原始错误日志并跳过该条通知，不改写为成功，
 * 不重试不伪造送达。
 */

import { mobileWsClient, useMobileStore } from "./mobileStore";
import type { WireEvent } from "./wsClient";
import {
  probeNotificationCapability,
  sendLocalNotification,
  isAndroidShell,
} from "./shellCapabilities";
import {
  loadNotificationPreferences,
  type NotificationImportance,
  type NotificationTypeKey,
} from "../components/NotificationPreferences";
import { navigate, parseHash } from "./router";

const NOTIFICATION_CHANNEL_IDS: Record<NotificationTypeKey, string> = {
  taskCompleted: "phm_task_completed",
  delegationResult: "phm_delegation_result",
  approvalRequested: "phm_approval_requested",
};

interface TurnPayload {
  turn?: {
    conversation_id?: string;
    target?: string;
    status?: string;
  };
}

interface ApprovalRequestedPayload {
  approval_id?: string;
  conversation_id?: string;
  operation?: { summary?: string };
  reason?: string;
}

const TERMINAL_TURN_STATUSES = new Set(["completed", "failed", "cancelled"]);

/** 发送决策：偏好档位 → 是否发送。silent 档 = 仅通知栏展示，无提醒，本引擎不发。 */
function shouldNotify(importance: NotificationImportance): boolean {
  return importance === "high" || importance === "default";
}

interface PendingNotification {
  type: NotificationTypeKey;
  title: string;
  body: string;
  conversationId: string | null;
}

let started = false;
let unsubscribeEvents: (() => void) | null = null;
let visibilityListener: (() => void) | null = null;
let permissionGranted = false;
let engineReady = false;
let lastNotifiedConversationId: string | null = null;

function conversationTitleFallback(conversationId: string | null): string {
  if (!conversationId) return "新聊天";
  return "新聊天";
}

/** 测试注入点：会话标题解析（生产从 store 读取），传 null 恢复兜底。 */
let titleResolver: ((conversationId: string) => string) | null = null;

export function setNotificationTitleResolver(
  resolver: ((conversationId: string) => string) | null,
): void {
  titleResolver = resolver;
}

function resolveTitle(conversationId: string | null): string {
  if (!conversationId) return "新聊天";
  return titleResolver?.(conversationId) ?? conversationTitleFallback(conversationId);
}

function handleTurnStatusChanged(payload: unknown): PendingNotification | null {
  const turn = (payload as TurnPayload | undefined)?.turn;
  if (!turn || typeof turn.conversation_id !== "string") return null;
  if (typeof turn.status !== "string" || !TERMINAL_TURN_STATUSES.has(turn.status)) {
    return null;
  }
  const isDelegation = turn.target === "assistant";
  const type: NotificationTypeKey = isDelegation ? "delegationResult" : "taskCompleted";
  const statusText =
    turn.status === "completed" ? "已完成" : turn.status === "failed" ? "失败" : "已取消";
  const title = isDelegation ? "委派结果" : "任务完成";
  return {
    type,
    title,
    body: `「${resolveTitle(turn.conversation_id)}」${statusText}`,
    conversationId: turn.conversation_id,
  };
}

function handleApprovalRequested(payload: unknown): PendingNotification | null {
  const data = (payload ?? {}) as ApprovalRequestedPayload;
  if (typeof data.approval_id !== "string") return null;
  const conversationId =
    typeof data.conversation_id === "string" ? data.conversation_id : null;
  const summary =
    typeof data.operation?.summary === "string" && data.operation.summary.length > 0
      ? data.operation.summary
      : typeof data.reason === "string"
        ? data.reason
        : "需要你在手机上批准或拒绝";
  return {
    type: "approvalRequested",
    title: "审批请求",
    body: `「${resolveTitle(conversationId)}」${summary}`,
    conversationId,
  };
}

function dispatchNotification(pending: PendingNotification): void {
  if (!engineReady || !permissionGranted) return;
  if (document.visibilityState !== "hidden") return;
  const preferences = loadNotificationPreferences();
  const preference = preferences[pending.type];
  if (!preference.enabled || !shouldNotify(preference.importance)) return;
  sendLocalNotification({
    title: pending.title,
    body: pending.body,
    channelId: NOTIFICATION_CHANNEL_IDS[pending.type],
  });
  if (pending.conversationId) {
    lastNotifiedConversationId = pending.conversationId;
  }
}

function handleEngineEvent(event: WireEvent): void {
  if (event.kind !== "event") return;
  let pending: PendingNotification | null = null;
  if (event.event === "turn.status_changed") {
    pending = handleTurnStatusChanged(event.payload);
  } else if (event.event === "approval.requested") {
    pending = handleApprovalRequested(event.payload);
  }
  if (pending) dispatchNotification(pending);
}

function handleVisibilityChange(): void {
  if (document.visibilityState !== "visible") return;
  // 回前台：近似「点击通知进入对应会话」。仅在列表页时跳转——
  // 用户正停在别的会话时不打断；路由守卫会在未配对时接管。
  if (!lastNotifiedConversationId) return;
  if (parseHash(window.location.hash).name !== "list") return;
  const target = lastNotifiedConversationId;
  lastNotifiedConversationId = null;
  navigate({ name: "chat", conversationId: target });
}

/**
 * 幂等启动通知引擎。非 Android 壳（PWA / 桌面壳）不启动——探测先行，
 * 不伪造可用。返回 dispose 供测试与卸载清理。
 */
export function startNotificationEngine(): () => void {
  if (started) return () => undefined;
  if (!isAndroidShell()) return () => undefined;
  started = true;

  // 会话标题来自 store 快照（与列表页同源兜底）；事件 payload 不带标题，不合成。
  // 测试可先 setNotificationTitleResolver 注入替身——注入优先，不覆盖。
  if (titleResolver === null) {
    titleResolver = (conversationId: string): string => {
      const record = useMobileStore.getState().conversationsById[conversationId];
      return record?.title && record.title.length > 0 ? record.title : "新聊天";
    };
  }

  void probeNotificationCapability().then((capability) => {
    if (capability.kind !== "ready") {
      // not_shell / plugin_unavailable：探测函数已保留原始错误日志，这里如实停用。
      return;
    }
    permissionGranted = capability.permission_granted;
    engineReady = true;
  });

  unsubscribeEvents = mobileWsClient.onEvent(handleEngineEvent);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  visibilityListener = () => document.removeEventListener("visibilitychange", handleVisibilityChange);

  return () => {
    started = false;
    engineReady = false;
    permissionGranted = false;
    lastNotifiedConversationId = null;
    unsubscribeEvents?.();
    unsubscribeEvents = null;
    visibilityListener?.();
    visibilityListener = null;
    titleResolver = null;
  };
}
