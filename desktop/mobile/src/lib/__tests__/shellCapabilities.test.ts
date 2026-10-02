import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import {
  detectShellEnvironment,
  probeNotificationCapability,
  requestNotificationPermission,
  sendLocalNotification,
} from "../shellCapabilities";

// 通知插件是原生平台边界：jsdom 里没有 Tauri 运行时，插件调用无法执行，这里换成桩函数。
// 各用例经 vi.mocked 按插件真实签名设定返回值。
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
  createChannel: vi.fn(),
}));

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
  vi.mocked(isPermissionGranted).mockReset();
  vi.mocked(requestPermission).mockReset();
  vi.mocked(sendNotification).mockReset();
});

afterEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("detectShellEnvironment 环境探测", () => {
  it.each([
    ["没有 Tauri 全局对象", "pwa", null, BROWSER_UA],
    ["Android 浏览器没有 Tauri 全局对象", "pwa", null, ANDROID_SHELL_UA],
    ["__TAURI_INTERNALS__ 加 Android UA", "android_shell", "__TAURI_INTERNALS__", ANDROID_SHELL_UA],
    ["__TAURI_INTERNALS__ 加桌面 UA", "desktop_shell", "__TAURI_INTERNALS__", BROWSER_UA],
    ["只有 __TAURI__ 加 Android UA", "android_shell", "__TAURI__", ANDROID_SHELL_UA],
  ] as const)("%s 时识别为 %s", (_label, expected, globalKey, userAgent) => {
    if (globalKey) window[globalKey] = {};
    stubUserAgent(userAgent);
    expect(detectShellEnvironment()).toBe(expected);
  });
});

describe("probeNotificationCapability 通知能力探测", () => {
  it("PWA 下返回 not_shell，不调用插件", async () => {
    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "unavailable",
      reason: "not_shell",
    });
    expect(isPermissionGranted).not.toHaveBeenCalled();
  });

  it.each([true, false])("壳内插件可用时返回 ready，系统授权状态 %s", async (granted) => {
    stubAndroidShellGlobals();
    vi.mocked(isPermissionGranted).mockResolvedValue(granted);

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "ready",
      permission_granted: granted,
    });
  });

  it("插件查询授权失败时返回 plugin_unavailable 并记录原始错误", async () => {
    stubAndroidShellGlobals();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const failure = new Error("plugin:notification|is_permission_granted failed");
    vi.mocked(isPermissionGranted).mockRejectedValue(failure);

    await expect(probeNotificationCapability()).resolves.toEqual({
      kind: "unavailable",
      reason: "plugin_unavailable",
    });
    expect(warnSpy).toHaveBeenCalledWith(expect.any(String), failure);
  });
});

describe("requestNotificationPermission 权限申请", () => {
  it.each([
    ["granted", true],
    ["denied", false],
    ["default", false],
  ] as const)("插件返回 %s 时结果为 %s", async (permission, granted) => {
    vi.mocked(requestPermission).mockResolvedValue(permission);
    await expect(requestNotificationPermission()).resolves.toBe(granted);
  });

  it("插件申请调用失败时抛出原始错误", async () => {
    vi.mocked(requestPermission).mockRejectedValue(
      new Error("plugin:notification|request_permission failed"),
    );
    await expect(requestNotificationPermission()).rejects.toThrow(
      "plugin:notification|request_permission failed",
    );
  });
});

describe("sendLocalNotification 本地通知发送", () => {
  it("把标题、正文与渠道交给插件发送", async () => {
    sendLocalNotification({ title: "审批请求", body: "写入文件", channelId: "phm_approval" });
    await vi.waitFor(() =>
      expect(sendNotification).toHaveBeenCalledWith({
        title: "审批请求",
        body: "写入文件",
        channelId: "phm_approval",
      }),
    );
  });

  it("插件发送失败时记录原始错误并跳过该条", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const failure = new Error("plugin:notification|notify failed");
    vi.mocked(sendNotification).mockImplementation(() => {
      throw failure;
    });

    expect(() => sendLocalNotification({ title: "t", body: "b" })).not.toThrow();
    await vi.waitFor(() => expect(warnSpy).toHaveBeenCalledWith(expect.any(String), failure));
  });
});
