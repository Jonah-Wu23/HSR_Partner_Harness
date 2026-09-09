import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ConversationBadgeRow } from "../ConversationBadges";
import {
  deriveConversationBadges,
  type ConversationBadgeSource,
  type ConversationBadges,
} from "../useConversationBadges";
import type { PendingApproval, QueueItem } from "@shared/contracts/protocol";

describe("ConversationBadgeRow 组件", () => {
  afterEach(() => {
    cleanup();
  });

  it("所有字段均为 null 时返回 null（无数据源时不渲染徽章，不伪造 0 指标）", () => {
    const badges: ConversationBadges = {
      running: null,
      pendingApprovals: null,
      queued: null,
      unread: null,
      lastTerminal: null,
    };
    const { container } = render(
      <ConversationBadgeRow conversationId="c1" badges={badges} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("数值字段为 0 且 running 为 false 时不渲染任何徽章（真实零值无须提示）", () => {
    const badges: ConversationBadges = {
      running: false,
      pendingApprovals: 0,
      queued: 0,
      unread: 0,
      lastTerminal: null,
    };
    const { container } = render(
      <ConversationBadgeRow conversationId="c1" badges={badges} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("running 为 true 时渲染「运行中」徽章", () => {
    const badges: ConversationBadges = {
      running: true,
      pendingApprovals: null,
      queued: null,
      unread: null,
      lastTerminal: null,
    };
    render(<ConversationBadgeRow conversationId="c1" badges={badges} />);
    const badge = screen.getByTestId("badge-running-c1");
    expect(badge).toHaveClass("is-running");
    expect(badge).toHaveTextContent("运行中");
  });

  it("pendingApprovals > 0 时渲染「待审批 N」警示徽章", () => {
    const badges: ConversationBadges = {
      running: null,
      pendingApprovals: 3,
      queued: null,
      unread: null,
      lastTerminal: null,
    };
    render(<ConversationBadgeRow conversationId="c1" badges={badges} />);
    const badge = screen.getByTestId("badge-approvals-c1");
    expect(badge).toHaveClass("is-approval");
    expect(badge).toHaveTextContent("待审批 3");
  });

  it("queued > 0 时渲染「排队 N」徽章", () => {
    const badges: ConversationBadges = {
      running: null,
      pendingApprovals: null,
      queued: 2,
      unread: null,
      lastTerminal: null,
    };
    render(<ConversationBadgeRow conversationId="c1" badges={badges} />);
    const badge = screen.getByTestId("badge-queued-c1");
    expect(badge).toHaveClass("is-queued");
    expect(badge).toHaveTextContent("排队 2");
  });

  it("unread > 0 时渲染「未读 N」徽章", () => {
    const badges: ConversationBadges = {
      running: null,
      pendingApprovals: null,
      queued: null,
      unread: 5,
      lastTerminal: null,
    };
    render(<ConversationBadgeRow conversationId="c1" badges={badges} />);
    const badge = screen.getByTestId("badge-unread-c1");
    expect(badge).toHaveClass("is-unread");
    expect(badge).toHaveTextContent("未读 5");
  });

  it("lastTerminal 渲染对应的终态文案及状态类（completed / failed / cancelled）", () => {
    const { rerender } = render(
      <ConversationBadgeRow
        conversationId="c1"
        badges={{
          running: null,
          pendingApprovals: null,
          queued: null,
          unread: null,
          lastTerminal: { status: "completed", error: null, at: "2026-09-09T10:00:00Z" },
        }}
      />,
    );
    expect(screen.getByTestId("badge-terminal-c1")).toHaveTextContent("上次完成");
    expect(screen.getByTestId("badge-terminal-c1")).toHaveClass("badge-status-completed");

    rerender(
      <ConversationBadgeRow
        conversationId="c1"
        badges={{
          running: null,
          pendingApprovals: null,
          queued: null,
          unread: null,
          lastTerminal: { status: "failed", error: "LLM timeout", at: "2026-09-09T10:00:00Z" },
        }}
      />,
    );
    const failedBadge = screen.getByTestId("badge-terminal-c1");
    expect(failedBadge).toHaveTextContent("上次失败");
    expect(failedBadge).toHaveClass("badge-status-failed");
    expect(failedBadge).toHaveAttribute("title", "LLM timeout");
    expect(failedBadge).toHaveAttribute("aria-label", "上次失败：LLM timeout");

    rerender(
      <ConversationBadgeRow
        conversationId="c1"
        badges={{
          running: null,
          pendingApprovals: null,
          queued: null,
          unread: null,
          lastTerminal: { status: "cancelled", error: null, at: "2026-09-09T10:00:00Z" },
        }}
      />,
    );
    expect(screen.getByTestId("badge-terminal-c1")).toHaveTextContent("上次已取消");
    expect(screen.getByTestId("badge-terminal-c1")).toHaveClass("badge-status-cancelled");
  });

  it("多徽章并存时按正确次序渲染全部徽章", () => {
    const badges: ConversationBadges = {
      running: true,
      pendingApprovals: 2,
      queued: 1,
      unread: 4,
      lastTerminal: { status: "completed", error: null, at: null },
    };
    render(<ConversationBadgeRow conversationId="c1" badges={badges} />);
    expect(screen.getByTestId("badge-running-c1")).toBeInTheDocument();
    expect(screen.getByTestId("badge-approvals-c1")).toBeInTheDocument();
    expect(screen.getByTestId("badge-queued-c1")).toBeInTheDocument();
    expect(screen.getByTestId("badge-unread-c1")).toBeInTheDocument();
    expect(screen.getByTestId("badge-terminal-c1")).toBeInTheDocument();
  });
});

describe("deriveConversationBadges 数据派生", () => {
  const emptySource: ConversationBadgeSource = {
    activeTasks: null,
    activeTask: null,
    approvals: null,
    queueItems: null,
    unreadByConversation: null,
    terminalByConversation: null,
  };

  it("数据源为 null 时各派生字段为 null，不臆断为 0 或 false", () => {
    const result = deriveConversationBadges("c1", emptySource);
    expect(result.running).toBeNull();
    expect(result.pendingApprovals).toBeNull();
    expect(result.queued).toBeNull();
    expect(result.unread).toBeNull();
    expect(result.lastTerminal).toBeNull();
  });

  it("基于 activeTasks 全量集合准确判定 running", () => {
    const source: ConversationBadgeSource = {
      ...emptySource,
      activeTasks: [
        {
          project_id: "p1",
          task_id: "t1",
          conversation_id: "c1",
          engine_turn_id: "e1",
        },
      ],
    };
    expect(deriveConversationBadges("c1", source).running).toBe(true);
    expect(deriveConversationBadges("c2", source).running).toBe(false);
  });

  it("无 activeTasks 只有兼容 activeTask 时：匹配为 true，其他聊天为 null（未知）", () => {
    const source: ConversationBadgeSource = {
      ...emptySource,
      activeTasks: null,
      activeTask: {
        project_id: "p1",
        task_id: "t1",
        conversation_id: "c1",
        engine_turn_id: "e1",
      },
    };
    expect(deriveConversationBadges("c1", source).running).toBe(true);
    expect(deriveConversationBadges("c2", source).running).toBeNull();
  });

  it("approvals 按 conversation_id 精确过滤计数", () => {
    const source: ConversationBadgeSource = {
      ...emptySource,
      approvals: [
        { approval_id: "a1", conversation_id: "c1" } as PendingApproval,
        { approval_id: "a2", conversation_id: "c1" } as PendingApproval,
        { approval_id: "a3", conversation_id: "c2" } as PendingApproval,
      ],
    };
    expect(deriveConversationBadges("c1", source).pendingApprovals).toBe(2);
    expect(deriveConversationBadges("c2", source).pendingApprovals).toBe(1);
    expect(deriveConversationBadges("c3", source).pendingApprovals).toBe(0);
  });

  it("queueItems 仅统计指定会话中 status === 'queued' 项", () => {
    const source: ConversationBadgeSource = {
      ...emptySource,
      queueItems: [
        { queue_item_id: "q1", conversation_id: "c1", status: "queued" } as QueueItem,
        { queue_item_id: "q2", conversation_id: "c1", status: "withdrawn" } as QueueItem,
        { queue_item_id: "q3", conversation_id: "c2", status: "queued" } as QueueItem,
      ],
    };
    expect(deriveConversationBadges("c1", source).queued).toBe(1);
    expect(deriveConversationBadges("c2", source).queued).toBe(1);
    expect(deriveConversationBadges("c3", source).queued).toBe(0);
  });

  it("unread 与 terminalByConversation 正确映射", () => {
    const source: ConversationBadgeSource = {
      ...emptySource,
      unreadByConversation: { c1: 3 },
      terminalByConversation: {
        c1: { status: "failed", error: "network error", at: "2026-09-09T10:00:00Z" },
      },
    };
    const c1Badges = deriveConversationBadges("c1", source);
    expect(c1Badges.unread).toBe(3);
    expect(c1Badges.lastTerminal?.status).toBe("failed");
    expect(c1Badges.lastTerminal?.error).toBe("network error");

    const c2Badges = deriveConversationBadges("c2", source);
    expect(c2Badges.unread).toBe(0);
    expect(c2Badges.lastTerminal).toBeNull();
  });
});
