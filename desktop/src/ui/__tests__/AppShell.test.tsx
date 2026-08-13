import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  backend: MockDesktopBackend;
}

async function renderScenario(name: MockScenarioName): Promise<Rendered> {
  const backend = new MockDesktopBackend(name);
  const controller = createActionController(backend);
  // 与 AppController 一致：backend 事件转发进 store（queue.changed 等）
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  const present = () => presentAppShell(desktopStore.getState());
  const { rerender } = render(<AppShell vm={present()} actions={controller.actions} />);
  return { controller, rerender, present, backend };
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
    const toolToggle = screen.getByRole("button", { name: /工具调用/ });
    expect(screen.queryByText("检查项目文件")).not.toBeInTheDocument();
    fireEvent.click(toolToggle);
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

  it("disconnected：技术详情抽屉提供立即重连", async () => {
    const { controller, rerender, present } = await renderScenario("single-project");
    desktopStore.getState().setStatus("disconnected");
    rerender(<AppShell vm={present()} actions={controller.actions} />);

    // 断线横幅 + 连接药丸均指向技术详情抽屉
    expect(screen.getByRole("alert")).toHaveTextContent("与本地服务失去连接");
    fireEvent.click(screen.getByRole("button", { name: /连接状态/ }));
    // 逻辑线接入 app.reconnect 后，抽屉提供「立即重连」按钮
    const reconnectButton = screen.getByRole("button", { name: "立即重连" });
    expect(reconnectButton).toBeInTheDocument();
    fireEvent.click(reconnectButton);
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

describe("AppShell V0.2 M4 接口接线", () => {
  afterEach(() => {
    cleanup();
    desktopStore.getState().setStatus("booting");
  });

  it("gate-default：默认账号整屏账号门，登录后进入应用", async () => {
    const backend = new MockDesktopBackend("gate-default");
    const controller = createActionController(backend);
    const unsubscribe = backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    try {
      await controller.loadBootstrap();
      const present = () => presentAppShell(desktopStore.getState());
      const { rerender } = render(<AppShell vm={present()} actions={controller.actions} />);

      // 整屏账号门：默认选中上次登录账号，导航被替换
      expect(screen.getByText("欢迎回来")).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: /默认账号/ })).toHaveAttribute(
        "aria-checked",
        "true",
      );
      expect(screen.getByRole("radio", { name: /演示账号/ })).toBeInTheDocument();
      expect(screen.queryByRole("navigation")).not.toBeInTheDocument();

      // 选择演示账号 → 输入密码 → 进入
      fireEvent.click(screen.getByRole("radio", { name: /演示账号/ }));
      fireEvent.change(screen.getByLabelText("密码"), { target: { value: "demo-pass" } });
      fireEvent.click(screen.getByRole("button", { name: "进入" }));

      // 登录成功后账号门消失，进入应用（账号数据来自 account.changed）
      await waitFor(() =>
        expect(desktopStore.getState().currentAccount?.username).toBe("demo"),
      );
      rerender(<AppShell vm={present()} actions={controller.actions} />);
      expect(screen.queryByText("欢迎回来")).not.toBeInTheDocument();
      expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
      expect(screen.getByTestId("composer")).toBeInTheDocument();
    } finally {
      unsubscribe();
    }
  });

  it("onboarding-pending：非默认账号且引导未完成 → 整屏首次引导", async () => {
    await renderScenario("onboarding-pending");
    // 步骤指示器与面板标题都会出现「创建第一个项目」
    expect(screen.getByRole("heading", { name: "创建第一个项目" })).toBeInTheDocument();
    expect(screen.getAllByText("创建第一个项目")).toHaveLength(2);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("连续跳过项目与模型配置后进入主页", async () => {
    const { controller, rerender, present } = await renderScenario("onboarding-pending");

    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    fireEvent.click(screen.getByRole("button", { name: "跳过，之后再说" }));
    fireEvent.click(screen.getByRole("button", { name: "开始使用" }));

    await waitFor(() =>
      expect(desktopStore.getState().currentAccount?.onboarding_complete).toBe(true),
    );
    rerender(<AppShell vm={present()} actions={controller.actions} />);
    expect(screen.queryByText("都准备好了")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
  });

  it("引导页保存 DeepSeek Key 时写入默认端点与模型", async () => {
    const { controller, rerender, present } = await renderScenario("onboarding-pending");
    const setConfig = vi.fn().mockResolvedValue(undefined);
    const testConnection = vi.fn().mockResolvedValue("连接正常（延迟 546 ms）");
    const actions = { ...controller.actions, setConfig, testConnection };
    rerender(<AppShell vm={present()} actions={actions} />);

    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并测试" }));

    await waitFor(() => expect(testConnection).toHaveBeenCalledOnce());
    expect(setConfig).toHaveBeenCalledWith({
      engine: "deepseek",
      "dialogue.provider": "deepseek",
      "dialogue.base_url": "https://api.deepseek.com",
      "dialogue.model": "deepseek-v4-flash",
      "dialogue.api_key": "sk-test",
    });
    expect(screen.getByRole("heading", { name: "都准备好了" })).toBeInTheDocument();
  });

  it("引导页 OpenAI 兼容 API 让角色与助手使用同一模型", async () => {
    const { controller, rerender, present } = await renderScenario("onboarding-pending");
    const setConfig = vi.fn().mockResolvedValue(undefined);
    const codexApiLogin = vi.fn().mockResolvedValue(undefined);
    const testConnection = vi.fn().mockResolvedValue("连接正常（延迟 12 ms）");
    const actions = { ...controller.actions, setConfig, codexApiLogin, testConnection };
    rerender(<AppShell vm={present()} actions={actions} />);

    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    fireEvent.change(screen.getByLabelText("模型来源"), {
      target: { value: "OpenAI 兼容 API（包括 OpenAI API）" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-openai" } });
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "gpt-5.6-sol" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并测试" }));

    await waitFor(() => expect(testConnection).toHaveBeenCalledOnce());
    expect(setConfig).toHaveBeenCalledWith({
      engine: "codex",
      "dialogue.provider": "openai_compatible",
      "dialogue.base_url": "https://api.openai.com/v1",
      "dialogue.model": "gpt-5.6-sol",
      "dialogue.api_key": "sk-openai",
    });
    expect(codexApiLogin).toHaveBeenCalledWith("sk-openai");
    expect(screen.getByRole("heading", { name: "都准备好了" })).toBeInTheDocument();
  });

  it("error.reported recoverable：Toast 渲染并可关闭", async () => {
    const { controller, rerender, present } = await renderScenario("single-project");
    desktopStore.getState().applyEvents([
      {
        kind: "event",
        event: "error.reported",
        sequence: 1,
        payload: {
          code: "backend_disconnected",
          message: "Python Sidecar 已断开，正在重连…",
          severity: "recoverable",
          source: "sidecar",
        },
      },
    ]);
    rerender(<AppShell vm={present()} actions={controller.actions} />);

    const toast = screen.getByText("Python Sidecar 已断开，正在重连…");
    expect(toast).toBeInTheDocument();
    // Toast 有技术详情入口（打开技术详情抽屉）
    expect(screen.getByRole("button", { name: "查看技术详情" })).toBeInTheDocument();

    // 点击关闭后 Toast 消失
    fireEvent.click(screen.getByRole("button", { name: "关闭通知" }));
    rerender(<AppShell vm={present()} actions={controller.actions} />);
    expect(screen.queryByText("Python Sidecar 已断开，正在重连…")).not.toBeInTheDocument();
  });

  it("设置入口打开设置中心并拉取 config.get 水合表单", async () => {
    const { controller, rerender, present } = await renderScenario("single-project");

    // 顶栏右侧设置按钮打开设置中心（打开时拉取 config.get）
    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    await waitFor(() => {
      // 每次轮询重新查询：config 到达后 key 重挂载会替换 dialog 实例
      expect(screen.queryByRole("dialog", { name: "设置" })).toBeInTheDocument();
    });

    // 配置到达后模型页表单水合真实配置
    await waitFor(() => expect(desktopStore.getState().configSnapshot).not.toBeNull());
    rerender(<AppShell vm={present()} actions={controller.actions} />);
    fireEvent.click(screen.getByRole("button", { name: "角色对话模型" }));
    await waitFor(() => expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat"));
    expect(screen.getByText("当前已保存 sk-d…1234")).toBeInTheDocument();

    // Esc 关闭设置中心
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "设置" })).not.toBeInTheDocument();
    });
  });
});

describe("AppShell QueueStrip 接线（V0.2 M4）", () => {
  afterEach(() => {
    cleanup();
    desktopStore.getState().setStatus("booting");
  });

  function queueItemsInto(
    rendered: Rendered,
    rerender: (ui: React.ReactElement) => void,
    present: () => ReturnType<typeof presentAppShell>,
  ) {
    const state = desktopStore.getState();
    rendered.backend.emitQueueChanged(state.currentConversationId, [
      {
        queue_item_id: "q-1",
        account_id: "",
        conversation_id: state.currentConversationId,
        target: "character",
        text: "等你忙完再说这个",
        intent: "followup",
        position: 0,
        status: "queued",
        created_at: "2026-08-12T00:00:00+00:00",
        source_message_id: null,
      },
      {
        queue_item_id: "q-2",
        account_id: "",
        conversation_id: state.currentConversationId,
        target: "assistant",
        text: "请检查这个项目的测试",
        intent: "followup",
        position: 1,
        status: "queued",
        created_at: "2026-08-12T00:00:00+00:00",
        source_message_id: null,
      },
    ]);
    rerender(<AppShell vm={present()} actions={rendered.controller.actions} />);
  }

  it("有队列时渲染胶囊条：目标、摘要与数量", async () => {
    const rendered = await renderScenario("single-project");
    const { controller, rerender, present } = rendered;
    expect(screen.queryByRole("region", { name: /排队/ })).not.toBeInTheDocument();
    queueItemsInto(rendered, rerender, present);

    const strip = screen.getByRole("region", { name: "排队 2 条" });
    expect(strip).toBeInTheDocument();
    expect(screen.getByText("给白厄")).toBeInTheDocument();
    expect(screen.getByText("给神秘的古代机械")).toBeInTheDocument();
    expect(screen.getByText(/「等你忙完再说这个」/)).toBeInTheDocument();
    expect(screen.getByText(/「请检查这个项目的测试」/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "撤回" })).toHaveLength(2);
  });

  it("编辑：拉回输入区并撤回该条", async () => {
    const rendered = await renderScenario("single-project");
    const { controller, rerender, present } = rendered;
    queueItemsInto(rendered, rerender, present);

    fireEvent.click(screen.getAllByRole("button", { name: "编辑" })[0]);
    // 拉回输入区：async 撤回完成后 seed 写入输入框
    rerender(<AppShell vm={present()} actions={controller.actions} />);
    const composer = screen.getByTestId("composer");
    const textarea = composer.querySelector("textarea")!;
    await waitFor(() => {
      expect(textarea.value).toContain("等你忙完再说这个");
    });
    // 撤回后队列只剩一条
    rerender(<AppShell vm={present()} actions={controller.actions} />);
    expect(screen.getByRole("region", { name: "排队 1 条" })).toBeInTheDocument();
  });

  it("立即插入：优先处理该条", async () => {
    const rendered = await renderScenario("single-project");
    const { controller, rerender, present } = rendered;
    queueItemsInto(rendered, rerender, present);

    fireEvent.click(screen.getAllByRole("button", { name: "立即插入" })[1]);
    rerender(<AppShell vm={present()} actions={controller.actions} />);
    const strip = screen.getByRole("region", { name: "排队 2 条" });
    const capsules = strip.querySelectorAll(".queue-capsule");
    expect(capsules[0]?.textContent).toContain("请检查这个项目的测试");
  });
});
