import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  detectShellEnvironment,
  isAndroidShell,
  probeNotificationCapability,
  requestNotificationPermission,
  sendLocalNotification,
  setNotificationModuleLoader,
  type NotificationModuleLike,
} from "../shellCapabilities";

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const ANDROID_SHELL_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";

function stubUserAgent(userAgent: string): void {
  Object.defineProperty(window.navigator, "userAgent", {
    value: userAgent,
    configurable: true,
  });
}

function stubAndroidShellGlobals(): void {
  window.__TAURI_INTERNALS__ = {};
  stubUserAgent(ANDROID_SHELL_UA);
}

beforeEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubUserAgent(BROWSER_UA);
  setNotificationModuleLoader(null);
});

afterEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  setNotificationModuleLoader(null);
  vi.restoreAllMocks();
});

describe("detectShellEnvironment 环境探测", () => {
  it("无 Tauri 全局对象时识别为 PWA", () => {
    expect(detectShellEnvironment()).toBe("pwa");
    expect(isAndroidShell()).toBe(false);
  });

  it("Android UA 但无 Tauri 全局对象时仍是 PWA（安卓浏览器不享受壳能力）", () => {
    stubUserAgent(ANDROID_SHELL_UA);
    expect(detectShellEnvironment()).toBe("pwa");
    expect(isAndroidShell()).toBe(false);
  });

  it("__TAURI_INTERNALS__ + Android UA 识别为 Android 壳", () => {
    stubAndroidShellGlobals();
    expect(detectShellEnvironment()).toBe("android_shell");
    expect(isAndroidShell()).toBe(true);
  });

  it("__TAURI_INTERNALS__ + 桌面 UA 识别为桌面壳（非 Android）", () => {
    window.__TAURI_INTERNALS__ = {};
    expect(detectShellEnvironment()).toBe("desktop_shell");
    expect(isAndroidShell()).toBe(false);
  });

  it("withGlobalTauri 形态（仅 __TAURI__）同样识别为壳", () => {
    window.__TAURI__ = {};
    stubUserAgent(ANDROID_SHELL_UA);
    expect(detectShellEnvironment()).toBe("android_shell");
    expect(isAndroidShell()).toBe(true);
  });
});

describe("probeNotificationCapability 通知能力探测", () => {
  it("PWA 下直接返回 not_shell，不触碰插件加载", async () => {
    const loader = vi.fn(async () => null);
    setNotificationModuleLoader(loader);

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "unavailable",
      reason: "not_shell",
    });
    expect(loader).not.toHaveBeenCalled();
  });

  it("壳内插件不可用（默认加载器在 jsdom 中无 invoke 可调）时返回 plugin_unavailable 并保留原始错误日志", async () => {
    // 接线后现实：@tauri-apps/plugin-notification 已静态打包，模块可加载；
    // jsdom 里 window.__TAURI_INTERNALS__ 是空 stub、invoke 不存在，
    // isPermissionGranted 必然抛错，探测走「API 调用失败」路径如实降级。
    stubAndroidShellGlobals();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "unavailable",
      reason: "plugin_unavailable",
    });
    expect(warnSpy).toHaveBeenCalled();
  });

  it("壳内插件返回的模块缺少约定 API 时按不可用处理", async () => {
    stubAndroidShellGlobals();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    setNotificationModuleLoader(async () => ({ isPermissionGranted: async () => true }));

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "unavailable",
      reason: "plugin_unavailable",
    });
    expect(warnSpy).toHaveBeenCalled();
  });

  it("壳内插件可用且已授权时返回 ready", async () => {
    stubAndroidShellGlobals();
    setNotificationModuleLoader(
      async (): Promise<NotificationModuleLike> => ({
        isPermissionGranted: async () => true,
        requestPermission: async () => true,
        sendNotification: vi.fn(),
      }),
    );

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "ready",
      permission_granted: true,
    });
  });

  it("壳内插件可用但未授权时返回 ready + permission_granted=false", async () => {
    stubAndroidShellGlobals();
    setNotificationModuleLoader(
      async (): Promise<NotificationModuleLike> => ({
        isPermissionGranted: async () => false,
        requestPermission: async () => false,
        sendNotification: vi.fn(),
      }),
    );

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "ready",
      permission_granted: false,
    });
  });

  it("isPermissionGranted 调用失败时如实降级为不可用", async () => {
    stubAndroidShellGlobals();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    setNotificationModuleLoader(
      async (): Promise<NotificationModuleLike> => ({
        isPermissionGranted: async () => {
          throw new Error("plugin:notification|is_permission_granted failed");
        },
        requestPermission: async () => true,
        sendNotification: vi.fn(),
      }),
    );

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "unavailable",
      reason: "plugin_unavailable",
    });
    expect(warnSpy).toHaveBeenCalled();
  });
});

describe("requestNotificationPermission 权限申请", () => {
  it("插件可用时透传申请结果，false 如实返回", async () => {
    setNotificationModuleLoader(
      async (): Promise<NotificationModuleLike> => ({
        isPermissionGranted: async () => false,
        requestPermission: async () => false,
        sendNotification: vi.fn(),
      }),
    );
    await expect(requestNotificationPermission()).resolves.toBe(false);
  });

  it("插件不可用时如实抛错", async () => {
    setNotificationModuleLoader(async () => null);
    await expect(requestNotificationPermission()).rejects.toThrow(
      "当前环境未加载通知能力，无法申请系统通知权限",
    );
  });

  it("插件申请调用抛错时保留原始错误", async () => {
    setNotificationModuleLoader(
      async (): Promise<NotificationModuleLike> => ({
        isPermissionGranted: async () => false,
        requestPermission: async () => {
          throw new Error("plugin:notification|request_permission failed");
        },
        sendNotification: vi.fn(),
      }),
    );
    await expect(requestNotificationPermission()).rejects.toThrow(
      "plugin:notification|request_permission failed",
    );
  });
});

describe("sendLocalNotification 本地通知发送", () => {
  it("插件可用时透传通知参数", async () => {
    const sendNotification = vi.fn();
    setNotificationModuleLoader(async (): Promise<NotificationModuleLike> => ({
      isPermissionGranted: async () => true,
      requestPermission: async () => true,
      sendNotification,
    }));

    sendLocalNotification({ title: "审批请求", body: "写入文件", channelId: "phm_approval" });
    await vi.waitFor(() =>
      expect(sendNotification).toHaveBeenCalledWith({
        title: "审批请求",
        body: "写入文件",
        channelId: "phm_approval",
      }),
    );
  });

  it("插件不可用时如实记录错误并跳过，不抛出、不伪造成功", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    setNotificationModuleLoader(async () => null);

    sendLocalNotification({ title: "t", body: "b" });
    await vi.waitFor(() => expect(warnSpy).toHaveBeenCalled());
    expect(warnSpy.mock.calls[0]?.[1]?.message ?? "").toContain("未加载通知能力");
    warnSpy.mockRestore();
  });
});
