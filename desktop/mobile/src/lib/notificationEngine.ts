/**
 * Android 壳内的本地通知规则引擎，直接订阅 mobileWsClient 的事件流：
 * - 任务完成：turn.status_changed，turn.target=character 且进入终态；
 * - 委派结果：turn.status_changed，turn.target=assistant 且进入终态；
 * - 审批请求：approval.requested，正文取 operation.summary 或申请理由。
 *
 * 只在应用处于后台时发送；发送前读取 localStorage 的通知偏好，关闭的类型跳过；
 * 未授权通知权限时不发送。插件没有点击回调，回到前台时若停在列表页，
 * 就打开最后一条通知所属的聊天；回前台的重新同步补齐离线期间的状态。
 * 插件调用失败记日志并跳过该条通知。
 */

import type { PendingApproval, Turn } from "@shared/contracts/protocol";
import { mobileWsClient, useMobileStore } from "./mobileStore";
import type { WireEvent } from "./wsClient";
import {
  ensureNotificationChannels,
  onShellEnvironmentChange,
  probeNotificationCapability,
  sendLocalNotification,
  detectShellEnvironment,
} from "./shellCapabilities";
import {
  loadNotificationPreferences,
  type NotificationImportance,
  type NotificationTypeKey,
} from "../components/NotificationPreferences";
import { navigate, parseHash } from "./router";

/** 渠道 importance 数值与插件枚举一致：Low=2 / Default=3 / High=4。 */
const NOTIFICATION_CHANNEL_IMPORTANCE: Record<NotificationImportance, number> = {
  silent: 2,
  default: 3,
  high: 4,
};

const NOTIFICATION_CHANNEL_IDS: Record<NotificationTypeKey, string> = {
  taskCompleted: "phm_task_completed",
  delegationResult: "phm_delegation_result",
  approvalRequested: "phm_approval_requested",
};

const TERMINAL_TURN_STATUS_TEXT: Partial<Record<Turn["status"], string>> = {
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

function notificationChannelId(
  type: NotificationTypeKey,
  importance: NotificationImportance,
): string {
  return NOTIFICATION_CHANNEL_IDS[type] + "_" + importance;
}

function notificationChannelName(
  type: NotificationTypeKey,
  importance: NotificationImportance,
): string {
  let name = "任务完成";
  if (type === "approvalRequested") {
    name = "审批请求";
  } else if (type === "delegationResult") {
    name = "委派结果";
  }
  if (importance === "silent") return name + "（静默）";
  if (importance === "high") return name + "（高优先级）";
  return name;
}

interface PendingNotification {
  type: NotificationTypeKey;
  title: string;
  body: string;
  conversationId: string;
}

let started = false;
let unsubscribeShell: (() => void) | null = null;
let unsubscribeEvents: (() => void) | null = null;
let permissionGranted = false;
let engineReady = false;
let lastNotifiedConversationId: string | null = null;
let channelsEnsured = false;

/** 会话标题取自 store 的会话记录，与列表页一样把空标题显示为「新聊天」。 */
function storeConversationTitle(conversationId: string): string {
  return useMobileStore.getState().conversationsById[conversationId]?.title || "新聊天";
}

let titleResolver: (conversationId: string) => string = storeConversationTitle;

/** 替换会话标题解析（测试用），传 null 恢复读取 store。 */
export function setNotificationTitleResolver(
  resolver: ((conversationId: string) => string) | null,
): void {
  titleResolver = resolver ?? storeConversationTitle;
}

function handleTurnStatusChanged({ turn }: { turn: Turn }): PendingNotification | null {
  const statusText = TERMINAL_TURN_STATUS_TEXT[turn.status];
  if (!statusText) return null;
  const isDelegation = turn.target === "assistant";
  return {
    type: isDelegation ? "delegationResult" : "taskCompleted",
    title: isDelegation ? "委派结果" : "任务完成",
    body: `「${titleResolver(turn.conversation_id)}」${statusText}`,
    conversationId: turn.conversation_id,
  };
}

function handleApprovalRequested(approval: PendingApproval): PendingNotification {
  return {
    type: "approvalRequested",
    title: "审批请求",
    body: `「${titleResolver(approval.conversation_id)}」${approval.operation.summary || approval.reason}`,
    conversationId: approval.conversation_id,
  };
}

function dispatchNotification(pending: PendingNotification): void {
  if (!engineReady || !permissionGranted) return;
  if (document.visibilityState !== "hidden") return;
  const preference = loadNotificationPreferences()[pending.type];
  if (!preference.enabled) return;
  sendLocalNotification({
    title: pending.title,
    body: pending.body,
    channelId: notificationChannelId(pending.type, preference.importance),
  });
  lastNotifiedConversationId = pending.conversationId;
}

function handleEngineEvent(event: WireEvent): void {
  if (event.event === "turn.status_changed") {
    const pending = handleTurnStatusChanged(event.payload as unknown as { turn: Turn });
    if (pending) dispatchNotification(pending);
  } else if (event.event === "approval.requested") {
    dispatchNotification(handleApprovalRequested(event.payload as unknown as PendingApproval));
  }
}

function refreshPermissionCache(): void {
  void probeNotificationCapability().then((capability) => {
    if (capability.kind !== "ready") return;
    permissionGranted = capability.permission_granted;
    // 权限就绪后补建渠道（用户可能在设置页授权后首次回前台）。
    ensureChannels();
  });
}

function ensureChannels(): void {
  if (channelsEnsured) return;
  channelsEnsured = true;
  const importanceLevels: NotificationImportance[] = ["high", "default", "silent"];
  ensureNotificationChannels(
    (Object.keys(NOTIFICATION_CHANNEL_IDS) as NotificationTypeKey[]).flatMap((key) =>
      importanceLevels.map((importance) => ({
        id: notificationChannelId(key, importance),
        name: notificationChannelName(key, importance),
        description: "角色与助手的事件提醒",
        importance: NOTIFICATION_CHANNEL_IMPORTANCE[importance],
      })),
    ),
  );
}

function handleVisibilityChange(): void {
  if (document.visibilityState !== "visible") return;
  // 用户可能去系统设置授权后返回，回前台即刷新权限缓存。
  refreshPermissionCache();
  // 代替通知点击：只在列表页时打开最后一条通知的聊天，停在别的聊天时不打断。
  if (!lastNotifiedConversationId) return;
  if (parseHash(window.location.hash).name !== "list") return;
  const target = lastNotifiedConversationId;
  lastNotifiedConversationId = null;
  navigate({ name: "chat", conversationId: target });
}

/**
 * 幂等启动通知引擎，只在 Android 壳内激活。`__TAURI_INTERNALS__` 可能晚于本调用注入，
 * 因此订阅壳环境变化，环境变为 android_shell 时再激活。返回 dispose 供卸载清理。
 */
export function startNotificationEngine(): () => void {
  if (started) return () => undefined;
  started = true;

  const activate = (): void => {
    if (engineReady || detectShellEnvironment() !== "android_shell") return;
    engineReady = true;
    refreshPermissionCache();
    unsubscribeEvents = mobileWsClient.onEvent(handleEngineEvent);
  };

  unsubscribeShell = onShellEnvironmentChange((environment) => {
    if (environment === "android_shell") activate();
  });
  // 若启动时已是壳（注入先于本调用），立即激活。
  activate();

  document.addEventListener("visibilitychange", handleVisibilityChange);

  return () => {
    started = false;
    engineReady = false;
    permissionGranted = false;
    channelsEnsured = false;
    lastNotifiedConversationId = null;
    unsubscribeShell?.();
    unsubscribeShell = null;
    unsubscribeEvents?.();
    unsubscribeEvents = null;
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    titleResolver = storeConversationTitle;
  };
}
