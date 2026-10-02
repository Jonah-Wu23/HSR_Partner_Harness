import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AppShell } from "../AppShell";
import type { HostEvent } from "../../contracts/protocol";
import type { MockScenarioName } from "../../mocks/scenarios";
import { MOCK_STREAM_ID, createMockScenario } from "../../mocks/scenarios";
import { presentAppShell } from "../../presenters/presenters";
import { createActionController, type ActionController } from "../../services/actions";
import { MOCK_ACCOUNT_PASSWORD, MockDesktopBackend } from "../../services/mockDesktopBackend";
import { desktopStore } from "../../stores/desktopStore";

interface Rendered {
  controller: ActionController;
  backend: MockDesktopBackend;
  /** AppShell 是受控组件：store 变化后用最新视图模型重渲。 */
  refresh: () => void;
}

async function renderScenario(name: MockScenarioName): Promise<Rendered> {
  const backend = new MockDesktopBackend(name);
  const controller = createActionController(backend);
  // 与 AppController 一致：backend 事件转发进 store（queue.changed 等）
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  const shell = () => (
    <AppShell vm={presentAppShell(desktopStore.getState())} actions={controller.actions} backend={backend} />
  );
  const { rerender } = render(shell());
  return { controller, backend, refresh: () => rerender(shell()) };
}

function paramsOf(backend: MockDesktopBackend, method: string) {
  return backend.recordedRequests.filter((request) => request.method === method).map((request) => request.params);
}

/** MockDesktopBackend 拒绝 config.test_connection 的原文（错误码 mock_unsupported）。 */
const MOCK_TEST_CONNECTION_ERROR =
  "Mock 后端不连接真实对话服务，无法测试连接；请在 Tauri + Python Sidecar 中联调";

/** 打开设置中心的角色对话模型页，等 config.get 的结果水合表单。 */
async function openModelSettings(): Promise<MockDesktopBackend> {
  const { backend, refresh } = await renderScenario("single-project");
  fireEvent.click(screen.getByRole("button", { name: "设置" }));
  await waitFor(() => expect(desktopStore.getState().configSnapshot).not.toBeNull());
  refresh();
  fireEvent.click(screen.getByRole("button", { name: "角色对话模型" }));
  // 已保存 Key 的提示只来自 config.get，出现即说明表单已用真实配置水合
  expect(await screen.findByText("当前已保存 sk-d…1234")).toBeInTheDocument();
  expect(paramsOf(backend, "config.get")).toEqual([{}]);
  return backend;
}

/** Rust 宿主合成的连接事件：带连接代次 stream_id，不带序号。 */
function hostEvent(event: HostEvent["event"], payload: Record<string, unknown>, streamId = MOCK_STREAM_ID): HostEvent {
  return { kind: "event", event, stream_id: streamId, payload };
}

afterEach(() => {
  cleanup();
  desktopStore.setState(desktopStore.getInitialState(), true);
});

describe("AppShell 按 mock 场景渲染", () => {
  it("single-project：导航、气泡与输入区完整渲染", async () => {
    const { controller, refresh } = await renderScenario("single-project");
    await controller.actions.switchMode("chat");
    refresh();

    expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
    expect(screen.getByText("星穹项目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /奥赫玛的项目聊天/, current: "page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建聊天/ })).toBeEnabled();
    expect(screen.getAllByRole("button", { name: "更多操作" }).length).toBeGreaterThan(0);
    // 角色气泡与用户气泡
    expect(
      screen.getByText("好，我和你一起看。需要执行的事情交给古代机械。"),
    ).toBeInTheDocument();
    expect(screen.getByText("帮我看看这个项目")).toBeInTheDocument();
    // 顶栏显示当前搭档；会话行的搭档名字在 tooltip
    expect(screen.getByRole("banner")).toHaveTextContent(/白厄.*神秘的古代机械/);
    expect(screen.getAllByTitle("白厄 × 神秘的古代机械").length).toBeGreaterThan(0);
    expect(screen.getByTestId("composer")).toBeInTheDocument();
    // 聊天模式下工作台收起但保留在 DOM（aria-hidden），状态不丢失
    expect(screen.getByLabelText("助手工作台")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("note")).toHaveTextContent("纯聊天");
  });

  it("collaboration-running：双栏、工具卡片与取消任务", async () => {
    const { controller, refresh } = await renderScenario("collaboration-running");
    await controller.actions.switchMode("collaboration");
    refresh();

    expect(screen.getByLabelText("助手工作台")).not.toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("任务运行中")).toBeInTheDocument();
    const toolToggle = screen.getByRole("button", { name: /工具调用/ });
    expect(screen.queryByText("检查项目文件")).not.toBeInTheDocument();
    fireEvent.click(toolToggle);
    expect(screen.getByText("检查项目文件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /取消任务/ })).toBeEnabled();
    // 运行中的聊天归入「运行中」分组
    expect(
      within(screen.getByRole("region", { name: "运行中" })).getByRole("button", { name: /奥赫玛的项目聊天/ }),
    ).toBeInTheDocument();
  });

  it.each([
    ["允许", "allow"],
    ["本对话内允许", "allow_for_conversation"],
    ["否决", "deny"],
  ])("approval-request：「%s」发出 %s 裁决，收到 approval.resolved 后审批条移除", async (buttonName, decision) => {
    const { backend, refresh } = await renderScenario("approval-request");
    expect(screen.getByTestId("approval-bar")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: buttonName }));
    await waitFor(() =>
      expect(paramsOf(backend, "approval.resolve")).toEqual([{ approval_id: "approval-1", decision }]),
    );
    // 审批条完全由 store 的 pending 驱动，approval.resolved 到达后才移除。
    await waitFor(() => expect(presentAppShell(desktopStore.getState()).approval.pending).toEqual([]));
    refresh();
    expect(screen.queryByRole("button", { name: buttonName })).not.toBeInTheDocument();
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
    const { controller, refresh } = await renderScenario("single-project");
    controller.actions.switchTheme("light");
    refresh();

    expect(screen.getByTestId("app-shell")).toHaveAttribute("data-theme", "light");
  });

  it("disconnected：技术详情抽屉的立即重连重启本地服务并回到启动状态", async () => {
    const { refresh } = await renderScenario("single-project");
    desktopStore.getState().setStatus("disconnected");
    refresh();

    // 断线横幅 + 连接药丸均指向技术详情抽屉
    expect(screen.getByRole("alert")).toHaveTextContent("与本地服务失去连接");
    fireEvent.click(screen.getByRole("button", { name: /连接状态/ }));

    // mock 宿主模拟一次断开与恢复，恢复事件让 store 进入 booting 等待重新水合
    fireEvent.click(screen.getByRole("button", { name: "立即重连" }));
    await waitFor(() => expect(desktopStore.getState().status).toBe("booting"));
  });

  it("disconnected：宿主断连事件下药丸、横幅与 Toast 一致，恢复后撤回断连通知", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    const snapshot = createMockScenario("single-project").snapshot;
    // 快照与宿主事件都带连接代次 stream_id，事件按代次校验后才进 store
    desktopStore.getState().hydrate({ ...snapshot, stream_id: "1", sequence: 10 });
    const shell = () => (
      <AppShell vm={presentAppShell(desktopStore.getState())} actions={controller.actions} backend={backend} />
    );
    const { rerender } = render(shell());
    expect(screen.getByRole("button", { name: /连接状态：已连接/ })).toBeInTheDocument();

    // Sidecar 被杀：Rust 同一批连发 connection.status 与 error.reported
    desktopStore.getState().applyEvents([
      hostEvent("connection.status", { status: "disconnected", stream_id: "1" }, "1"),
      hostEvent(
        "error.reported",
        {
          code: "backend_disconnected",
          message: "Python Sidecar 已断开，正在重连…",
          severity: "recoverable",
          source: "sidecar",
        },
        "1",
      ),
    ]);
    rerender(shell());

    // 同一帧里不得同时出现「已连接药丸」与「已断开 Toast」两种相反结论
    expect(screen.getByText("Python Sidecar 已断开，正在重连…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /连接状态：连接已断开/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /连接状态：已连接/ })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("与本地服务失去连接");

    // 恢复：断开期间的瞬时通知随恢复撤回，重新水合前不显示「已连接」
    desktopStore.getState().applyEvents([
      hostEvent("connection.status", { status: "connected", stream_id: "2" }, "2"),
    ]);
    rerender(shell());
    expect(screen.queryByText("Python Sidecar 已断开，正在重连…")).not.toBeInTheDocument();
    expect(desktopStore.getState().status).toBe("booting");
    expect(screen.queryByRole("button", { name: /连接状态：已连接/ })).not.toBeInTheDocument();
  });

  it("booting：只渲染状态页", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    desktopStore.getState().setStatus("booting");
    render(<AppShell vm={presentAppShell(desktopStore.getState())} actions={controller.actions} backend={backend} />);

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

describe("AppShell 账号门、首次引导与设置中心", () => {
  it("gate-default：默认账号整屏账号门，登录其他账号后进入应用", async () => {
    const { backend, refresh } = await renderScenario("gate-default");

    // 整屏账号门：默认选中上次登录账号，导航被替换
    expect(screen.getByRole("heading", { name: "欢迎回来" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /默认账号/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /演示账号/ }));
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: MOCK_ACCOUNT_PASSWORD } });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));

    // 登录成功后账号门消失，进入应用（账号数据来自 account.changed）
    await waitFor(() => expect(desktopStore.getState().currentAccount?.username).toBe("demo"));
    refresh();
    expect(paramsOf(backend, "account.login")).toEqual([
      { account_id: "demo-account", password: MOCK_ACCOUNT_PASSWORD },
    ]);
    expect(screen.queryByRole("heading", { name: "欢迎回来" })).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
    expect(screen.getByTestId("composer")).toBeInTheDocument();
  });

  it("gate-default：未设密码的默认账号以空密码登录后账号门让开", async () => {
    const { backend, refresh } = await renderScenario("gate-default");

    // 默认账号被默认选中：不填密码，「进入」可用，空密码原样交给后端校验
    fireEvent.click(screen.getByRole("button", { name: "进入" }));

    await waitFor(() => expect(desktopStore.getState().currentAccount?.last_login_at).not.toBeNull());
    refresh();
    expect(paramsOf(backend, "account.login")).toEqual([{ account_id: "default-local", password: "" }]);
    // 登录后账号身份仍是默认账号（username=default），账号门照样让开
    expect(desktopStore.getState().currentAccount?.username).toBe("default");
    expect(screen.queryByRole("heading", { name: "欢迎回来" })).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
  });

  it("账号门：后端拒绝登录时就地显示错误，切到注册表单后清掉", async () => {
    await renderScenario("gate-default");

    fireEvent.click(screen.getByRole("radio", { name: /演示账号/ }));
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "wrong-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("密码错误");

    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));
    expect(screen.getByRole("heading", { name: "注册新账号" })).toBeInTheDocument();
    expect(screen.queryByText("密码错误")).not.toBeInTheDocument();
  });

  it("onboarding-pending：非默认账号且引导未完成时显示整屏首次引导", async () => {
    await renderScenario("onboarding-pending");
    expect(screen.getByRole("heading", { name: "创建第一个项目" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("连续跳过项目与模型配置后完成引导并进入主页", async () => {
    const { backend, refresh } = await renderScenario("onboarding-pending");

    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    fireEvent.click(screen.getByRole("button", { name: "跳过，之后再说" }));
    fireEvent.click(screen.getByRole("button", { name: "开始使用" }));

    await waitFor(() => expect(desktopStore.getState().currentAccount?.onboarding_complete).toBe(true));
    refresh();
    expect(paramsOf(backend, "account.onboarding_complete")).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "都准备好了" })).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "项目轨道" })).toBeInTheDocument();
  });

  // mock 后端不连真实对话服务，config.test_connection 报 mock_unsupported：
  // 保存先写 config.set，再测试连接，失败原文留在原页面。
  it.each([
    {
      provider: "DeepSeek",
      fill: () => {
        fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-test" } });
      },
      updates: {
        "dialogue.provider": "deepseek",
        "dialogue.base_url": "https://api.deepseek.com",
        "dialogue.model": "deepseek-v4-flash",
        "dialogue.api_key": "sk-test",
      },
    },
    {
      provider: "OpenAI 兼容 API",
      fill: () => {
        fireEvent.change(screen.getByLabelText("模型来源"), { target: { value: "openai_compatible" } });
        fireEvent.change(screen.getByLabelText("Base URL"), {
          target: { value: "https://gateway.example.com/v1" },
        });
        fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-openai" } });
        fireEvent.change(screen.getByLabelText("模型"), { target: { value: "gpt-5.6-sol" } });
      },
      updates: {
        "dialogue.provider": "openai_compatible",
        "dialogue.base_url": "https://gateway.example.com/v1",
        "dialogue.model": "gpt-5.6-sol",
        "dialogue.api_key": "sk-openai",
      },
    },
  ])("引导页保存 $provider：只写 dialogue.* 再测试连接，连接失败时停在模型步骤", async ({ fill, updates }) => {
    const { backend } = await renderScenario("onboarding-pending");

    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    fill();
    fireEvent.click(screen.getByRole("button", { name: "保存并测试" }));

    expect(await screen.findByText(MOCK_TEST_CONNECTION_ERROR)).toBeInTheDocument();
    expect(paramsOf(backend, "config.set")).toEqual([{ updates }]);
    expect(backend.recordedRequests.map((request) => request.method).slice(-2)).toEqual([
      "config.set",
      "config.test_connection",
    ]);
    expect(screen.getByRole("heading", { name: "配置角色模型" })).toBeInTheDocument();
  });

  it("error.reported recoverable：Toast 可打开技术详情，也可关闭", async () => {
    const { refresh } = await renderScenario("single-project");
    desktopStore.getState().applyEvents([
      hostEvent("error.reported", {
        code: "backend_disconnected",
        message: "Python Sidecar 已断开，正在重连…",
        severity: "recoverable",
        source: "sidecar",
      }),
    ]);
    refresh();

    const toast = screen.getByText("Python Sidecar 已断开，正在重连…").parentElement!;
    fireEvent.click(within(toast).getByRole("button", { name: "查看技术详情" }));
    expect(screen.getByRole("dialog", { name: "技术详情" })).toBeInTheDocument();

    fireEvent.click(within(toast).getByRole("button", { name: "关闭通知" }));
    refresh();
    expect(toast).not.toBeInTheDocument();
  });

  it("设置入口打开设置中心并拉取 config.get 水合表单，Esc 关闭", async () => {
    await openModelSettings();

    expect(screen.getByLabelText("模型")).toHaveValue("deepseek-chat");

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "设置" })).not.toBeInTheDocument());
  });

  it.each([
    {
      change: "DeepSeek 模型与推理等级",
      edit: () => {
        fireEvent.change(screen.getByLabelText("模型"), { target: { value: "deepseek-reasoner" } });
        fireEvent.change(screen.getByLabelText("推理等级"), { target: { value: "medium" } });
      },
      updates: {
        "dialogue.provider": "deepseek",
        "dialogue.base_url": "https://api.deepseek.com",
        "dialogue.model": "deepseek-reasoner",
        "dialogue.reasoning_effort": "medium",
      },
    },
    {
      change: "切到 OpenAI 兼容 API",
      edit: () => {
        fireEvent.change(screen.getByLabelText("服务商"), { target: { value: "openai_compatible" } });
      },
      updates: {
        "dialogue.provider": "openai_compatible",
        "dialogue.base_url": "https://api.openai.com/v1",
        "dialogue.model": "gpt-5.6-sol",
      },
    },
  ])("设置页保存 $change：config.set 写入对应 dialogue.* 后测试连接并显示结果", async ({ edit, updates }) => {
    const backend = await openModelSettings();

    edit();
    fireEvent.click(screen.getByRole("button", { name: "保存并测试" }));

    expect(await screen.findByText(MOCK_TEST_CONNECTION_ERROR)).toBeInTheDocument();
    expect(paramsOf(backend, "config.set")).toEqual([{ updates }]);
    expect(paramsOf(backend, "config.test_connection")).toEqual([{}]);
  });
});

describe("AppShell 排队条、多搭档与音色直达", () => {
  function queueItemsInto(rendered: Rendered) {
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
        error: null,
        created_at: "2026-08-12T00:00:00+00:00",
        source_message_id: null,
        origin: "desktop",
        remote_device_key: null,
        remote_device_name: null,
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
        error: null,
        created_at: "2026-08-12T00:00:00+00:00",
        source_message_id: null,
        origin: "desktop",
        remote_device_key: null,
        remote_device_name: null,
      },
    ]);
    rendered.refresh();
  }

  it("排队条「编辑」撤回该条并把原文拉回输入区", async () => {
    const rendered = await renderScenario("single-project");
    queueItemsInto(rendered);

    fireEvent.click(screen.getAllByRole("button", { name: "编辑" })[0]);
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "消息输入" })).toHaveValue("等你忙完再说这个"),
    );
    expect(paramsOf(rendered.backend, "queue.withdraw")).toEqual([{ queue_item_id: "q-1" }]);
    rendered.refresh();
    expect(screen.getByRole("region", { name: "排队 1 条" })).toBeInTheDocument();
  });

  it("排队条「立即插入」把该条移到队首", async () => {
    const rendered = await renderScenario("single-project");
    queueItemsInto(rendered);

    fireEvent.click(screen.getAllByRole("button", { name: "立即插入" })[1]);
    await waitFor(() =>
      expect(paramsOf(rendered.backend, "queue.prioritize")).toEqual([{ queue_item_id: "q-2" }]),
    );
    rendered.refresh();
    const capsules = within(screen.getByRole("region", { name: "排队 2 条" })).getAllByRole("listitem");
    expect(capsules[0]).toHaveTextContent("请检查这个项目的测试");
  });

  it("multi-pair：会话与顶栏显示各自搭档，新建聊天可选择搭档", async () => {
    const { controller, backend, refresh } = await renderScenario("multi-pair");
    expect(screen.getByTestId("app-shell")).toHaveAttribute("data-pair", "firefly_sam");

    // 列表中三个会话分别显示对应搭档信息
    expect(screen.getByTitle("白厄 × 神秘的古代机械")).toBeInTheDocument();
    expect(screen.getByTitle("流萤 × 萨姆")).toBeInTheDocument();
    expect(screen.getByTitle("三月七 × 第四面镜")).toBeInTheDocument();
    // 顶栏是当前选中的流萤会话
    expect(screen.getByRole("banner")).toHaveTextContent(/流萤.*萨姆/);

    // 切到三月七会话
    await controller.actions.selectConversation("conv-march7");
    refresh();
    expect(screen.getByTestId("app-shell")).toHaveAttribute("data-pair", "march7_fourth_mirror");
    expect(screen.getByLabelText("角色区")).toHaveTextContent("三月七");
    expect(screen.getByLabelText("助手工作台")).toHaveTextContent("第四面镜");

    // 新建聊天先选择搭档
    fireEvent.click(screen.getByRole("button", { name: /新建聊天/ }));
    const menu = screen.getByRole("menu", { name: "选择搭档新建聊天" });
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("白厄 × 神秘的古代机械"),
      expect.stringContaining("流萤 × 萨姆"),
      expect.stringContaining("三月七 × 第四面镜"),
    ]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: /流萤 × 萨姆/ }));
    await waitFor(() =>
      expect(paramsOf(backend, "conversation.create")).toEqual([
        expect.objectContaining({ pair_id: "firefly_sam" }),
      ]),
    );
  });

  it("会话的 pair_id 不在搭档列表中时照常渲染，并以 pair_id 标注", async () => {
    const { refresh } = await renderScenario("single-project");
    const scenario = createMockScenario("single-project").snapshot;
    const [firstProject] = scenario.projects;
    desktopStore.getState().hydrate({
      ...scenario,
      projects: [
        {
          ...firstProject,
          conversations: [
            { ...firstProject.conversations[0], pair_id: "unknown_custom_pair", title: "未知搭档的聊天" },
          ],
        },
      ],
      current_conversation_id: firstProject.conversations[0].conversation_id,
    });
    refresh();
    expect(screen.getByRole("button", { name: /未知搭档的聊天/, current: "page" })).toBeInTheDocument();
    expect(screen.getByTitle("unknown_custom_pair")).toBeInTheDocument();
  });

  it("从角色库直达语音页的预选卡在关闭设置后清空，从齿轮重新打开不残留", async () => {
    const { controller, refresh } = await renderScenario("single-project");

    // 进入角色库，点击第一张可配置用户卡的「配置音色」直达语音页
    await controller.actions.openCharacterLibrary();
    refresh();
    const configureButtons = await screen.findAllByTitle("配置音色");
    expect(configureButtons.length).toBeGreaterThan(0);
    fireEvent.click(configureButtons[0]);

    // 直达后设置中心打开且预选该卡（列表首张可配置卡为 card-draft-001）
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "设置" })).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("character-voice-select")).toHaveValue("card-draft-001"),
    );

    // Esc 关闭后从顶栏齿轮重新打开：预选卡不得残留
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "设置" })).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "设置" })).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByTestId("character-voice-select")).toHaveValue(""));
  });
});
