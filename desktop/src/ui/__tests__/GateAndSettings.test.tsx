import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    fireEvent.change(screen.getByLabelText(/密码（至少 6 位）/), { target: { value: "abcdef" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "abcdeg" } });
    expect(screen.getByRole("alert")).toHaveTextContent("不一致");
    expect(screen.getByRole("button", { name: "注册并进入" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "abcdef" } });
    fireEvent.click(screen.getByRole("button", { name: "注册并进入" }));
    expect(onRegister).toHaveBeenCalledWith("新伙伴", "abcdef");
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

  it("取消选文件夹时停留在创建项目步骤", async () => {
    const onCreateProject = vi.fn().mockResolvedValue(false);
    render(
      <Onboarding
        onCreateProject={onCreateProject}
        onSaveModelConfig={vi.fn()}
        onFinish={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "选择文件夹" }));
    expect(await screen.findByRole("heading", { name: "创建第一个项目" })).toBeInTheDocument();
    expect(onCreateProject).toHaveBeenCalled();
  });

  it("角色模型连接成功后自动进入完成步骤", async () => {
    const onSaveModelConfig = vi.fn().mockResolvedValue("连接正常（延迟 546 ms）");
    render(
      <Onboarding
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

  it("首次引导提供 DeepSeek、OpenAI 兼容 API 与 OpenAI OAuth", () => {
    render(
      <Onboarding
        onCreateProject={vi.fn().mockResolvedValue(true)}
        onSaveModelConfig={vi.fn().mockResolvedValue("连接正常")}
        onFinish={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    const provider = screen.getByLabelText("模型来源");
    expect(provider).toHaveValue("DeepSeek");
    expect(screen.getByRole("option", { name: "OpenAI 兼容 API（包括 OpenAI API）" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "OpenAI OAuth" })).toBeInTheDocument();

    fireEvent.change(provider, { target: { value: "OpenAI 兼容 API（包括 OpenAI API）" } });
    expect(screen.getByLabelText("Base URL")).toHaveValue("https://api.openai.com/v1");
    expect(screen.getByLabelText("模型")).toHaveValue("gpt-5.6-sol");

    fireEvent.change(provider, { target: { value: "OpenAI OAuth" } });
    expect(screen.getByText("使用 OpenAI 账号登录，角色与助手共用 gpt-5.6-sol。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "启动并继续" })).toBeEnabled();
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
      assistantVoiceEnabled: false,
      characterVoiceId: "qwen-audio-3.0-tts-flash-phainon-46e9bd0087cd4c4c8d29e1b9f1b5db32",
      characterVoiceName: "白厄",
      assistantVoiceId: "qwen-audio-3.0-tts-flash-vd-ancientmac-a26ce26e55414e219fe00360e24b4f19",
      assistantVoiceName: "神秘的古代机械",
      vadEnabled: false,
      vadStatus: "ready",
    },
    modelTest: { state: "idle" },
    voicePreview: { state: "idle" },
    onSaveProfile: vi.fn(),
    onChangePassword: vi.fn(),
    onLogout: vi.fn(),
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

  it("模型页未修改时保存按钮禁用，修改后可保存并测试", async () => {
    const props = renderSettings();
    const save = screen.getByRole("button", { name: "保存并测试" });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "deepseek-chat" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() =>
      expect(props.onSaveModel).toHaveBeenCalledWith(
        expect.objectContaining({
          model: "deepseek-chat",
          reasoningEffort: "medium",
          apiKey: undefined,
        }),
      ),
    );
    expect(props.onTestModel).toHaveBeenCalled();
  });

  it("模型页切到 OpenAI OAuth 时先保存并启动登录，不测试未登录连接", async () => {
    const onSaveModel = vi.fn().mockResolvedValue(undefined);
    const onTestModel = vi.fn();
    const props = renderSettings({ onSaveModel, onTestModel });

    fireEvent.change(screen.getByLabelText("服务商"), {
      target: { value: "openai_oauth" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存并测试" }));

    await waitFor(() =>
      expect(onSaveModel).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "openai_oauth",
          baseUrl: "https://api.openai.com/v1",
          model: "gpt-5.6-sol",
          apiKey: undefined,
        }),
      ),
    );
    expect(onTestModel).not.toHaveBeenCalled();
  });

  it("编程助手页未登录时提供浏览器登录与 API Key 两条路", () => {
    const props = renderSettings({ page: "coding" });
    expect(screen.getByRole("button", { name: "通过浏览器登录" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "通过浏览器登录" }));
    expect(props.onCodexOAuthStart).toHaveBeenCalled();
  });

  it("语音页显示用户 BYOK 配置与固定模型，不显示赞助内容", () => {
    renderSettings({ page: "voice" });
    expect(screen.getByText("语音功能")).toBeInTheDocument();
    expect(screen.getByText("DashScope 账号配置")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("填写自己的 DashScope API Key")).toBeInTheDocument();
    expect(screen.getByText("qwen-audio-3.0-asr-flash-streaming")).toBeInTheDocument();
    expect(screen.getByText("qwen-audio-3.0-tts-flash")).toBeInTheDocument();
    expect(screen.queryByText("喜欢这个语音功能的话，请给作者一点支持")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "微信收款二维码" })).not.toBeInTheDocument();
    // 六个音色只展示生成状态，不再提供模型或 voice_id 编辑输入框
    expect(screen.getByText("白厄")).toBeInTheDocument();
    expect(screen.getByText("神秘的古代机械")).toBeInTheDocument();
    expect(screen.queryByLabelText("ASR 模型")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("TTS 模型")).not.toBeInTheDocument();
  });

  it("语音页明确区分开发环境 .env 凭据与账号 BYOK", () => {
    renderSettings({
      page: "voice",
      voice: {
        enabled: true,
        assistantVoiceEnabled: false,
        characterVoiceId: "",
        characterVoiceName: "白厄",
        assistantVoiceId: "",
        assistantVoiceName: "神秘的古代机械",
        vadEnabled: false,
        vadStatus: "ready",
        baseUrl: "https://dashscope.aliyuncs.com/api/v1",
        apiKeyMasked: "",
        asrAvailable: true,
        credentialSource: "development_env",
      },
    });
    expect(
      screen.getByText("开发环境 .env Key 可用，尚未保存到当前账号"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("开发环境 .env 凭据可用（未保存到账号）"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/当前账号已保存/)).not.toBeInTheDocument();
  });

  it("语音页关闭总开关后隐藏音色与 VAD 细项，不保留赞助卡", () => {
    renderSettings({
      page: "voice",
      voice: {
        enabled: false,
        assistantVoiceEnabled: false,
        characterVoiceId: "",
        characterVoiceName: "",
        assistantVoiceId: "",
        assistantVoiceName: "",
        vadEnabled: false,
        vadStatus: "unavailable",
      },
    });
    expect(screen.getByText("语音功能")).toBeInTheDocument();
    expect(screen.queryByText("喜欢这个语音功能的话，请给作者一点支持")).not.toBeInTheDocument();
    expect(screen.queryByText("试听")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/语音自动聆听/)).toBeDisabled();
  });

  it("语音页保存用户 Key、地址与开关偏好", async () => {
    const onSaveVoice = vi.fn().mockResolvedValue(undefined);
    const props = renderSettings({
      page: "voice",
      onSaveVoice,
      voice: {
        enabled: true,
        assistantVoiceEnabled: false,
        characterVoiceId: "",
        characterVoiceName: "",
        assistantVoiceId: "",
        assistantVoiceName: "",
        vadEnabled: false,
        vadStatus: "ready",
        baseUrl: "https://dashscope.aliyuncs.com/api/v1",
        apiKeyMasked: "sk-····",
      },
    });

    fireEvent.change(screen.getByPlaceholderText("留空保留当前 sk-····"), {
      target: { value: "user-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存语音配置" }));
    await waitFor(() =>
      expect(onSaveVoice).toHaveBeenCalledWith(
        expect.objectContaining({
          apiKey: "user-key",
          baseUrl: "https://dashscope.aliyuncs.com/api/v1",
        }),
      ),
    );

    fireEvent.click(screen.getByLabelText(/语音功能/));
    expect(props.onSaveVoice).toHaveBeenLastCalledWith(expect.objectContaining({
      enabled: false,
      assistantVoiceEnabled: false,
      vadEnabled: false,
      baseUrl: "https://dashscope.aliyuncs.com/api/v1",
    }));
  });

  it("语音页把六项生成委派给 voice.provision", async () => {
    const onProvisionVoices = vi.fn().mockResolvedValue({
      status: "completed",
      completed: 6,
      total: 6,
      results: [],
    });
    renderSettings({ page: "voice", onProvisionVoices });

    fireEvent.click(screen.getByRole("button", { name: "生成 6 个专属音色" }));
    await waitFor(() =>
      expect(onProvisionVoices).toHaveBeenCalledWith(
        ["phainon", "firefly", "sam", "march7", "fourth_mirror", "ancient_machine"],
        false,
      ),
    );
  });

  it("语音页试听按钮按音色回传 voice_id 与名称", () => {
    const props = renderSettings({
      page: "voice",
      voice: {
        enabled: true,
        assistantVoiceEnabled: false,
        characterVoiceId: "",
        characterVoiceName: "",
        assistantVoiceId: "",
        assistantVoiceName: "",
        vadEnabled: false,
        vadStatus: "ready",
        speakers: [
          {
            speakerId: "phainon",
            name: "白厄",
            method: "clone",
            state: "completed",
            voiceId: "account-phainon-voice",
          },
          {
            speakerId: "ancient_machine",
            name: "神秘的古代机械",
            method: "design",
            state: "completed",
            voiceId: "account-ancient-machine-voice",
          },
        ],
      },
    });
    const previewButtons = screen.getAllByRole("button", { name: "试听" });
    fireEvent.click(previewButtons[1]);
    expect(props.onPreviewVoice).toHaveBeenCalledWith(
      "account-ancient-machine-voice",
      "神秘的古代机械",
    );
  });

  it("账号页保存资料、修改密码（含禁用校验）与退出登录二次确认", () => {
    const props = renderSettings({ page: "account" });

    // 显示名称未修改时保存禁用；修改后保存并回传
    const save = screen.getByRole("button", { name: "保存资料" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "吴新名" } });
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }));
    expect(props.onSaveProfile).toHaveBeenCalledWith("吴新名");

    // 当前密码为空或新密码不足 6 位时改密禁用
    const change = screen.getByRole("button", { name: "修改密码" });
    expect(change).toBeDisabled();
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "old-pass" } });
    expect(change).toBeDisabled(); // 新密码仍为空
    fireEvent.change(screen.getByLabelText(/新密码/), { target: { value: "new-pass" } });
    fireEvent.click(change);
    expect(props.onChangePassword).toHaveBeenCalledWith("old-pass", "new-pass");

    // 退出登录：先出现二次确认，确定后才调用 onLogout
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    expect(screen.getByRole("alert")).toHaveTextContent("确定退出");
    fireEvent.click(screen.getByRole("button", { name: "确定退出" }));
    expect(props.onLogout).toHaveBeenCalled();
  });
});
