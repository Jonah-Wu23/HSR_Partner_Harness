import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HarnessActions } from "../../../contracts/actions";
import type { ApprovalViewModel } from "../../../contracts/view-models";
import { ApprovalBar } from "../../approval/ApprovalBar";

function makeActions(overrides: Partial<HarnessActions> = {}): HarnessActions {
  return {
    createProject: vi.fn(),
    renameProject: vi.fn(),
    repairProjectPath: vi.fn(),
    selectProject: vi.fn(),
    archiveProject: vi.fn(),
    createConversation: vi.fn(),
    selectConversation: vi.fn(),
    openConversationTab: vi.fn(),
    closeConversationTab: vi.fn(),
    openConversationWindow: vi.fn(),
    renameConversation: vi.fn(),
    archiveConversation: vi.fn(),
    switchMode: vi.fn(),
    switchTheme: vi.fn(),
    submitMessage: vi.fn(),
    editQueueItem: vi.fn(),
    withdrawQueueItem: vi.fn(),
    prioritizeQueueItem: vi.fn(),
    editQueueFromStrip: vi.fn(),
    cancelTask: vi.fn(),
    resolveApproval: vi.fn(),
    setApprovalMode: vi.fn(),
    setReasoningEffort: vi.fn(),
    openCharacterLibrary: vi.fn(),
    openCharacterCreate: vi.fn(),
    openChat: vi.fn(),
    createCardDraft: vi.fn(),
    deleteCard: vi.fn(),
    exportCard: vi.fn(),
    duplicateCard: vi.fn(),
    listCards: vi.fn(),
    saveDraft: vi.fn(),
    openSettings: vi.fn(),
    openVoicePreview: vi.fn(),
    ...overrides,
  } as unknown as HarnessActions;
}

function makePending(id: string, convId: string, summary: string) {
  return {
    approval_id: id,
    conversation_id: convId,
    operation: {
      tool_kind: "shell" as const,
      command: "pytest",
      paths: [],
      patch_file_count: null,
      summary,
    },
    reason: `理由：${summary}`,
    resolving: false,
  };
}

describe("V0.3.9 V01 ApprovalBar 过滤当前聊天与全量 pending 展示", () => {
  afterEach(cleanup);

  it("当前聊天存在多项待审批时，全量渲染而非只渲染第 1 项", () => {
    const actions = makeActions();
    const approval: ApprovalViewModel = {
      mode: "request_approval",
      pending: [
        makePending("app-1", "conv-current", "命令 1"),
        makePending("app-2", "conv-current", "命令 2"),
      ],
      resolved: [],
      reviewActive: false,
      reviewText: null,
    };

    render(
      <ApprovalBar
        approval={approval}
        actions={actions}
        currentConversationId="conv-current"
      />,
    );

    expect(screen.getByText("命令 1")).toBeInTheDocument();
    expect(screen.getByText("命令 2")).toBeInTheDocument();
    const allowButtons = screen.getAllByRole("button", { name: "允许" });
    expect(allowButtons).toHaveLength(2);

    fireEvent.click(allowButtons[1]);
    expect(actions.resolveApproval).toHaveBeenCalledWith("app-2", "allow");
  });

  it("当前聊天无审批但其他聊天有审批时，渲染跨聊天待审批入口与计数", () => {
    const actions = makeActions();
    const approval: ApprovalViewModel = {
      mode: "request_approval",
      pending: [
        makePending("app-other-1", "conv-other", "其他聊天命令 1"),
        makePending("app-other-2", "conv-other", "其他聊天命令 2"),
      ],
      resolved: [],
      reviewActive: false,
      reviewText: null,
    };

    render(
      <ApprovalBar
        approval={approval}
        actions={actions}
        currentConversationId="conv-current"
      />,
    );

    expect(screen.queryByText("其他聊天命令 1")).not.toBeInTheDocument();
    expect(screen.getByText("其他聊天有 2 项待审批操作")).toBeInTheDocument();

    const jumpBtn = screen.getByRole("button", { name: "前往处理" });
    expect(jumpBtn).toBeInTheDocument();
    fireEvent.click(jumpBtn);
    expect(actions.openConversationTab).toHaveBeenCalledWith("conv-other");
  });

  it("当前聊天与其他聊天均有审批时，渲染当前全部审批并附带跨聊天提示", () => {
    const actions = makeActions();
    const approval: ApprovalViewModel = {
      mode: "request_approval",
      pending: [
        makePending("app-1", "conv-current", "当前命令"),
        makePending("app-other-1", "conv-other", "其他命令"),
      ],
      resolved: [],
      reviewActive: false,
      reviewText: null,
    };

    render(
      <ApprovalBar
        approval={approval}
        actions={actions}
        currentConversationId="conv-current"
      />,
    );

    expect(screen.getByText("当前命令")).toBeInTheDocument();
    expect(screen.getByText("其他聊天另有 1 项待审批操作")).toBeInTheDocument();
  });
});
