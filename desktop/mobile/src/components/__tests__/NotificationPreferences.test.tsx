import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { isPermissionGranted, requestPermission } from "@tauri-apps/plugin-notification";
import {
  DEFAULT_NOTIFICATION_PREFERENCES,
  NotificationPreferences,
  loadNotificationPreferences,
} from "../NotificationPreferences";

// 通知插件是原生平台边界：jsdom 里没有 Tauri 运行时，这里换成桩函数，
// 各用例经 vi.mocked 设定系统授权状态与申请结果。
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
  createChannel: vi.fn(),
}));

const STORAGE_KEY = "phm.notificationPreferences.v1";

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const ANDROID_SHELL_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";

function stubAndroidShell(): void {
  window.__TAURI_INTERNALS__ = {};
  Object.defineProperty(window.navigator, "userAgent", {
    value: ANDROID_SHELL_UA,
    configurable: true,
  });
}

function stubBrowser(): void {
  Object.defineProperty(window.navigator, "userAgent", {
    value: BROWSER_UA,
    configurable: true,
  });
}

beforeEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubBrowser();
  window.localStorage.clear();
  vi.mocked(isPermissionGranted).mockReset();
  vi.mocked(requestPermission).mockReset();
});

afterEach(() => {
  cleanup();
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("NotificationPreferences 组件", () => {
  it.each([
    {
      label: "PWA",
      setup: () => undefined,
      testId: "notif-unavailable-pwa",
      text: "本地通知仅在 Android 壳内可用",
      foregroundNote: false,
    },
    {
      label: "壳内通知能力探测中",
      setup: () => {
        stubAndroidShell();
        vi.mocked(isPermissionGranted).mockReturnValue(new Promise(() => {}));
      },
      testId: "notif-probing",
      text: "正在检测当前环境的通知能力",
      foregroundNote: true,
    },
    {
      label: "壳内通知插件调用失败",
      setup: () => {
        stubAndroidShell();
        vi.spyOn(console, "warn").mockImplementation(() => {});
        vi.mocked(isPermissionGranted).mockRejectedValue(
          new Error("plugin:notification|is_permission_granted failed"),
        );
      },
      testId: "notif-unavailable-plugin",
      text: "当前壳内未能加载通知能力",
      foregroundNote: true,
    },
  ].map((row) => [row.label, row] as const))("%s 时说明原因，不渲染偏好开关", async (_label, row) => {
    const { setup, testId, text, foregroundNote } = row;
    setup();
    const { container } = render(<NotificationPreferences />);

    expect(await screen.findByTestId(testId)).toHaveTextContent(text);
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
    expect(container.querySelectorAll("select")).toHaveLength(0);
    expect(screen.queryByTestId("notif-foreground-note") !== null).toBe(foregroundNote);
  });

  it("系统已授权时按默认偏好展示三类可编辑通知", async () => {
    stubAndroidShell();
    vi.mocked(isPermissionGranted).mockResolvedValue(true);

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-granted");

    for (const key of ["taskCompleted", "delegationResult", "approvalRequested"]) {
      expect(screen.getByTestId(`notif-toggle-${key}`)).toBeChecked();
    }
    expect(screen.getByTestId("notif-importance-taskCompleted")).toHaveValue("default");
    expect(screen.getByTestId("notif-importance-approvalRequested")).toHaveValue("high");
    expect(screen.getByTestId("notif-foreground-note")).toHaveTextContent("保持连接中");
  });

  it("展示 localStorage 中已保存的偏好", async () => {
    stubAndroidShell();
    vi.mocked(isPermissionGranted).mockResolvedValue(true);
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_NOTIFICATION_PREFERENCES,
        taskCompleted: { enabled: false, importance: "silent" },
      }),
    );

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-granted");

    expect(screen.getByTestId("notif-toggle-taskCompleted")).not.toBeChecked();
    expect(screen.getByTestId("notif-importance-taskCompleted")).toHaveValue("silent");
    expect(screen.getByTestId("notif-toggle-delegationResult")).toBeChecked();
  });

  it("关闭「任务完成」并调整「审批请求」提醒方式后立即写入 localStorage 并同步原生常驻连接", async () => {
    stubAndroidShell();
    vi.mocked(isPermissionGranted).mockResolvedValue(true);
    // Android 壳注入的原生接口，PWA 与 jsdom 里都没有。
    const syncConfig = vi.fn();
    vi.stubGlobal("PairHarnessNative", { syncConfig });

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-granted");

    fireEvent.click(screen.getByTestId("notif-toggle-taskCompleted"));
    fireEvent.change(screen.getByTestId("notif-importance-approvalRequested"), {
      target: { value: "silent" },
    });

    const stored = loadNotificationPreferences();
    expect(stored.taskCompleted.enabled).toBe(false);
    expect(stored.approvalRequested.importance).toBe("silent");
    expect(stored.delegationResult).toEqual(
      DEFAULT_NOTIFICATION_PREFERENCES.delegationResult,
    );
    expect(syncConfig).toHaveBeenCalled();
    const syncedPrefs = JSON.parse(syncConfig.mock.calls.at(-1)![2]);
    expect(syncedPrefs.taskCompleted.enabled).toBe(false);
    expect(syncedPrefs.approvalRequested.importance).toBe("silent");
    // 关闭后提醒方式不可再调
    expect(screen.getByTestId("notif-importance-taskCompleted")).toBeDisabled();
  });

  it("申请权限获准后显示已授权", async () => {
    stubAndroidShell();
    let granted = false;
    vi.mocked(isPermissionGranted).mockImplementation(async () => granted);
    vi.mocked(requestPermission).mockImplementation(async () => {
      granted = true;
      return "granted";
    });

    render(<NotificationPreferences />);
    fireEvent.click(await screen.findByTestId("btn-request-permission"));

    expect(await screen.findByTestId("notif-permission-granted")).toBeInTheDocument();
  });

  it("申请被拒时提示仍未获得系统通知权限", async () => {
    stubAndroidShell();
    vi.mocked(isPermissionGranted).mockResolvedValue(false);
    vi.mocked(requestPermission).mockResolvedValue("denied");

    render(<NotificationPreferences />);
    fireEvent.click(await screen.findByTestId("btn-request-permission"));

    expect(await screen.findByTestId("notif-permission-error")).toHaveTextContent(
      "仍未获得系统通知权限",
    );
    expect(screen.queryByTestId("notif-permission-granted")).toBeNull();
  });

  it("权限申请调用失败时展示原始错误", async () => {
    stubAndroidShell();
    vi.mocked(isPermissionGranted).mockResolvedValue(false);
    vi.mocked(requestPermission).mockRejectedValue(
      new Error("plugin:notification|request_permission failed"),
    );

    render(<NotificationPreferences />);
    fireEvent.click(await screen.findByTestId("btn-request-permission"));

    expect(await screen.findByTestId("notif-permission-error")).toHaveTextContent(
      "plugin:notification|request_permission failed",
    );
  });

  it("申请权限超时未返回时以重新查询的系统授权状态为准", async () => {
    stubAndroidShell();
    // 插件 2.4.0 在 Android 13+ 已授权时 requestPermission 不返回：系统已授权，回调不回到 JS。
    let granted = false;
    vi.mocked(isPermissionGranted).mockImplementation(async () => granted);
    vi.mocked(requestPermission).mockImplementation(() => {
      granted = true;
      return new Promise(() => {});
    });

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-missing");

    vi.useFakeTimers();
    fireEvent.click(screen.getByTestId("btn-request-permission"));
    await vi.advanceTimersByTimeAsync(8500);
    vi.useRealTimers();

    expect(await screen.findByTestId("notif-permission-granted")).toBeInTheDocument();
    expect(screen.queryByText("正在申请权限")).toBeNull();
  });

  it("回到前台时重新探测授权状态，在系统设置里开启后即显示已授权", async () => {
    stubAndroidShell();
    let granted = false;
    vi.mocked(isPermissionGranted).mockImplementation(async () => granted);

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-missing");

    granted = true;
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));

    expect(await screen.findByTestId("notif-permission-granted")).toBeInTheDocument();
  });

  it("localStorage 偏好损坏时按默认值处理并记录解析错误", async () => {
    stubAndroidShell();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.mocked(isPermissionGranted).mockResolvedValue(true);
    window.localStorage.setItem(STORAGE_KEY, "{not-json");

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-granted");

    expect(screen.getByTestId("notif-toggle-taskCompleted")).toBeChecked();
    expect(loadNotificationPreferences()).toEqual(DEFAULT_NOTIFICATION_PREFERENCES);
    expect(warnSpy).toHaveBeenCalled();
  });
});
