import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExtendedChatTabsViewModel } from "../../ChatTabs";
import { ChatTabs } from "../../ChatTabs";

describe("V0.3.9 V01 未读徽章与完成反馈", () => {
  afterEach(cleanup);

  it("ChatTabs 在 unreadCount > 0 时渲染未读徽章，<= 0 或无数据时不渲染", () => {
    const tabs: ExtendedChatTabsViewModel[] = [
      {
        conversationId: "c-1",
        title: "聊天 1",
        isRunning: false,
        isQueued: false,
        isWaitingApproval: false,
        isActive: true,
        unreadCount: 5,
      },
      {
        conversationId: "c-2",
        title: "聊天 2",
        isRunning: false,
        isQueued: false,
        isWaitingApproval: false,
        isActive: false,
        unreadCount: 0,
      },
      {
        conversationId: "c-3",
        title: "聊天 3",
        isRunning: false,
        isQueued: false,
        isWaitingApproval: false,
        isActive: false,
      },
    ];

    render(
      <ChatTabs
        tabs={tabs}
        onSelect={vi.fn()}
        onClose={vi.fn()}
        onOpenWindow={vi.fn()}
      />,
    );

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("ChatTabs 在 isCompleted 为 true 时渲染已完成状态点", () => {
    const tabs: ExtendedChatTabsViewModel[] = [
      {
        conversationId: "c-1",
        title: "完成的聊天",
        isRunning: false,
        isQueued: false,
        isWaitingApproval: false,
        isActive: true,
        isCompleted: true,
      },
    ];

    const { container } = render(
      <ChatTabs
        tabs={tabs}
        onSelect={vi.fn()}
        onClose={vi.fn()}
        onOpenWindow={vi.fn()}
      />,
    );

    expect(container.querySelector(".chat-tab-dot.is-completed")).not.toBeNull();
  });
});
