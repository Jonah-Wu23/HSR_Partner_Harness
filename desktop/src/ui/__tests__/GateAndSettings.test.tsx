import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountGate } from "../gate/AccountGate";
import { Onboarding } from "../gate/Onboarding";
import { SettingsCenter } from "../settings/SettingsCenter";

afterEach(cleanup);

describe("AccountGate", () => {
  const accounts = [
    { accountId: "a1", displayName: "吴 Jonah", isLastLogin: true },
    { accountId: "a2", displayName: "测试账号", isLastLogin: false },
  ];

  it("默认选中上次登录账号，输入密码后提交登录", () => {
    const onLogin = vi.fn();
    render(<AccountGate accounts={accounts} error={null} busy={false} onLogin={onLogin} onRegister={() => {}} />);

    const selected = screen.getByRole("radio", { name: /吴 Jonah/ });
    expect(selected).toHaveAttribute("aria-checked", "true");

    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "1234" } });
    fireEvent.click(screen.getByRole("button", { name: "进入" }));
    expect(onLogin).toHaveBeenCalledWith("a1", "1234");
  });

  it("切换到注册表单并校验两次密码一致", () => {
    const onRegister = vi.fn();
    render(<AccountGate accounts={[]} error={null} busy={false} onLogin={() => {}} onRegister={onRegister} />);

    fireEvent.click(screen.getByRole("button", { name: /注册新账号/ }));
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "新伙伴" } });
    fireEvent.change(screen.getByLabelText(/密码（至少 4 位）/), { target: { value: "abcd" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "abce" } });
    expect(screen.getByRole("alert")).toHaveTextContent("不一致");
    expect(screen.getByRole("button", { name: "注册并进入" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "abcd" } });
    fireEvent.click(screen.getByRole("button", { name: "注册并进入" }));
    expect(onRegister).toHaveBeenCalledWith("新伙伴", "abcd");
  });

  it("就地显示后端错误", () => {
    render(<AccountGate accounts={accounts} error="密码不对" busy={false} onLogin={() => {}} onRegister={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("密码不对");
  });
});

describe("Onboarding", () => {
  it("三步推进，配置页可跳过", async () => {
    const onCreateProject = vi.fn().mockResolvedValue(true);
    const onFinish = vi.fn();
    render(
      <Onboarding
        characterName="白厄"
        assistantName="机枢"
        onCreateProject={onCreateProject}
        onSaveModelConfig={vi.fn().mockResolvedValue("连接正常（延迟 120 ms）")}
        onFinish={onFinish}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "选择文件夹" }));
    expect(onCreateProject).toHaveBeenCalled();
    expect(await screen.findByText("配置角色模型")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "跳过，之后再说" }));
    expect(screen.getByText("都准备好了")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "开始使用" }));
    expect(onFinish).toHaveBeenCalled();
  });

  it("角色模型连接成功后自动进入完成步骤", async () => {
    const onSaveModelConfig = vi.fn().mockResolvedValue("连接正常（延迟 546 ms）");
    render(
      <Onboarding
        characterName="白厄"
        assistantName="机枢"
        onCreateProject={vi.fn().mockResolvedValue(true)}
        onSaveModelConfig={onSaveModelConfig}
        onFinish={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并测试" }));

    expect(await screen.findByRole("heading", { name: "都准备好了" })).toBeInTheDocument();
    expect(onSaveModelConfig).toHaveBeenCalledWith({ provider: "DeepSeek", apiKey: "sk-test" });
  });
});

function renderSettings(overrides: Partial<Parameters<typeof SettingsCenter>[0]> = {}) {
  const props: Parameters<typeof SettingsCenter>[0] = {
    open: true,
    page: "model",
    onPageChange: vi.fn(),
    onClose: vi.fn(),
    account: { displayName: "吴 Jonah" },
    coding: { engine: "codex", codex: { status: "logged_out" } },
    model: {
      provider: "DeepSeek",
      model: "deepseek-reasoner",
      baseUrl: "https://api.deepseek.com",
      apiKeyMasked: "sk-····",
      reasoningEffort: "medium",
    },
    voice: {
      enabled: true,
      baseUrl: "https://dashscope.aliyuncs.com",
      apiKeyMasked: "sk-····",
      asrModel: "paraformer",
      ttsModel: "cosyvoice",
      characterVoice: "longxiaochun",
      assistantVoice: "longwan",
      vadEnabled: false,
      vadStatus: "ready",
    },
    modelTest: { state: "idle" },
    voicePreview: { state: "idle" },
    onSaveProfile: vi.fn(),
    onChangePassword: vi.fn(),
    onLogout: vi.fn(),
    onSelectEngine: vi.fn(),
    onCodexOAuthStart: vi.fn(),
    onCodexLogout: vi.fn(),
    onCodexApiLogin: vi.fn(),
    onSaveModel: vi.fn(),
    onTestModel: vi.fn(),
    onSaveVoice: vi.fn(),
    onPreviewVoice: vi.fn(),
    ...overrides,
  };
  render(<SettingsCenter {...props} />);
  return props;
}

describe("SettingsCenter", () => {
  it("栏目导航切换页面，Esc 关闭", () => {
    const props = renderSettings();
    expect(screen.getByRole("dialog", { name: "设置" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "语音" }));
    expect(props.onPageChange).toHaveBeenCalledWith("voice");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalled();
  });

  it("模型页未修改时保存按钮禁用，修改后可保存并测试", () => {
    const props = renderSettings();
    const save = screen.getByRole("button", { name: "保存并测试" });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "deepseek-chat" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    expect(props.onSaveModel).toHaveBeenCalledWith(
      expect.objectContaining({ model: "deepseek-chat", apiKey: undefined }),
    );
    expect(props.onTestModel).toHaveBeenCalled();
  });

  it("编程助手页未登录时提供浏览器登录与 API Key 两条路", () => {
    const props = renderSettings({ page: "coding" });
    expect(screen.getByRole("button", { name: "通过浏览器登录" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "通过浏览器登录" }));
    expect(props.onCodexOAuthStart).toHaveBeenCalled();
  });

  it("语音页关闭总开关后隐藏细项", () => {
    renderSettings({
      page: "voice",
      voice: {
        enabled: false,
        baseUrl: "",
        apiKeyMasked: "",
        asrModel: "",
        ttsModel: "",
        characterVoice: "",
        assistantVoice: "",
        vadEnabled: false,
        vadStatus: "unavailable",
      },
    });
    expect(screen.getByText("语音功能")).toBeInTheDocument();
    expect(screen.queryByText("试听")).not.toBeInTheDocument();
  });
});
