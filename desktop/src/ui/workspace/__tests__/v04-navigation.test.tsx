import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../../AppShell";
import { ProjectRail } from "../../navigation/ProjectRail";
import { createMockScenario } from "../../../mocks/scenarios";
import { presentAppShell } from "../../../presenters/presenters";
import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";

async function setupScenario(name = "background-tasks") {
  const backend = new MockDesktopBackend(name as any);
  const controller = createActionController(backend);
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  return { backend, controller };
}

describe("V0.3.9 V04 导航收敛与层级优化", () => {
  afterEach(() => {
    cleanup();
    desktopStore.getState().setStatus("booting");
  });

  it("ProjectRail 移除日常聊天占位按钮，保留后台任务总览与角色库", async () => {
    const { controller } = await setupScenario("background-tasks");
    const vm = presentAppShell(desktopStore.getState());

    render(
      <ProjectRail
        navigation={vm.navigation!}
        actions={controller.actions}
      />,
    );

    expect(screen.queryByLabelText(/日常聊天/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("角色库")).toBeInTheDocument();
    expect(screen.getByLabelText("后台任务总览")).toBeInTheDocument();
  });

  it("非聊天视图隐藏发送区，且在后台有运行任务时提供返回运行中聊天入口", async () => {
    const { controller } = await setupScenario("background-tasks");
    // 切换至角色库视图
    await controller.actions.openCharacterLibrary();
    const vm = presentAppShell(desktopStore.getState());
    expect(vm.mainView).toBe("characters");

    const { rerender } = render(
      <AppShell
        vm={vm}
        actions={controller.actions}
      />,
    );

    // Composer 发送区隐藏
    expect(screen.queryByRole("textbox", { name: /消息输入/ })).not.toBeInTheDocument();

    // 渲染非聊天视图的运行任务横幅
    const banner = screen.getByTestId("non-chat-running-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent("后台有 2 个任务正在运行中");

    const returnBtn = screen.getByRole("button", { name: "返回运行中聊天" });
    fireEvent.click(returnBtn);

    // 回到 chat 模式
    expect(desktopStore.getState().mainView).toBe("chat");
  });
});
