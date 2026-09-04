import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { ChatListPage } from "../ChatListPage";
import { useMobileStore } from "../../../lib/mobileStore";
import * as router from "../../../lib/router";
import type { PowerStatusPayload, ProjectRecord } from "@shared/contracts/protocol";

const initialStoreState = useMobileStore.getState();

describe("ChatListPage 组件", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useMobileStore.setState({
      connection: "disconnected",
      deviceName: null,
      projects: [],
      conversationsById: {},
      activeConversationId: null,
      messages: [],
      toolRuns: [],
      approvals: [],
      lastSequence: 0,
      bootstrapped: false,
      powerStatus: null,
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useMobileStore.setState(initialStoreState);
  });

  it("未水合（!bootstrapped）且处于连接中时展示骨架屏", () => {
    useMobileStore.setState({
      bootstrapped: false,
      connection: "connecting",
      projects: [],
    });

    render(<ChatListPage />);
    expect(screen.getByTestId("chat-list-skeleton")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-list-empty")).toBeNull();
    expect(screen.queryByTestId("chat-list-content")).toBeNull();
  });

  it("未水合且处于 unreachable 时展示真实错误与重试按钮", () => {
    const reconnectSpy = vi.fn();
    useMobileStore.setState({
      bootstrapped: false,
      connection: "unreachable",
      reconnect: reconnectSpy,
      projects: [],
    });

    render(<ChatListPage />);
    expect(screen.getByTestId("chat-list-error")).toBeInTheDocument();
    expect(screen.getByText("无法连接到电脑桌面端", { exact: false })).toBeInTheDocument();

    const retryBtn = screen.getByTestId("chat-list-btn-retry");
    fireEvent.click(retryBtn);
    expect(reconnectSpy).toHaveBeenCalled();
  });

  it("未水合且处于 auth_failed 时「重新配对」先清凭据再跳转", () => {
    const navigateSpy = vi.spyOn(router, "navigate");
    const disconnectSpy = vi.spyOn(useMobileStore.getState(), "disconnect");
    useMobileStore.setState({
      bootstrapped: false,
      connection: "auth_failed",
      projects: [],
    });

    render(<ChatListPage />);
    expect(screen.getByTestId("chat-list-error")).toBeInTheDocument();
    expect(screen.getByText("配对鉴权已失效或设备已被撤销", { exact: false })).toBeInTheDocument();

    const repairBtn = screen.getByTestId("chat-list-btn-repair");
    fireEvent.click(repairBtn);
    // 只 navigate 会被 App 路由守卫按 token 存在性弹回列表页，必须先 disconnect 清凭据
    expect(disconnectSpy).toHaveBeenCalledTimes(1);
    expect(navigateSpy).toHaveBeenCalledWith({ name: "pair" });
  });

  it("已水合并且项目为空时展示空态引导", () => {
    useMobileStore.setState({
      bootstrapped: true,
      connection: "connected",
      projects: [],
    });

    render(<ChatListPage />);
    expect(screen.getByTestId("chat-list-empty")).toBeInTheDocument();
    expect(screen.getByText("还没有项目。请在电脑端创建项目后，手机端将自动同步项目与聊天。")).toBeInTheDocument();
  });

  it("已水合时按项目分组渲染会话，过滤 archived，点击可跳转聊天页", () => {
    const navigateSpy = vi.spyOn(router, "navigate");

    const mockProjects: ProjectRecord[] = [
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

    useMobileStore.setState({
      bootstrapped: true,
      connection: "connected",
      projects: mockProjects,
    });

    render(<ChatListPage />);
    expect(screen.getByTestId("chat-list-content")).toBeInTheDocument();
    expect(screen.getByText("主工程")).toBeInTheDocument();
    expect(screen.getByText("核心开发")).toBeInTheDocument();
    expect(screen.getByText("委派")).toBeInTheDocument();
    expect(screen.queryByText("已归档聊天")).toBeNull();

    expect(screen.getByText("空聊天工程")).toBeInTheDocument();
    expect(screen.getByText("暂无活跃聊天")).toBeInTheDocument();

    const convItem = screen.getByTestId("conversation-item-c1");
    fireEvent.click(convItem);
    expect(navigateSpy).toHaveBeenCalledWith({ name: "chat", conversationId: "c1" });
  });
});

describe("ChatListPage V0.3.7 接线（电源状态与通知偏好）", () => {
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
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    useMobileStore.setState({
      connection: "connected",
      deviceName: "测试手机",
      projects: [],
      conversationsById: {},
      activeConversationId: null,
      messages: [],
      toolRuns: [],
      approvals: [],
      lastSequence: 0,
      bootstrapped: true,
      powerStatus: null,
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.localStorage.clear();
    useMobileStore.setState(initialStoreState);
  });

  it("at_risk 时在列表页顶部展示「电脑可能休眠」警示条，reason 原文呈现", () => {
    useMobileStore.setState({ powerStatus: atRiskStatus });
    render(<ChatListPage />);
    expect(screen.getByTestId("power-status-banner")).toHaveClass("is-at-risk");
    expect(screen.getByTestId("power-status-title")).toHaveTextContent("电脑可能休眠");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent(
      "AC 睡眠超时 600 秒低于阈值 900 秒",
    );
  });

  it("点击「知道了」收敛警示条；电脑状态再次变化（新 checked_at）时重新出现", () => {
    useMobileStore.setState({ powerStatus: atRiskStatus });
    render(<ChatListPage />);
    fireEvent.click(screen.getByTestId("btn-power-dismiss"));
    expect(screen.queryByTestId("power-status-banner")).toBeNull();

    act(() => {
      useMobileStore.setState({
        powerStatus: { ...atRiskStatus, checked_at: "2026-09-02T10:05:00" },
      });
    });
    expect(screen.getByTestId("power-status-banner")).toBeInTheDocument();
  });

  it("远程服务未开启时弱化展示 reason 原文，不冒充休眠风险", () => {
    useMobileStore.setState({
      powerStatus: { ...atRiskStatus, at_risk: false, remote_serve_enabled: false, reason: "远程服务未开启" },
    });
    render(<ChatListPage />);
    expect(screen.getByTestId("power-status-banner")).toHaveClass("is-muted");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent("远程服务未开启");
    expect(screen.queryByTestId("power-status-title")).toBeNull();
  });

  it("无电源数据时不渲染警示条", () => {
    render(<ChatListPage />);
    expect(screen.queryByTestId("power-status-banner")).toBeNull();
  });

  it("PWA 下通知偏好区如实说明仅 Android 壳内可用，不渲染任何开关", async () => {
    const { container } = render(<ChatListPage />);
    const note = await screen.findByTestId("notif-unavailable-pwa");
    expect(note).toHaveTextContent("本地通知仅在 Android 壳内可用");
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });
});
