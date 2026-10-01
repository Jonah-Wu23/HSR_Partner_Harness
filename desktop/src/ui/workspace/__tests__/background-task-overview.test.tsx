import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MockScenarioName } from "../../../mocks/scenarios";
import { presentAppShell } from "../../../presenters/presenters";
import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";
import { BackgroundTaskOverview } from "../../navigation/BackgroundTaskOverview";

async function renderOverview(scenario: MockScenarioName, isOpen = true) {
  const backend = new MockDesktopBackend(scenario);
  const controller = createActionController(backend);
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  const onClose = vi.fn();
  const { container } = render(
    <BackgroundTaskOverview
      projects={presentAppShell(desktopStore.getState()).navigation!.projects}
      actions={controller.actions}
      isOpen={isOpen}
      onClose={onClose}
    />,
  );
  return { backend, container, onClose };
}

describe("BackgroundTaskOverview 跨聊天后台任务总览", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it("未打开时不渲染", async () => {
    const { container } = await renderOverview("background-tasks", false);
    expect(container.firstChild).toBeNull();
  });

  it("没有运行中的任务时显示空状态", async () => {
    await renderOverview("single-project");
    expect(screen.getByText("当前没有正在运行的后台任务")).toBeInTheDocument();
  });

  it("汇总各项目运行中的聊天，前往该聊天会切换项目并打开聊天", async () => {
    const { backend, onClose } = await renderOverview("background-tasks");

    expect(screen.getByText("2 个运行中")).toBeInTheDocument();
    expect(screen.getByText("星穹项目：长世界书校对")).toBeInTheDocument();
    expect(screen.getByText("流萤的甜点配方")).toBeInTheDocument();
    expect(screen.queryByText("奥赫玛的项目聊天")).not.toBeInTheDocument();

    const jumpButtons = screen.getAllByRole("button", { name: "前往该聊天" });
    expect(jumpButtons).toHaveLength(2);
    fireEvent.click(jumpButtons[1]);

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      const methods = backend.recordedRequests.map((request) => request.method);
      expect(methods).toEqual(expect.arrayContaining(["project.select", "conversation.open"]));
    });
    expect(backend.recordedRequests.find((request) => request.method === "project.select")?.params).toEqual({
      project_id: "project-2",
    });
    expect(backend.recordedRequests.find((request) => request.method === "conversation.open")?.params).toMatchObject({
      conversation_id: "conv-3",
    });
  });
});
