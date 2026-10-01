import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppShell } from "../../AppShell";
import { presentAppShell } from "../../../presenters/presenters";
import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";

/** background-tasks 场景：星穹项目的 conv-2 与日常项目的 conv-3 各有一个运行中的任务。 */
async function renderBackgroundTasks() {
  const backend = new MockDesktopBackend("background-tasks");
  const controller = createActionController(backend);
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  const shell = () => (
    <AppShell vm={presentAppShell(desktopStore.getState())} actions={controller.actions} backend={backend} />
  );
  const { rerender } = render(shell());
  return { backend, refresh: () => rerender(shell()) };
}

describe("项目轨道入口与非聊天视图", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it("后台任务总览入口打开跨聊天总览", async () => {
    await renderBackgroundTasks();

    fireEvent.click(screen.getByRole("button", { name: "后台任务总览" }));
    expect(screen.getByRole("dialog", { name: "跨聊天后台任务总览" })).toHaveTextContent("2 个运行中");
  });

  it("角色库视图隐藏发送区，有运行中任务时可返回运行中的聊天", async () => {
    const { backend, refresh } = await renderBackgroundTasks();

    fireEvent.click(screen.getByRole("button", { name: "角色库" }));
    await waitFor(() => expect(desktopStore.getState().mainView).toBe("characters"));
    refresh();

    expect(screen.queryByRole("textbox", { name: "消息输入" })).not.toBeInTheDocument();
    expect(screen.getByTestId("non-chat-running-banner")).toHaveTextContent("后台有 2 个任务正在运行中");

    fireEvent.click(screen.getByRole("button", { name: "返回运行中聊天" }));
    expect(desktopStore.getState().mainView).toBe("chat");
    await waitFor(() => {
      const open = backend.recordedRequests.find((request) => request.method === "conversation.open");
      expect(open?.params).toMatchObject({ conversation_id: "conv-2" });
    });
  });
});
