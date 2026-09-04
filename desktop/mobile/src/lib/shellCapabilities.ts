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
 * 通知能力（冻结 §9.2 定案 tauri-plugin-notification）：JS 包由接线阶段随壳依赖引入，
 * 本模块以运行时动态 import 探测其真实可用性——未安装/未注册时如实返回不可用并保留
 * 原始错误日志，PWA 下探测直接返回 not_shell，全程不抛错、不伪造可用。
 */

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

/** 通知插件 JS API 的最小形状（@tauri-apps/plugin-notification v2 的两个核心函数）。 */
export interface NotificationModuleLike {
  isPermissionGranted: () => Promise<boolean>;
  requestPermission: () => Promise<boolean>;
}

export type NotificationCapability =
  | { kind: "unavailable"; reason: "not_shell" }
  | { kind: "unavailable"; reason: "plugin_unavailable" }
  | { kind: "ready"; permission_granted: boolean };

const NOTIFICATION_MODULE_ID = "@tauri-apps/plugin-notification";

type NotificationModuleLoader = () => Promise<unknown>;

async function loadNotificationModule(): Promise<unknown> {
  // 变量形式动态 import：包未安装时不阻塞构建与运行，失败由探测方如实记录。
  return import(/* @vite-ignore */ NOTIFICATION_MODULE_ID);
}

let notificationModuleLoader: NotificationModuleLoader = loadNotificationModule;

/**
 * 测试注入点：替换通知插件加载器，传 null 恢复默认动态加载。
 * 生产代码不得调用；真实能力始终以运行时探测结果为准。
 */
export function setNotificationModuleLoader(
  loader: NotificationModuleLoader | null,
): void {
  notificationModuleLoader = loader ?? loadNotificationModule;
}

function isNotificationModule(value: unknown): value is NotificationModuleLike {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.isPermissionGranted === "function" &&
    typeof candidate.requestPermission === "function"
  );
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
    moduleValue = await notificationModuleLoader();
  } catch (error) {
    console.warn("[shellCapabilities] 通知插件加载失败，按不可用处理：", error);
    return { kind: "unavailable", reason: "plugin_unavailable" };
  }
  if (!isNotificationModule(moduleValue)) {
    // null/undefined 表示插件包本身不存在；对象存在但缺 API 才值得保留诊断日志。
    if (moduleValue !== null && moduleValue !== undefined) {
      console.warn(
        "[shellCapabilities] 通知插件已加载但缺少约定 API（isPermissionGranted/requestPermission），按不可用处理。",
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
  const moduleValue: unknown = await notificationModuleLoader();
  if (!isNotificationModule(moduleValue)) {
    throw new Error("当前环境未加载通知能力，无法申请系统通知权限");
  }
  return (await moduleValue.requestPermission()) === true;
}
