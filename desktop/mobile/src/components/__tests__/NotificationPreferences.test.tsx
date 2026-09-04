import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  DEFAULT_NOTIFICATION_PREFERENCES,
  NotificationPreferences,
  loadNotificationPreferences,
} from "../NotificationPreferences";
import { setNotificationModuleLoader } from "../../lib/shellCapabilities";

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

function moduleStub(overrides: {
  isPermissionGranted?: () => Promise<boolean>;
  requestPermission?: () => Promise<boolean>;
}) {
  return async () => ({
    isPermissionGranted:
      overrides.isPermissionGranted ?? (async () => true),
    requestPermission: overrides.requestPermission ?? (async () => true),
  });
}

beforeEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubBrowser();
  setNotificationModuleLoader(null);
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  setNotificationModuleLoader(null);
  vi.restoreAllMocks();
});

describe("NotificationPreferences 组件", () => {
  it("PWA 下如实说明本地通知仅在 Android 壳内可用，不提供任何伪造开关", async () => {
    const { container } = render(<NotificationPreferences />);

    const note = await screen.findByTestId("notif-unavailable-pwa");
    expect(note).toHaveTextContent("本地通知仅在 Android 壳内可用");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
    expect(container.querySelectorAll("select")).toHaveLength(0);
    expect(screen.queryByTestId("notif-foreground-note")).toBeNull();
  });

  it("能力探测进行中显示检测提示", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(() => new Promise(() => {}));

    render(<NotificationPreferences />);
    expect(await screen.findByTestId("notif-probing")).toHaveTextContent(
      "正在检测当前环境的通知能力",
    );
  });

  it("壳内通知插件不可用时如实说明，不渲染开关", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(async () => null);

    const { container } = render(<NotificationPreferences />);
    await screen.findByTestId("notif-unavailable-plugin");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });

  it("壳内权限已授予时渲染三类可编辑偏好并按默认值展示", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(moduleStub({}));

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-granted");

    for (const key of ["taskCompleted", "delegationResult", "approvalRequested"]) {
      expect(screen.getByTestId(`notif-row-${key}`)).toBeInTheDocument();
      expect(screen.getByTestId(`notif-toggle-${key}`)).toBeChecked();
    }
    // 默认：审批请求高优先级，其余常规
    expect(screen.getByTestId("notif-importance-taskCompleted")).toHaveValue("default");
    expect(screen.getByTestId("notif-importance-approvalRequested")).toHaveValue("high");
    // Android 壳内呈现常驻通知说明
    expect(screen.getByTestId("notif-foreground-note")).toHaveTextContent(
      "保持连接中",
    );
  });

  it("关闭「任务完成」并调整「审批请求」提醒方式后立即持久化到 localStorage", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(moduleStub({}));

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
    // 关闭后提醒方式不可再调
    expect(screen.getByTestId("notif-importance-taskCompleted")).toBeDisabled();
  });

  it("尚未授权时提供权限申请入口：申请成功切换为已授权", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(
      moduleStub({
        isPermissionGranted: async () => false,
        requestPermission: async () => true,
      }),
    );

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-missing");

    fireEvent.click(screen.getByTestId("btn-request-permission"));
    expect(await screen.findByTestId("notif-permission-granted")).toBeInTheDocument();
  });

  it("申请被拒时如实呈现仍未授权，不伪装成功", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(
      moduleStub({
        isPermissionGranted: async () => false,
        requestPermission: async () => false,
      }),
    );

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-missing");

    fireEvent.click(screen.getByTestId("btn-request-permission"));
    const error = await screen.findByTestId("notif-permission-error");
    expect(error).toHaveTextContent("仍未获得系统通知权限");
    expect(screen.queryByTestId("notif-permission-granted")).toBeNull();
  });

  it("权限申请调用抛错时展示原始错误信息", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(
      moduleStub({
        isPermissionGranted: async () => false,
        requestPermission: async () => {
          throw new Error("plugin:notification|request_permission failed");
        },
      }),
    );

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-missing");

    fireEvent.click(screen.getByTestId("btn-request-permission"));
    expect(await screen.findByTestId("notif-permission-error")).toHaveTextContent(
      "plugin:notification|request_permission failed",
    );
  });

  it("localStorage 偏好损坏时按默认值处理并保留原始解析错误日志", async () => {
    stubAndroidShell();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    setNotificationModuleLoader(moduleStub({}));
    window.localStorage.setItem("phm.notificationPreferences.v1", "{not-json");

    render(<NotificationPreferences />);
    await screen.findByTestId("notif-permission-granted");

    expect(screen.getByTestId("notif-toggle-taskCompleted")).toBeChecked();
    expect(loadNotificationPreferences()).toEqual(DEFAULT_NOTIFICATION_PREFERENCES);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("支持 initialPreferences 注入并通过 onPreferencesChange 回传变更", async () => {
    stubAndroidShell();
    setNotificationModuleLoader(moduleStub({}));
    const onPreferencesChange = vi.fn();

    render(
      <NotificationPreferences
        initialPreferences={{
          taskCompleted: { enabled: false, importance: "silent" },
          delegationResult: { enabled: true, importance: "default" },
          approvalRequested: { enabled: true, importance: "high" },
        }}
        onPreferencesChange={onPreferencesChange}
      />,
    );
    await screen.findByTestId("notif-permission-granted");

    expect(screen.getByTestId("notif-toggle-taskCompleted")).not.toBeChecked();
    fireEvent.click(screen.getByTestId("notif-toggle-delegationResult"));
    expect(onPreferencesChange).toHaveBeenCalledTimes(1);
    expect(onPreferencesChange.mock.calls[0][0].delegationResult.enabled).toBe(false);
  });
});
