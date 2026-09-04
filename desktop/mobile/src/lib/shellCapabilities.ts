/**
 * V0.3.7 壳能力探测（冻结文档 §9.1「能力探测先行」）。
 *
 * 移动端前端同时运行在三种环境：
 * - pwa：普通浏览器 / 已安装的 PWA，无任何壳专有能力；
 * - android_shell：Tauri 2 Android 壳（desktop/src-tauri/gen/android），具备本地通知、
 *   前台服务（常驻「保持连接中」）等壳能力；
 * - desktop_shell：Tauri 2 桌面壳（Windows）加载移动产物的情形，视为壳但不承诺 Android 行为。
 *
 * 判定依据：
 * - Tauri 2 运行时在 window 上注入 `__TAURI_INTERNALS__`；`withGlobalTauri` 开启时另有
 *   `__TAURI__` 全局 API（桌面端 main.tsx 用同一判定）。纯浏览器两者皆无；
 * - Android 判定用 navigator.userAgent（壳 WebView 的 UA 含 "Android"）。这是平台能力
 *   判定，不是对用户文字/意图的猜测（Let It Go 边界不受影响）。
 *
 * 通知能力（冻结 §9.2 定案 tauri-plugin-notification）：JS 包已在接线阶段随壳依赖引入
 * （@tauri-apps/plugin-notification + @tauri-apps/api，静态 import 保证打进壳产物）；
 * 本模块以运行时探测真实可用性——插件未注册（如 PWA、桌面壳未注册移动插件）或调用失败
 * 时如实返回不可用并保留原始错误日志，全程不抛错、不伪造可用。
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
  if (typeof window === "undefined") return "pwa";
  const isTauriRuntime = "__TAURI_INTERNALS__" in window || "__TAURI__" in window;
  if (!isTauriRuntime) return "pwa";
  return /android/i.test(window.navigator.userAgent) ? "android_shell" : "desktop_shell";
}

export function isAndroidShell(): boolean {
  return detectShellEnvironment() === "android_shell";
}

/** React hook：订阅式壳判定（竞态安全）；非 React 消费方用同步函数。 */
export function useShellEnvironment(): ShellEnvironment {
  const environment: ShellEnvironment = useSyncExternalStore(
    onShellEnvironmentChange,
    detectShellEnvironment,
    (): ShellEnvironment => "pwa",
  );
  // 真机竞态诊断探针：记录 hook 每次提交的快照值与时刻（仅诊断，不参与逻辑）。
  if (typeof window !== "undefined") {
    const probe = window as unknown as { __phmShellSnapshots?: string[] };
    const snapshots: string[] = probe.__phmShellSnapshots ?? [];
    const entry: string = `${Date.now()}:${environment}`;
    if (snapshots[snapshots.length - 1] !== entry) {
      snapshots.push(entry);
    }
    probe.__phmShellSnapshots = snapshots;
  }
  return environment;
}

/**
 * 壳注入的延迟容限（毫秒）：Android WebView 上 `__TAURI_INTERNALS__` 由
 * document-start 脚本注入，与首个 JS bundle 的执行存在可观测竞态——
 * 首帧 render 时 internals 可能尚未就位（真机 00:58 实证：PairPage 首判
 * pwa、百毫秒后判定为壳）。渲染期消费判定必须经 useShellEnvironment
 * 订阅重估，不得在 render 一次性求值后固化。
 */
const SHELL_INJECTION_GRACE_MS = 2500;

const shellListeners = new Set<(environment: ShellEnvironment) => void>();
let shellPollActive = false;

function notifyShellListeners(): void {
  const environment = detectShellEnvironment();
  shellListeners.forEach((listener) => listener(environment));
}

function ensureShellWatch(): void {
  if (shellPollActive || typeof window === "undefined") return;
  shellPollActive = true;
  const startedAt = Date.now();
  const poll = (): void => {
    notifyShellListeners();
    if (detectShellEnvironment() !== "pwa" || Date.now() - startedAt > SHELL_INJECTION_GRACE_MS) {
      // 注入已就位或宽限期过：本轮轮询停止。环境仍为 pwa 时，后续新订阅者
      // （如另一页面挂载）会重启一轮——不做常驻探针，也不永久封死。
      if (detectShellEnvironment() === "pwa") shellPollActive = false;
      return;
    }
    window.setTimeout(poll, 100);
  };
  window.setTimeout(poll, 50);
}

/**
 * 订阅壳环境变化（注入竞态下首帧可能判为 pwa，internals 就位后回调壳值）。
 * 返回退订函数。React 侧经 useSyncExternalStore 消费；轮询在壳值出现或
 * 宽限期耗尽后自动停止，环境仍为 pwa 时新订阅者会重启一轮。
 */
export function onShellEnvironmentChange(
  listener: (environment: ShellEnvironment) => void,
): () => void {
  shellListeners.add(listener);
  ensureShellWatch();
  return () => {
    shellListeners.delete(listener);
  };
}

/**
 * 测试后门：复位壳环境轮询状态（PWA→壳转变场景需从干净轮询出发重演，
 * 与 setNotificationModuleLoader 同级的测试注入点）。生产代码不得调用。
 */
export function resetShellEnvironmentWatch(): void {
  shellPollActive = false;
}

/** 通知插件 JS API 的最小形状（@tauri-apps/plugin-notification v2 核心函数）。 */
export interface NotificationModuleLike {
  isPermissionGranted: () => Promise<boolean>;
  requestPermission: () => Promise<boolean>;
  sendNotification: (options: NotificationSendOptions) => void;
  /** Android 8+ 通知必须先建渠道：channelId 指向不存在的渠道时通知不投递。 */
  createChannel: (channel: NotificationChannelLike) => Promise<void> | void;
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

type NotificationModuleLoader = () => Promise<unknown> | unknown;

function loadNotificationModule(): unknown {
  // 静态导入的插件模块：打包期已解析（不再走运行时裸说明符 import），
  // jsdom/无插件环境由调用方按探测结果如实降级。
  return {
    isPermissionGranted,
    requestPermission,
    sendNotification,
    createChannel,
  };
}

let notificationModuleLoader: NotificationModuleLoader = loadNotificationModule;

/** 已就绪的模块缓存（loader 可能是异步的，首次加载后缓存 resolve 值）。 */
let notificationModuleReady: Promise<unknown> | null = null;

/**
 * 测试注入点：替换通知插件加载器，传 null 恢复默认静态加载。
 * 生产代码不得调用；真实能力始终以运行时探测结果为准。
 */
export function setNotificationModuleLoader(
  loader: NotificationModuleLoader | null,
): void {
  notificationModuleLoader = loader ?? loadNotificationModule;
  notificationModuleReady = null;
}

function isNotificationModule(value: unknown): value is NotificationModuleLike {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.isPermissionGranted === "function" &&
    typeof candidate.requestPermission === "function" &&
    typeof candidate.sendNotification === "function" &&
    typeof candidate.createChannel === "function"
  );
}

function loadNotificationModuleOnce(): Promise<unknown> {
  if (notificationModuleReady === null) {
    notificationModuleReady = Promise.resolve(notificationModuleLoader());
  }
  return notificationModuleReady;
}

/**
 * 探测当前环境能否发起本地通知。绝不抛错：
 * - 非 Tauri 环境（PWA）→ not_shell，不触碰插件加载；
 * - 壳内插件缺失 / 调用失败 → plugin_unavailable，原始错误进 console 保留证据；
 * - 插件可调用 → ready + 权限布尔（false 表示尚未授权或已被拒，由 UI 引导）。
 */
export async function probeNotificationCapability(): Promise<NotificationCapability> {
  const environment = detectShellEnvironment();
  if (environment === "pwa") {
    return { kind: "unavailable", reason: "not_shell" };
  }
  let moduleValue: unknown;
  try {
    moduleValue = await loadNotificationModuleOnce();
  } catch (error) {
    console.warn("[shellCapabilities] 通知插件加载失败，按不可用处理：", error);
    return { kind: "unavailable", reason: "plugin_unavailable" };
  }
  if (!isNotificationModule(moduleValue)) {
    // null/undefined 表示插件包本身不存在；对象存在但缺 API 才值得保留诊断日志。
    if (moduleValue !== null && moduleValue !== undefined) {
      console.warn(
        "[shellCapabilities] 通知插件已加载但缺少约定 API（isPermissionGranted/requestPermission/sendNotification），按不可用处理。",
      );
    }
    return { kind: "unavailable", reason: "plugin_unavailable" };
  }
  try {
    const granted = await moduleValue.isPermissionGranted();
    return { kind: "ready", permission_granted: granted === true };
  } catch (error) {
    console.warn("[shellCapabilities] 通知权限查询失败，按不可用处理：", error);
    return { kind: "unavailable", reason: "plugin_unavailable" };
  }
}

/**
 * 发起系统通知权限申请（Android 13+ 的 POST_NOTIFICATIONS 运行时弹窗）。
 * 仅在探测结果为 ready 的界面调用；环境不具备或插件缺失时如实抛错，由调用方呈现原文。
 * 申请返回 false 表示用户拒绝或系统策略未放行——如实返回 false，不重试不伪装成功。
 */
export async function requestNotificationPermission(): Promise<boolean> {
  const moduleValue: unknown = await loadNotificationModuleOnce();
  if (!isNotificationModule(moduleValue)) {
    throw new Error("当前环境未加载通知能力，无法申请系统通知权限");
  }
  return (await moduleValue.requestPermission()) === true;
}

/**
 * 发送一条本地通知。插件模块加载是异步的就绪等待（loader 可能异步），插件缺失或
 * 调用失败如实进 console 并跳过该条——不抛出到调用方（引擎高频调用点不应被单条
 * 失败打断），也绝不改写为成功；错误原文完整保留在日志里（Let It Fail）。
 */
export function sendLocalNotification(options: NotificationSendOptions): void {
  void loadNotificationModuleOnce()
    .then((moduleValue) => {
      if (!isNotificationModule(moduleValue)) {
        throw new Error("当前环境未加载通知能力，无法发送本地通知");
      }
      moduleValue.sendNotification(options);
    })
    .catch((error: unknown) => {
      console.warn("[shellCapabilities] 本地通知发送失败，跳过该条：", error);
    });
}

/**
 * 幂等创建通知渠道（Android 8+ 前置：channelId 指向不存在的渠道时通知不投递）。
 * 失败如实进 console（单条渠道失败不阻断其余），不抛出到调用方。
 */
export function ensureNotificationChannels(channels: NotificationChannelLike[]): void {
  void loadNotificationModuleOnce()
    .then(async (moduleValue) => {
      if (!isNotificationModule(moduleValue)) {
        throw new Error("当前环境未加载通知能力，无法创建通知渠道");
      }
      for (const channel of channels) {
        try {
          await moduleValue.createChannel(channel);
        } catch (error) {
          console.warn(
            `[shellCapabilities] 通知渠道创建失败 ${channel.id}：`,
            error,
          );
        }
      }
    })
    .catch((error: unknown) => {
      console.warn("[shellCapabilities] 通知渠道初始化失败：", error);
    });
}
