import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppShell } from "../AppShell";
import type { MockScenarioName } from "../../mocks/scenarios";
import { presentAppShell } from "../../presenters/presenters";
import { createActionController, type ActionController } from "../../services/actions";
import { MockDesktopBackend } from "../../services/mockDesktopBackend";
import { desktopStore } from "../../stores/desktopStore";

interface Rendered {
  controller: ActionController;
  rerender: (ui: React.ReactElement) => void;
  present: () => ReturnType<typeof presentAppShell>;
}

async function renderScenario(name: MockScenarioName): Promise<Rendered> {
  const backend = new MockDesktopBackend(name);
  const controller = createActionController(backend);
  await controller.loadBootstrap();
  const present = () => presentAppShell(desktopStore.getState());
  const { rerender } = render(<AppShell vm={present()} actions={controller.actions} />);
  return { controller, rerender, present };
}

describe("AppShell 视觉组件（Mock 场景）", () => {
  afterEach(() => {
    cleanup();
    desktopStore.getState().setStatus("booting");
  });

  it("single-project：导航、气泡与输入区完整渲染", async () => {
    const { controller, rerender, present } = await renderScenario("single-project");
    controller.actions.switchMode("chat");
    rerender(<AppShell vm={present()} actions={controller.actions} />);

    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    // 项目轨道 + 聊天栏
    expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
    expect(screen.getByText("星穹项目")).toBeInTheDocument();
    expect(screen.getByText("奥赫玛的项目聊天")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建聊天/ })).toBeEnabled();
    const conversationButton = screen.getByRole("button", { name: /奥赫玛的项目聊天/ });
    expect(conversationButton.closest(".conversation-row")?.getAttribute("role")).toBeNull();
    expect(screen.getAllByRole("button", { name: "更多操作" }).length).toBeGreaterThan(0);
    // 角色气泡与用户气泡
    expect(
      screen.getByText("好，我和你一起看。需要执行的事情交给古代机械。"),
    ).toBeInTheDocument();
    expect(screen.getByText("帮我看看这个项目")).toBeInTheDocument();
    // 顶栏搭档与输入区
    const topbarPair = document.querySelector(".topbar-pair");
    expect(topbarPair?.textContent).toContain("白厄");
    expect(topbarPair?.textContent).toContain("神秘的古代机械");
    // 会话行搭档芯片折叠为双色点，名字在 tooltip
    expect(screen.getAllByTitle("白厄 × 神秘的古代机械").length).toBeGreaterThan(0);
    expect(screen.getByTestId("composer")).toBeInTheDocument();
    // 聊天模式下工作台收起但保留在 DOM（aria-hidden），状态不丢失
    const workbench = document.querySelector(".pane-workbench");
    expect(workbench).not.toBeNull();
    expect(workbench).toHaveAttribute("aria-hidden", "true");
    expect(workbench?.className).toContain("is-closed");
    // 聊天模式能力签可见
    expect(screen.getByRole("note")).toHaveTextContent("纯聊天");
  });

  it("collaboration-running：双栏、工具卡片与取消任务", async () => {
    const { controller, rerender, present } = await renderScenario("collaboration-running");
    controller.actions.switchMode("collaboration");
    rerender(<AppShell vm={present()} actions={controller.actions} />);

    expect(screen.getByLabelText("助手工作台")).toBeInTheDocument();
    expect(screen.getByText("任务运行中")).toBeInTheDocument();
    expect(screen.getByText("检查项目文件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /取消任务/ })).toBeEnabled();
    // 运行中的聊天在“运行中”分组并有呼吸点
    expect(screen.getByText("运行中", { selector: ".chat-group-label" })).toBeInTheDocument();
  });

  it("approval-request：审批条三按钮可点击", async () => {
    await renderScenario("approval-request");

    expect(screen.getByTestId("approval-bar")).toBeInTheDocument();
    const allow = screen.getByRole("button", { name: "允许" });
    expect(screen.getByRole("button", { name: "本对话内允许" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "否决" })).toBeInTheDocument();
    fireEvent.click(allow);
    // 点击后本地收敛，不再展示待审批操作
    expect(screen.queryByRole("button", { name: "允许" })).not.toBeInTheDocument();
  });

  it("approval-full-auto：不渲染审批条", async () => {
    await renderScenario("approval-full-auto");
    expect(screen.queryByTestId("approval-bar")).not.toBeInTheDocument();
  });

  it("invalid-path：路径警告横幅且支持重新选择文件夹", async () => {
    await renderScenario("invalid-path");

    expect(screen.getByRole("alert")).toHaveTextContent("项目文件夹不可用");
    expect(screen.getByRole("button", { name: /新建聊天/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新选择文件夹" })).toBeEnabled();
  });

  it("light-theme：主题切换反映到根节点", async () => {
    const { controller, rerender, present } = await renderScenario("single-project");
    controller.actions.switchTheme("light");
    rerender(<AppShell vm={present()} actions={controller.actions} />);

    expect(screen.getByTestId("app-shell")).toHaveAttribute("data-theme", "light");
  });

  it("booting：只渲染状态页", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    desktopStore.getState().setStatus("booting");
    render(<AppShell vm={presentAppShell(desktopStore.getState())} actions={controller.actions} />);

    expect(screen.getByText("初始化中…")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("empty：保留导航骨架，不降级为整页状态页", async () => {
    await renderScenario("empty");

    expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
    expect(screen.getByText("HSR Partner Harness")).toBeInTheDocument();
    expect(screen.getByText("还没有项目")).toBeInTheDocument();
    expect(screen.queryByText("暂无打开的项目")).not.toBeInTheDocument();
  });
});
