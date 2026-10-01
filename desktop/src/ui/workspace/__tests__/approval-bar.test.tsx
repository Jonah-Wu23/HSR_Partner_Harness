import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { presentAppShell } from "../../../presenters/presenters";
import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";
import { ApprovalBar } from "../../approval/ApprovalBar";

/** background-tasks 场景：conv-1 有 1 项待审批，conv-3 有 2 项，conv-2 没有。 */
async function renderApprovalBar(currentConversationId: string) {
  const backend = new MockDesktopBackend("background-tasks");
  const controller = createActionController(backend);
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  render(
    <ApprovalBar
      approval={presentAppShell(desktopStore.getState()).approval}
      actions={controller.actions}
      currentConversationId={currentConversationId}
    />,
  );
  return backend;
}

describe("ApprovalBar 按当前聊天过滤待审批", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it("当前聊天的待审批全部渲染，其他聊天只给计数", async () => {
    const backend = await renderApprovalBar("conv-3");

    expect(screen.getByText("写入甜点配方")).toBeInTheDocument();
    expect(screen.getByText("删除旧文件")).toBeInTheDocument();
    expect(screen.queryByText("当前聊天里的测试命令")).not.toBeInTheDocument();
    expect(screen.getByText("其他聊天另有 1 项待审批操作")).toBeInTheDocument();

    const allowButtons = screen.getAllByRole("button", { name: "允许" });
    expect(allowButtons).toHaveLength(2);
    fireEvent.click(allowButtons[1]);
    await waitFor(() => {
      const resolves = backend.recordedRequests.filter((request) => request.method === "approval.resolve");
      expect(resolves.map((request) => request.params)).toEqual([
        { approval_id: "approval-other-2", decision: "allow" },
      ]);
    });
  });

  it("当前聊天没有待审批时只显示跨聊天入口，前往处理打开对应聊天", async () => {
    const backend = await renderApprovalBar("conv-2");

    expect(screen.queryByRole("button", { name: "允许" })).not.toBeInTheDocument();
    expect(screen.getByText("其他聊天有 3 项待审批操作")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "前往处理" }));
    await waitFor(() => {
      const open = backend.recordedRequests.find((request) => request.method === "conversation.open");
      expect(open?.params).toMatchObject({ conversation_id: "conv-1" });
    });
  });
});
