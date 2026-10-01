import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createActionController } from "../../services/actions";
import { MockDesktopBackend } from "../../services/mockDesktopBackend";
import { Onboarding } from "../gate/Onboarding";
import { SettingsCenter } from "../settings/SettingsCenter";

afterEach(cleanup);

describe("Onboarding", () => {
  it("三步推进，配置页可跳过", async () => {
    const onCreateProject = vi.fn().mockResolvedValue(true);
    const onFinish = vi.fn();
    render(
      <Onboarding
        onCreateProject={onCreateProject}
        onSaveModelConfig={vi.fn().mockResolvedValue({ ok: true, message: "连接正常（延迟 120 ms）" })}
        onFinish={onFinish}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "选择文件夹" }));
    // 步骤指示器始终列出三步的名字，进入下一步的信号是该步的面板标题。
    expect(await screen.findByRole("heading", { name: "配置角色模型" })).toBeInTheDocument();
    expect(onCreateProject).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "跳过，之后再说" }));
    expect(screen.getByRole("heading", { name: "都准备好了" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "开始使用" }));
    expect(onFinish).toHaveBeenCalledTimes(1);
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

    const pick = screen.getByRole("button", { name: "选择文件夹" });
    fireEvent.click(pick);
    expect(pick).toBeDisabled();
    // 选择结束后按钮恢复可用，说明这次创建已经返回。
    await waitFor(() => expect(pick).toBeEnabled());
    expect(onCreateProject).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "创建第一个项目" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "配置角色模型" })).not.toBeInTheDocument();
  });

  it("角色模型连接成功后自动进入完成步骤", async () => {
    const onSaveModelConfig = vi.fn().mockResolvedValue({ ok: true, message: "连接正常（延迟 546 ms）" });
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
    expect(onSaveModelConfig).toHaveBeenCalledWith({ provider: "deepseek", apiKey: "sk-test" });
  });

  it("默认 DeepSeek 只需要 Key，OpenAI 兼容 API 另需 Base URL 与模型", () => {
    render(
      <Onboarding
        onCreateProject={vi.fn().mockResolvedValue(true)}
        onSaveModelConfig={vi.fn().mockResolvedValue({ ok: true, message: "连接正常" })}
        onFinish={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "跳过" }));
    const provider = screen.getByLabelText("模型来源");
    expect(provider).toHaveValue("deepseek");
    expect(screen.queryByLabelText("Base URL")).not.toBeInTheDocument();
    fireEvent.change(provider, { target: { value: "openai_compatible" } });
    expect(screen.getByLabelText("Base URL")).toHaveValue("https://api.openai.com/v1");
    expect(screen.getByLabelText("模型")).toHaveValue("gpt-5.6-sol");
    expect(screen.getByRole("button", { name: "保存并测试" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-test" } });
    expect(screen.getByRole("button", { name: "保存并测试" })).toBeEnabled();
  });
});

function renderSettings(overrides: Partial<Parameters<typeof SettingsCenter>[0]> = {}) {
  const props: Parameters<typeof SettingsCenter>[0] = {
    open: true,
    page: "model",
    onPageChange: vi.fn(),
    onClose: vi.fn(),
    account: { displayName: "吴 Jonah" },
    model: {
      provider: "deepseek",
      model: "deepseek-reasoner",
      baseUrl: "https://api.deepseek.com",
      apiKeyMasked: "sk-····",
      reasoningEffort: "medium",
      providerSupported: true,
      providerUnavailable: null,
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
    onSaveModel: vi.fn(),
    onTestModel: vi.fn(),
    onSaveVoice: vi.fn(),
    onPreviewVoice: vi.fn(),
    remote: {
      code: null,
      ttlSeconds: 300,
      issuedAtEpochMs: null,
      devices: [],
      loading: false,
      error: null,
      serveAddress: null,
      tunnel: { state: "off", publicUrl: null, hostname: null, error: null, requestError: null, loading: false },
    },
    onIssuePairingCode: vi.fn(),
    onListRemoteDevices: vi.fn(),
    onRevokeRemoteDevice: vi.fn(),
    onProvisionVoices: vi.fn(),
    onPickFile: vi.fn(),
    actions: createActionController(new MockDesktopBackend()).actions,
    ...overrides,
  };
  render(<SettingsCenter {...props} />);
  return props;
}

describe("SettingsCenter", () => {
  it("栏目导航切换页面，Esc 关闭", () => {
    // 窗口没有打开的聊天：长期记忆页只说明原因，不发记忆命令。
    const props = renderSettings({ page: "memory" });
    expect(screen.getByRole("dialog", { name: "设置" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "长期记忆" })).toBeInTheDocument();
    expect(screen.getByTestId("memory-panel")).toHaveTextContent("没有打开的聊天");

    fireEvent.click(screen.getByRole("button", { name: "语音" }));
    expect(props.onPageChange).toHaveBeenLastCalledWith("voice");
    fireEvent.click(screen.getByRole("button", { name: "长期记忆" }));
    expect(props.onPageChange).toHaveBeenLastCalledWith("memory");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
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

  it("模型页切回 DeepSeek 时改用 DeepSeek 默认端点与模型", async () => {
    const onSaveModel = vi.fn().mockResolvedValue(undefined);
    renderSettings({
      onSaveModel,
      model: {
        provider: "openai_compatible",
        model: "gpt-5.6-sol",
        baseUrl: "https://gateway.example.com/v1",
        apiKeyMasked: "",
        reasoningEffort: "auto",
        providerSupported: true,
        providerUnavailable: null,
      },
    });

    fireEvent.change(screen.getByLabelText("服务商"), { target: { value: "deepseek" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并测试" }));

    await waitFor(() =>
      expect(onSaveModel).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "deepseek",
          baseUrl: "https://api.deepseek.com",
          model: "deepseek-v4-flash",
        }),
      ),
    );
  });

  const unavailableMessage = "该供应商不可用，请重新选择 DeepSeek 或 OpenAI 兼容 API。";

  it("后端判定服务商不可用时显示原因并禁止保存，改选可用服务商后恢复", async () => {
    const onSaveModel = vi.fn().mockResolvedValue(undefined);
    renderSettings({
      model: {
        provider: "openai_oauth",
        model: "gpt-5.6-sol",
        baseUrl: "https://api.openai.com/v1",
        apiKeyMasked: "",
        reasoningEffort: "auto",
        providerSupported: false,
        providerUnavailable: { code: "provider_unavailable", message: unavailableMessage },
      },
      onSaveModel,
    });

    expect(screen.getByLabelText("服务商")).toHaveValue("openai_oauth");
    // 占位与提示文案都来自后端 provider_unavailable.message
    expect(screen.getByRole("option", { name: unavailableMessage })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(unavailableMessage);

    const save = screen.getByRole("button", { name: "保存并测试" });
    // 只改模型字段仍算「未改选服务商」，不许在不可用供应商上保存
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "gpt-5.6" } });
    expect(save).toBeDisabled();

    // 显式选择可用服务商后立即恢复保存，不需要重进设置页
    fireEvent.change(screen.getByLabelText("服务商"), { target: { value: "openai_compatible" } });
    expect(save).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(save);

    await waitFor(() =>
      expect(onSaveModel).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "openai_compatible" }),
      ),
    );
    expect(onSaveModel).not.toHaveBeenCalledWith(
      expect.objectContaining({ provider: "openai_oauth" }),
    );
  });

  it("后端只给 code 不给 message 时不编造文案，但保存仍然拦住", () => {
    renderSettings({
      model: {
        provider: "openai_oauth",
        model: "gpt-5.6-sol",
        baseUrl: "https://api.openai.com/v1",
        apiKeyMasked: "",
        reasoningEffort: "auto",
        providerSupported: false,
        providerUnavailable: null,
      },
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("模型"), { target: { value: "gpt-5.6" } });
    expect(screen.getByRole("button", { name: "保存并测试" })).toBeDisabled();
  });

  it("账号页保存资料、修改密码（含禁用校验）与退出登录二次确认", async () => {
    const props = renderSettings({
      page: "account",
      onSaveProfile: vi.fn().mockResolvedValue(undefined),
      onChangePassword: vi.fn().mockRejectedValue(new Error("原密码错误")),
    });

    // 显示名称未修改时保存禁用；修改后保存，结果就地显示
    const save = screen.getByRole("button", { name: "保存资料" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "吴新名" } });
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }));
    expect(props.onSaveProfile).toHaveBeenCalledWith("吴新名");
    expect(await screen.findByRole("status")).toHaveTextContent("资料已保存");

    // 当前密码为空或新密码不足 6 位时改密禁用；失败原文就地显示
    const change = screen.getByRole("button", { name: "修改密码" });
    expect(change).toBeDisabled();
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "old-pass" } });
    expect(change).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/新密码/), { target: { value: "new-pass" } });
    fireEvent.click(change);
    expect(props.onChangePassword).toHaveBeenCalledWith("old-pass", "new-pass");
    expect(await screen.findByRole("alert")).toHaveTextContent("原密码错误");

    // 退出登录：先出现二次确认，确定后才调用 onLogout
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    expect(props.onLogout).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确定退出" }));
    expect(props.onLogout).toHaveBeenCalledTimes(1);
  });
});
