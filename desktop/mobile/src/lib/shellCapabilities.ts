/**
 * 运行环境与壳能力探测。移动端前端运行在三种环境：
 * - pwa：普通浏览器或已安装的 PWA，没有壳专有能力；
 * - android_shell：Tauri 2 Android 壳，具备本地通知与前台服务（常驻「保持连接中」）；
 * - desktop_shell：Tauri 2 桌面壳加载移动产物，视为壳但不承诺 Android 行为。
 *
 * Tauri 2 运行时在 window 上注入 `__TAURI_INTERNALS__`（开启 withGlobalTauri 时另有 `__TAURI__`），
 * 纯浏览器两者皆无；Android 由 WebView 的 userAgent 判定。
 *
 * 通知使用 @tauri-apps/plugin-notification（静态 import 打进壳产物）。插件未注册
 * （PWA、桌面壳）或调用失败时返回不可用，原始错误进日志。
 */

import { useSyncExternalStore } from "react";
import {
  createChannel,
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
    __TAURI__?: unknown;
  }
}

export type ShellEnvironment = "android_shell" | "desktop_shell" | "pwa";

export function detectShellEnvironment(): ShellEnvironment {
  const isTauriRuntime = "__TAURI_INTERNALS__" in window || "__TAURI__" in window;
  if (!isTauriRuntime) return "pwa";
  return /android/i.test(window.navigator.userAgent) ? "android_shell" : "desktop_shell";
}

/** 订阅式壳判定，壳注入晚于首帧时随后更新；非 React 消费方用 detectShellEnvironment。 */
export function useShellEnvironment(): ShellEnvironment {
  return useSyncExternalStore(onShellEnvironmentChange, detectShellEnvironment, () => "pwa");
}

/**
 * 壳注入的等待上限（毫秒）。Android WebView 的 `__TAURI_INTERNALS__` 由 document-start
 * 脚本注入，首帧渲染时可能还没就位，百毫秒后才出现；渲染期的判定因此经
 * useShellEnvironment 订阅更新。
 */
const SHELL_INJECTION_GRACE_MS = 2500;

const shellListeners = new Set<(environment: ShellEnvironment) => void>();
let shellPollActive = false;
let shellPollTimer: number | null = null;

function notifyShellListeners(): void {
  const environment = detectShellEnvironment();
  shellListeners.forEach((listener) => listener(environment));
}

function ensureShellWatch(): void {
  if (shellPollActive) return;
  shellPollActive = true;
  const startedAt = Date.now();
  const poll = (): void => {
    shellPollTimer = null;
    if (shellListeners.size === 0) {
      shellPollActive = false;
      return;
    }
    notifyShellListeners();
    if (detectShellEnvironment() !== "pwa" || Date.now() - startedAt > SHELL_INJECTION_GRACE_MS) {
      // 注入已就位或等待超时，本轮轮询停止；环境仍为 pwa 时，新订阅者（如另一页面挂载）会重启一轮。
      if (detectShellEnvironment() === "pwa") shellPollActive = false;
      return;
    }
    shellPollTimer = window.setTimeout(poll, 100);
  };
  shellPollTimer = window.setTimeout(poll, 50);
}

/**
 * 订阅壳环境变化：首帧可能判为 pwa，壳注入就位后回调壳值。返回退订函数。
 * 轮询在壳值出现或等待超时后停止，环境仍为 pwa 时新订阅者会重启一轮。
 */
export function onShellEnvironmentChange(
  listener: (environment: ShellEnvironment) => void,
): () => void {
  shellListeners.add(listener);
  ensureShellWatch();
  return () => {
    shellListeners.delete(listener);
    if (shellListeners.size === 0) resetShellEnvironmentWatch();
  };
}

/** 停止壳环境轮询；最后一个订阅者退订时调用。 */
function resetShellEnvironmentWatch(): void {
  shellPollActive = false;
  if (shellPollTimer !== null) {
    window.clearTimeout(shellPollTimer);
    shellPollTimer = null;
  }
}

/** 发送本地通知的最小参数（@tauri-apps/plugin-notification v2 Options 子集）。 */
export interface NotificationSendOptions {
  title: string;
  body: string;
  channelId?: string;
}

/** 通知渠道的最小形状（Importance 数值与插件枚举一致：0-4）。 */
export interface NotificationChannelLike {
  id: string;
  name: string;
  description?: string;
  importance: number;
  vibration?: boolean;
  lights?: boolean;
}

export type NotificationCapability =
  | { kind: "unavailable"; reason: "not_shell" }
  | { kind: "unavailable"; reason: "plugin_unavailable" }
  | { kind: "ready"; permission_granted: boolean };

/**
 * 探测当前环境能否发起本地通知，结果写在返回值里：
 * - PWA 返回 not_shell，不调用插件；
 * - 壳内插件未注册或调用失败返回 plugin_unavailable，原始错误进日志；
 * - 插件可调用返回 ready 与授权状态（false 表示尚未授权或已被拒绝）。
 */
export async function probeNotificationCapability(): Promise<NotificationCapability> {
  if (detectShellEnvironment() === "pwa") {
    return { kind: "unavailable", reason: "not_shell" };
  }
  try {
    return { kind: "ready", permission_granted: await isPermissionGranted() };
  } catch (error) {
    console.warn("[shellCapabilities] 通知权限查询失败，按不可用处理：", error);
    return { kind: "unavailable", reason: "plugin_unavailable" };
  }
}

/**
 * 申请系统通知权限（Android 13+ 的 POST_NOTIFICATIONS 运行时弹窗），只在探测结果为 ready 时调用。
 * 插件返回 granted 时为 true；denied（拒绝）与 default（未作选择）为 false，调用失败抛出原始错误。
 */
export async function requestNotificationPermission(): Promise<boolean> {
  return (await requestPermission()) === "granted";
}

/**
 * 发送一条本地通知。插件调用失败时记日志并跳过这一条，
 * 通知引擎的事件处理不因单条通知失败而中断。
 */
export function sendLocalNotification(options: NotificationSendOptions): void {
  try {
    sendNotification(options);
  } catch (error) {
    console.warn("[shellCapabilities] 本地通知发送失败，跳过该条：", error);
  }
}

/**
 * 幂等创建通知渠道（Android 8+ 上 channelId 指向不存在的渠道时通知不投递）。
 * 单个渠道创建失败记日志，不影响其余渠道。
 */
export function ensureNotificationChannels(channels: NotificationChannelLike[]): void {
  void (async () => {
    for (const channel of channels) {
      try {
        await createChannel(channel);
      } catch (error) {
        console.warn(`[shellCapabilities] 通知渠道创建失败 ${channel.id}：`, error);
      }
    }
  })();
}
