import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  setNotificationTitleResolver,
  startNotificationEngine,
} from "../notificationEngine";
import { setNotificationModuleLoader } from "../shellCapabilities";
import { mobileWsClient } from "../mobileStore";
import type { WireEvent } from "../wsClient";
import {
  saveNotificationPreferences,
  DEFAULT_NOTIFICATION_PREFERENCES,
} from "../../components/NotificationPreferences";

const ANDROID_SHELL_UA =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";

function stubAndroidShell(): void {
  window.__TAURI_INTERNALS__ = {};
  Object.defineProperty(window.navigator, "userAgent", {
    value: ANDROID_SHELL_UA,
    configurable: true,
  });
}

function stubVisibility(state: "visible" | "hidden"): void {
  Object.defineProperty(document, "visibilityState", {
    value: state,
    configurable: true,
  });
}

let sendNotification: ReturnType<typeof vi.fn>;
let disposeEngine: (() => void) | null = null;

function event(name: string, payload: unknown, sequence = 1): WireEvent {
  return { kind: "event", event: name, sequence, payload: payload as Record<string, unknown> };
}

function turnEvent(
  target: string,
  status: string,
  conversationId = "conv-1",
): WireEvent {
  return event("turn.status_changed", {
    turn: { conversation_id: conversationId, target, status },
  });
}

function approvalEvent(conversationId = "conv-2"): WireEvent {
  return event("approval.requested", {
    approval_id: "appr-1",
    conversation_id: conversationId,
    operation: { summary: "写入文件 config.json" },
    reason: "需要确认",
  });
}

/** 启动引擎并等权限探测 promise resolve（engineReady 就位）。 */
async function startEngineAndWaitReady(): Promise<void> {
  disposeEngine = startNotificationEngine();
  await new Promise((resolve) => setTimeout(resolve, 20));
}

beforeEach(() => {
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  window.localStorage.clear();
  stubVisibility("hidden");
  sendNotification = vi.fn();
  setNotificationModuleLoader(async () => ({
    isPermissionGranted: async () => true,
    requestPermission: async () => true,
    sendNotification,
  }));
  setNotificationTitleResolver(null);
});

afterEach(() => {
  disposeEngine?.();
  disposeEngine = null;
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  setNotificationModuleLoader(null);
  setNotificationTitleResolver(null);
  stubVisibility("visible");
  vi.restoreAllMocks();
});

describe("notificationEngine 规则映射", () => {
  it("任务完成：target=character 的 turn 终态在后台触发通知", async () => {
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(turnEvent("character", "completed"));
    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
    expect(sendNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: "任务完成" }),
    );
  });

  it("委派结果：target=assistant 的 turn 终态标题为「委派结果」", async () => {
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(turnEvent("assistant", "completed"));
    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
    expect(sendNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: "委派结果" }),
    );
  });

  it("失败与取消同样是终态，运行中状态不通知", async () => {
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(turnEvent("character", "running"));
    mobileWsClient.emitTestEvent(turnEvent("character", "queued"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(sendNotification).not.toHaveBeenCalled();

    mobileWsClient.emitTestEvent(turnEvent("character", "failed"));
    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
    const options = sendNotification.mock.calls[0][0] as { body: string };
    expect(options.body).toContain("失败");
  });

  it("审批请求：payload 的 operation.summary 进入通知正文", async () => {
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(approvalEvent());
    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
    const options = sendNotification.mock.calls[0][0] as { title: string; body: string };
    expect(options.title).toBe("审批请求");
    expect(options.body).toContain("写入文件 config.json");
  });

  it("会话标题经注入解析，缺失时兜底「新聊天」", async () => {
    setNotificationTitleResolver((id) => (id === "conv-1" ? "白厄的训练日志" : "新聊天"));
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(turnEvent("character", "completed", "conv-1"));
    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
    const options = sendNotification.mock.calls[0][0] as { body: string };
    expect(options.body).toContain("白厄的训练日志");
  });

  it("偏好关闭后不发送（enabled=false）", async () => {
    saveNotificationPreferences({
      ...DEFAULT_NOTIFICATION_PREFERENCES,
      taskCompleted: { enabled: false, importance: "default" },
    });
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(turnEvent("character", "completed"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(sendNotification).not.toHaveBeenCalled();
  });

  it("静默档（silent）不发送", async () => {
    saveNotificationPreferences({
      ...DEFAULT_NOTIFICATION_PREFERENCES,
      approvalRequested: { enabled: true, importance: "silent" },
    });
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(approvalEvent());
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(sendNotification).not.toHaveBeenCalled();
  });

  it("前台（visible）不发送", async () => {
    stubVisibility("visible");
    stubAndroidShell();
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(turnEvent("character", "completed"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(sendNotification).not.toHaveBeenCalled();
  });
});

describe("notificationEngine 环境与生命周期", () => {
  it("非 Android 壳（PWA）不启动：事件不产生通知", async () => {
    await startEngineAndWaitReady();

    mobileWsClient.emitTestEvent(turnEvent("character", "completed"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(sendNotification).not.toHaveBeenCalled();
  });

  it("dispose 后不再监听事件", async () => {
    stubAndroidShell();
    const dispose = startNotificationEngine();
    await new Promise((resolve) => setTimeout(resolve, 20));
    dispose();

    mobileWsClient.emitTestEvent(turnEvent("character", "completed"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(sendNotification).not.toHaveBeenCalled();
  });
});
