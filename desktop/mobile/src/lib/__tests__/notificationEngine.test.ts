import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createChannel,
  isPermissionGranted,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import type { ConversationRecord, PendingApproval, Turn } from "@shared/contracts/protocol";
import { startNotificationEngine } from "../notificationEngine";
import { mobileWsClient, useMobileStore } from "../mobileStore";
import {
  saveNotificationPreferences,
  DEFAULT_NOTIFICATION_PREFERENCES,
} from "../../components/NotificationPreferences";
import { installFakeWebSocket, latestSocket } from "../../test/fakeWebSocket";

// 通知插件是原生平台边界：jsdom 里没有 Tauri 运行时，这里换成桩函数。系统授权状态经
// vi.mocked 设定；sendNotification 与 createChannel 收到的参数就是交给系统的通知与渠道。
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
  createChannel: vi.fn(),
}));

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

let disposeEngine: (() => void) | null = null;
let sequence = 0;

/** 按真实协议向 mobileWsClient 推送一条带序号的事件，通知引擎与 store 都会收到。 */
function emitEvent(event: string, payload: object): void {
  sequence += 1;
  latestSocket().emit({ kind: "event", event, sequence, payload });
}

function turn(target: Turn["target"], status: Turn["status"]): Turn {
  return {
    turn_id: "turn-1",
    account_id: "acc",
    project_id: "p1",
    conversation_id: "conv-1",
    target,
    source_message_id: "m1",
    status,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
}

const APPROVAL: PendingApproval = {
  approval_id: "appr-1",
  conversation_id: "conv-2",
  task_id: "task-1",
  operation: {
    tool_kind: "file_write",
    command: null,
    paths: ["config.json"],
    patch_file_count: null,
    summary: "写入文件 config.json",
  },
  reason: "需要确认",
};

/** 启动引擎并等到权限查询完成：查到已授权后引擎随即创建通知渠道。 */
async function startEngineAndWaitReady(): Promise<void> {
  disposeEngine = startNotificationEngine();
  await vi.waitFor(() => expect(createChannel).toHaveBeenCalled());
}

/** 给事件处理与插件调用留出时间，再断言没有发送通知。 */
function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 30));
}

beforeEach(async () => {
  installFakeWebSocket();
  // disconnect 把会话级状态复位到初值，通知正文里的会话标题取自其中的会话记录。
  await useMobileStore.getState().disconnect();
  useMobileStore.getState().start();
  mobileWsClient.connect();
  latestSocket().open();
  sequence = 0;
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  window.localStorage.clear();
  stubVisibility("hidden");
  vi.mocked(isPermissionGranted).mockReset().mockResolvedValue(true);
  vi.mocked(sendNotification).mockReset();
  vi.mocked(createChannel).mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  disposeEngine?.();
  disposeEngine = null;
  mobileWsClient.disconnect();
  vi.unstubAllGlobals();
  delete window.__TAURI_INTERNALS__;
  delete window.__TAURI__;
  stubVisibility("visible");
  vi.restoreAllMocks();
});

describe("notificationEngine 通知规则", () => {
  it.each([
    ["character", "completed", "任务完成", "已完成"],
    ["character", "failed", "任务完成", "失败"],
    ["character", "cancelled", "任务完成", "已取消"],
    ["assistant", "completed", "委派结果", "已完成"],
  ] as const)(
    "target=%s 的回合进入 %s 时发送「%s」",
    async (target, status, title, statusText) => {
      stubAndroidShell();
      await startEngineAndWaitReady();

      emitEvent("turn.status_changed", { turn: turn(target, status) });

      await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
      expect(sendNotification).toHaveBeenCalledWith(
        expect.objectContaining({ title, body: `「新聊天」${statusText}` }),
      );
    },
  );

  it.each(["queued", "accepted", "running"] as const)("回合处于 %s 时不发送通知", async (status) => {
    stubAndroidShell();
    await startEngineAndWaitReady();

    emitEvent("turn.status_changed", { turn: turn("character", status) });
    await settle();

    expect(sendNotification).not.toHaveBeenCalled();
  });

  it("审批请求以 operation.summary 为正文", async () => {
    stubAndroidShell();
    await startEngineAndWaitReady();

    emitEvent("approval.requested", APPROVAL);

    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
    expect(sendNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: "审批请求", body: "「新聊天」写入文件 config.json" }),
    );
  });

  it("正文使用 store 中的会话标题", async () => {
    const conversation: ConversationRecord = {
      conversation_id: "conv-1",
      project_id: "p1",
      pair_id: "pair-default",
      title: "白厄的训练日志",
      last_mode: "chat",
      archived: false,
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
    };
    stubAndroidShell();
    await startEngineAndWaitReady();

    emitEvent("conversation.changed", { conversation });
    emitEvent("turn.status_changed", { turn: turn("character", "completed") });

    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
    expect(sendNotification).toHaveBeenCalledWith(
      expect.objectContaining({ body: "「白厄的训练日志」已完成" }),
    );
  });

  it("该类通知在偏好中关闭时不发送", async () => {
    saveNotificationPreferences({
      ...DEFAULT_NOTIFICATION_PREFERENCES,
      taskCompleted: { enabled: false, importance: "default" },
    });
    stubAndroidShell();
    await startEngineAndWaitReady();

    emitEvent("turn.status_changed", { turn: turn("character", "completed") });
    await settle();

    expect(sendNotification).not.toHaveBeenCalled();
  });

  // 渠道 importance 取插件 Importance 枚举：Low=2、Default=3、High=4。
  it.each([
    ["high", 4],
    ["default", 3],
    ["silent", 2],
  ] as const)(
    "提醒方式为 %s 时经已创建的 importance=%i 渠道发送",
    async (importance, channelImportance) => {
      saveNotificationPreferences({
        ...DEFAULT_NOTIFICATION_PREFERENCES,
        approvalRequested: { enabled: true, importance },
      });
      stubAndroidShell();
      await startEngineAndWaitReady();

      emitEvent("approval.requested", APPROVAL);

      await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
      const { channelId } = vi.mocked(sendNotification).mock.calls[0][0] as { channelId: string };
      await vi.waitFor(() => {
        const created = vi.mocked(createChannel).mock.calls.map(([channel]) => channel);
        expect(created.find((channel) => channel.id === channelId)?.importance).toBe(
          channelImportance,
        );
      });
    },
  );

  it("应用在前台时不发送", async () => {
    stubVisibility("visible");
    stubAndroidShell();
    await startEngineAndWaitReady();

    emitEvent("turn.status_changed", { turn: turn("character", "completed") });
    await settle();

    expect(sendNotification).not.toHaveBeenCalled();
  });
});

describe("notificationEngine 环境与生命周期", () => {
  it("PWA 下不激活，事件不产生通知", async () => {
    disposeEngine = startNotificationEngine();

    emitEvent("turn.status_changed", { turn: turn("character", "completed") });
    await settle();

    expect(sendNotification).not.toHaveBeenCalled();
  });

  it("dispose 后不再监听事件", async () => {
    stubAndroidShell();
    await startEngineAndWaitReady();
    disposeEngine?.();
    disposeEngine = null;

    emitEvent("turn.status_changed", { turn: turn("character", "completed") });
    await settle();

    expect(sendNotification).not.toHaveBeenCalled();
  });

  it("壳注入晚于引擎启动时，环境变为 android_shell 后激活并发送", async () => {
    disposeEngine = startNotificationEngine();
    await settle();
    expect(createChannel).not.toHaveBeenCalled();

    stubAndroidShell();
    await vi.waitFor(() => expect(createChannel).toHaveBeenCalled());
    emitEvent("turn.status_changed", { turn: turn("character", "completed") });

    await vi.waitFor(() => expect(sendNotification).toHaveBeenCalledTimes(1));
  });
});
