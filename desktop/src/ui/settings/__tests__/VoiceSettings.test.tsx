import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createActionController } from "../../../services/actions";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { SettingsCenter } from "../SettingsCenter";
import type { VoicePageView } from "../types";

afterEach(cleanup);

function voicePageProps(overrides: Partial<VoicePageView> = {}) {
  const defaultVoice: VoicePageView = {
    enabled: true,
    assistantVoiceEnabled: false,
    characterVoiceId: "voice-phainon-01",
    characterVoiceName: "白厄",
    assistantVoiceId: "",
    assistantVoiceName: "",
    vadEnabled: true,
    vadStatus: "ready",
    baseUrl: "https://dashscope.aliyuncs.com/api/v1",
    apiKeyMasked: "sk-····1234",
    asrAvailable: true,
    credentialSource: "account",
    voicesSource: "account",
    ...overrides,
  };

  const props: Parameters<typeof SettingsCenter>[0] = {
    open: true,
    page: "voice",
    onPageChange: vi.fn(),
    onClose: vi.fn(),
    account: { displayName: "测试用户" },
    model: {
      provider: "deepseek",
      model: "deepseek-chat",
      baseUrl: "https://api.deepseek.com",
      apiKeyMasked: "sk-····",
      reasoningEffort: "medium",
      providerSupported: true,
      providerUnavailable: null,
    },
    voice: defaultVoice,
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
    modelTest: { state: "idle" },
    voicePreview: { state: "idle" },
    onSaveProfile: vi.fn(),
    onChangePassword: vi.fn(),
    onLogout: vi.fn(),
    onSaveModel: vi.fn(),
    onTestModel: vi.fn(),
    onSaveVoice: vi.fn(),
    onPreviewVoice: vi.fn(),
    onProvisionVoices: vi.fn(),
    onPickFile: vi.fn(),
    actions: createActionController(new MockDesktopBackend()).actions,
  };

  return props;
}

describe("设置中心语音页", () => {
  it("展示各说话方的音色状态与错误原文，已绑定的音色可按 voice_id 试听", () => {
    const props = voicePageProps({
      speakers: [
        {
          speakerId: "phainon",
          name: "白厄",
          method: "clone",
          state: "completed",
          voiceId: "voice-phainon-01",
        },
        {
          speakerId: "firefly",
          name: "流萤",
          method: "clone",
          state: "not_generated",
        },
        {
          speakerId: "march7",
          name: "三月七",
          method: "clone",
          state: "failed",
          error: "百炼 API 402: 余额不足",
        },
      ],
    });

    render(<SettingsCenter {...props} />);

    expect(screen.getByText("已绑定")).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(screen.getByText("未配置")).toBeInTheDocument();
    expect(screen.getByText("百炼 API 402: 余额不足")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "试听" }));
    expect(props.onPreviewVoice).toHaveBeenCalledWith("voice-phainon-01", "白厄");
  });

  it.each([
    ["account", "sk-····1234", "当前账号已保存 sk-····1234", "当前账号 BYOK 已配置"],
    ["development_env", "", "开发环境 .env Key 可用，尚未保存到当前账号", "开发环境 .env 凭据可用（未保存到账号）"],
  ] as const)("凭据来源 %s 时如实标注 Key 的保存位置", (credentialSource, apiKeyMasked, keyNote, switchNote) => {
    render(<SettingsCenter {...voicePageProps({ credentialSource, apiKeyMasked })} />);

    expect(screen.getByText(keyNote)).toBeInTheDocument();
    expect(screen.getByText(switchNote)).toBeInTheDocument();
  });

  it("DashScope 账号未配置时提示并禁用生成", () => {
    const props = voicePageProps({
      baseUrl: "",
      apiKeyMasked: "",
      credentialSource: "not_configured",
    });

    render(<SettingsCenter {...props} />);

    expect(screen.getByText(/语音服务账号未配置/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成 3 个专属音色" })).toBeDisabled();
  });

  it("保存新 Key 与服务地址，保存后清空 Key 输入框", async () => {
    const onSaveVoice = vi.fn().mockResolvedValue(undefined);
    render(<SettingsCenter {...voicePageProps()} onSaveVoice={onSaveVoice} />);

    const keyInput = screen.getByPlaceholderText("留空保留当前 sk-····1234");
    fireEvent.change(keyInput, { target: { value: "user-key" } });
    fireEvent.click(screen.getByRole("button", { name: "保存语音配置" }));

    expect(onSaveVoice).toHaveBeenCalledWith({
      apiKey: "user-key",
      baseUrl: "https://dashscope.aliyuncs.com/api/v1",
    });
    await waitFor(() => expect(keyInput).toHaveValue(""));
  });

  // 开关只提交变化的那一项：带上服务地址会让后端重建语音运行时并打断朗读。
  it.each([
    [/语音功能/, { enabled: false }],
    [/语音自动聆听/, { vadEnabled: false }],
  ])("切换 %s 开关只提交该项", (label, expected) => {
    const onSaveVoice = vi.fn().mockResolvedValue(undefined);
    render(<SettingsCenter {...voicePageProps()} onSaveVoice={onSaveVoice} />);

    fireEvent.click(screen.getByLabelText(label));
    expect(onSaveVoice).toHaveBeenCalledWith(expected);
  });

  it("语音总开关关闭时语音自动聆听不可用", () => {
    render(<SettingsCenter {...voicePageProps({ enabled: false, vadEnabled: false, vadStatus: "unavailable" })} />);
    expect(screen.getByLabelText(/语音自动聆听/)).toBeDisabled();
  });

  it("生成专属音色提交全部未生成的说话方，进行中不会重复提交", async () => {
    let resolveProvision: ((value: { results: [] }) => void) | undefined;
    const onProvisionVoices = vi.fn(
      () => new Promise<{ results: [] }>((resolve) => { resolveProvision = resolve; }),
    );
    render(<SettingsCenter {...voicePageProps()} onProvisionVoices={onProvisionVoices} />);

    const button = screen.getByRole("button", { name: "生成 3 个专属音色" });
    fireEvent.click(button);
    expect(button).toHaveTextContent("正在生成…");
    fireEvent.click(button);

    expect(onProvisionVoices).toHaveBeenCalledTimes(1);
    expect(onProvisionVoices).toHaveBeenCalledWith(["phainon", "firefly", "march7"], false);
    resolveProvision?.({ results: [] });
    expect(await screen.findByRole("button", { name: "生成 3 个专属音色" })).toBe(button);
  });

  it("音色生成失败后显示失败状态并允许重试", async () => {
    const onProvisionVoices = vi.fn().mockRejectedValue(new Error("百炼 API 402: 余额不足"));
    render(<SettingsCenter {...voicePageProps()} onProvisionVoices={onProvisionVoices} />);

    fireEvent.click(screen.getByRole("button", { name: "生成 3 个专属音色" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("百炼 API 402: 余额不足");
    });
    expect(screen.getAllByText("失败")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "重试失败项" })).toBeEnabled();
  });
});
