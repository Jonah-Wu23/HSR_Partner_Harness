import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type {
  PendingApproval,
  PowerStatusPayload,
  ProjectRecord,
} from "@shared/contracts/protocol";
import { mobileWsClient, useMobileStore } from "../../../lib/mobileStore";
import { getStoredToken, saveCredentials } from "../../../lib/wsClient";
import { FakeWebSocket, installFakeWebSocket, latestSocket } from "../../../test/fakeWebSocket";
import { ChatListPage } from "../ChatListPage";

const PROJECTS: ProjectRecord[] = [
  {
    project_id: "p1",
    name: "主工程",
    root_path: "/workspace/p1",
    approval_mode: "request_approval",
    reasoning_effort: "medium",
    archived: false,
    created_at: "2026-08-20T10:00:00Z",
    last_opened_at: "2026-08-20T12:00:00Z",
    path_available: true,
    conversations: [
      {
        conversation_id: "c1",
        project_id: "p1",
        pair_id: "pair-1",
        title: "核心开发",
        last_mode: "collaboration",
        archived: false,
        created_at: "2026-08-20T10:00:00Z",
        updated_at: "2026-08-20T14:30:00Z",
      },
      {
        conversation_id: "c2-archived",
        project_id: "p1",
        pair_id: "pair-1",
        title: "已归档聊天",
        last_mode: "chat",
        archived: true,
        created_at: "2026-08-20T08:00:00Z",
        updated_at: "2026-08-20T09:00:00Z",
      },
    ],
  },
  {
    project_id: "p2",
    name: "空聊天工程",
    root_path: "/workspace/p2",
    approval_mode: "request_approval",
    reasoning_effort: "medium",
    archived: false,
    created_at: "2026-08-20T10:00:00Z",
    last_opened_at: "2026-08-20T12:00:00Z",
    path_available: true,
    conversations: [],
  },
];

/**
 * 首次同步完成后的列表数据。生产中由 app.bootstrap 快照写入，这里作为前置条件；
 * 之后的事件序号从 11 起。
 */
function syncedState(projects: ProjectRecord[]): void {
  useMobileStore.setState({ projects, bootstrapped: true, lastSequence: 10 });
}

function emitEvent(event: string, sequence: number, payload: unknown): void {
  latestSocket().emit({ kind: "event", event, sequence, payload });
}

/** 已配对的手机重新连上桌面端，回放 app.bootstrap 的失败响应。 */
async function failBootstrap(code: string, message: string): Promise<void> {
  saveCredentials("tok-paired", "我的手机");
  useMobileStore.getState().reconnect();
  const socket = latestSocket();
  socket.open();
  await vi.waitFor(() => socket.lastFrame("app.bootstrap"));
  socket.respondError(socket.lastFrame("app.bootstrap"), code, message);
}

describe("ChatListPage 聊天列表", () => {
  beforeEach(async () => {
    installFakeWebSocket();
    window.localStorage.clear();
    window.location.hash = "#/list";
    // disconnect 把会话级状态复位到初值。
    await useMobileStore.getState().disconnect();
    useMobileStore.getState().start();
    mobileWsClient.connect();
    latestSocket().open();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("首次同步完成前展示骨架屏", () => {
    render(<ChatListPage />);

    expect(screen.getByTestId("chat-list-skeleton")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-list-empty")).toBeNull();
    expect(screen.queryByTestId("chat-list-content")).toBeNull();
  });

  it("重连退避用尽后展示无法连接的原因与通知偏好，点击重试重新建立连接", async () => {
    vi.useFakeTimers();
    try {
      latestSocket().close();
      for (let attempt = 0; attempt < 5; attempt += 1) {
        vi.runOnlyPendingTimers();
        latestSocket().close();
      }
    } finally {
      vi.useRealTimers();
    }
    expect(useMobileStore.getState().connection).toBe("unreachable");

    render(<ChatListPage />);
    expect(screen.getByTestId("chat-list-error")).toHaveTextContent("无法连接到电脑桌面端");
    // 通知偏好是本机设置，同步失败时也能查看。
    expect(await screen.findByTestId("notif-unavailable-pwa")).toBeInTheDocument();

    const socketsBefore = FakeWebSocket.instances.length;
    fireEvent.click(screen.getByTestId("chat-list-btn-retry"));

    expect(FakeWebSocket.instances).toHaveLength(socketsBefore + 1);
    await waitFor(() => expect(screen.getByTestId("chat-list-skeleton")).toBeInTheDocument());
  });

  it("配对失效时「重新配对」清除本机凭据并跳转配对页", async () => {
    await failBootstrap("unauthorized", "revoked_token");
    await waitFor(() => expect(useMobileStore.getState().connection).toBe("auth_failed"));

    render(<ChatListPage />);
    expect(screen.getByTestId("chat-list-error")).toHaveTextContent(
      "配对鉴权已失效或设备已被撤销",
    );
    fireEvent.click(screen.getByTestId("chat-list-btn-repair"));

    // 凭据已失效，服务端不会接受释放控制权，直接清凭据后跳转。
    await waitFor(() => expect(window.location.hash).toBe("#/pair"));
    expect(getStoredToken()).toBeNull();
    expect(latestSocket().sentFrames("remote.release_control")).toHaveLength(0);
  });

  it("状态同步失败时展示原始错误，点击重新同步再次发出 app.bootstrap", async () => {
    await failBootstrap("internal_error", "快照生成失败：数据库被占用");

    render(<ChatListPage />);
    expect(await screen.findByTestId("chat-list-sync-error-text")).toHaveTextContent(
      "快照生成失败：数据库被占用",
    );
    fireEvent.click(screen.getByTestId("chat-list-btn-resync"));

    await vi.waitFor(() => expect(latestSocket().sentFrames("app.bootstrap")).toHaveLength(2));
  });

  it("同步完成且没有项目时展示空态引导与连接详情入口", () => {
    syncedState([]);
    render(<ChatListPage />);

    expect(screen.getByTestId("chat-list-empty")).toHaveTextContent(
      "还没有项目。请在电脑端创建项目后，手机端将自动同步项目与聊天。",
    );
    expect(screen.getByTestId("btn-toggle-connection-details")).toBeInTheDocument();
  });

  it("按项目分组渲染未归档的会话，点击会话进入聊天页", () => {
    syncedState(PROJECTS);
    render(<ChatListPage />);

    expect(screen.getByText("主工程")).toBeInTheDocument();
    expect(screen.getByText("核心开发")).toBeInTheDocument();
    expect(screen.getByText("委派")).toBeInTheDocument();
    expect(screen.queryByText("已归档聊天")).toBeNull();
    expect(screen.getByText("空聊天工程")).toBeInTheDocument();
    expect(screen.getByText("暂无活跃聊天")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("conversation-item-c1"));
    expect(window.location.hash).toBe("#/chat/c1");
  });

  it("task.busy_changed 与 approval.requested 到达后会话行显示运行中与待审批徽章", async () => {
    syncedState(PROJECTS);
    render(<ChatListPage />);

    const activeTask = { project_id: "p1", conversation_id: "c1", task_id: "t1", engine_turn_id: "e1" };
    emitEvent("task.busy_changed", 11, {
      conversation_id: "c1",
      busy: true,
      active_task: activeTask,
      active_tasks: [activeTask],
    });
    const approval: PendingApproval = {
      approval_id: "a1",
      conversation_id: "c1",
      task_id: "t1",
      operation: {
        tool_kind: "shell",
        command: "npm test",
        paths: [],
        patch_file_count: null,
        summary: "运行单元测试",
      },
      reason: "需要执行命令",
    };
    emitEvent("approval.requested", 12, approval);

    await waitFor(() => {
      expect(screen.getByTestId("badge-running-c1")).toHaveTextContent("运行中");
      expect(screen.getByTestId("badge-approvals-c1")).toHaveTextContent("待审批 1");
    });
  });

  it("电源警示点「知道了」后收起，power.status_changed 带来新的检查时间时重新出现", async () => {
    const atRiskStatus: PowerStatusPayload = {
      supported: true,
      platform: "windows",
      plan_name: "平衡",
      ac_sleep_timeout_seconds: 600,
      dc_sleep_timeout_seconds: 1800,
      remote_serve_enabled: true,
      threshold_seconds: 900,
      at_risk: true,
      reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
      checked_at: "2026-09-02T10:00:00",
      warnings: [],
    };
    syncedState([]);
    render(<ChatListPage />);

    emitEvent("power.status_changed", 11, atRiskStatus);
    fireEvent.click(await screen.findByTestId("btn-power-dismiss"));
    expect(screen.queryByTestId("power-status-banner")).toBeNull();

    emitEvent("power.status_changed", 12, { ...atRiskStatus, checked_at: "2026-09-02T10:05:00" });
    expect(await screen.findByTestId("power-status-banner")).toHaveTextContent("电脑可能休眠");
  });
});
