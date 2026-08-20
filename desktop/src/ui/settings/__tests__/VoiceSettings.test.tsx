import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsCenter } from "../SettingsCenter";
import type { VoicePageView } from "../types";

afterEach(cleanup);

function createMockVoiceProps(overrides: Partial<VoicePageView> = {}) {
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
    coding: { engine: "codex", codex: { status: "logged_out" } },
    model: {
      provider: "DeepSeek",
      model: "deepseek-chat",
      baseUrl: "https://api.deepseek.com",
      apiKeyMasked: "sk-····",
      reasoningEffort: "medium",
    },
    voice: defaultVoice,
    remote: {
      code: null,
      ttlSeconds: 300,
      issuedAtEpochMs: null,
      devices: [],
      loading: false,
      error: null,
    },
    onIssuePairingCode: vi.fn(),
    onListRemoteDevices: vi.fn(),
    onRevokeRemoteDevice: vi.fn(),
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
  };

  return props;
}

describe("VoiceSettings (V0.3.3 角色语音与助手无 TTS 改造)", () => {
  it("渲染后断言查询不到任何助手语音入口文案（萨姆 / 神秘的古代机械 / 助手语音 / 古代机械）", () => {
    const props = createMockVoiceProps();
    render(<SettingsCenter {...props} />);

    expect(screen.queryByText(/萨姆/)).not.toBeInTheDocument();
    expect(screen.queryByText(/神秘的古代机械/)).not.toBeInTheDocument();
    expect(screen.queryByText(/助手语音/)).not.toBeInTheDocument();
    expect(screen.queryByText(/古代机械/)).not.toBeInTheDocument();
  });

  it("仅保留 4 位角色说话方（白厄、流萤、三月七、第四面镜）", () => {
    const props = createMockVoiceProps();
    render(<SettingsCenter {...props} />);

    expect(screen.getByText("白厄")).toBeInTheDocument();
    expect(screen.getByText("流萤")).toBeInTheDocument();
    expect(screen.getByText("三月七")).toBeInTheDocument();
    expect(screen.getByText("第四面镜")).toBeInTheDocument();
    expect(screen.getByText(/4 次声音复刻/)).toBeInTheDocument();
  });

  it("展示角色音色四态（未配置 / 创建中 / 已绑定 / 失败）与试听", () => {
    const props = createMockVoiceProps({
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
          state: "creating",
        },
        {
          speakerId: "march7",
          name: "三月七",
          method: "clone",
          state: "failed",
          error: "百炼 API 402: 余额不足",
        },
        {
          speakerId: "fourth_mirror",
          name: "第四面镜",
          method: "clone",
          state: "not_generated",
        },
      ],
    });

    render(<SettingsCenter {...props} />);

    expect(screen.getByText("已绑定")).toBeInTheDocument();
    expect(screen.getByText("创建中")).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(screen.getByText("未配置")).toBeInTheDocument();
    expect(screen.getByText("百炼 API 402: 余额不足")).toBeInTheDocument();

    const previewBtn = screen.getByRole("button", { name: "试听" });
    fireEvent.click(previewBtn);
    expect(props.onPreviewVoice).toHaveBeenCalledWith("voice-phainon-01", "白厄");
  });

  it("DashScope 账号未配置阻断态：展示提示并禁用生成按钮", () => {
    const props = createMockVoiceProps({
      baseUrl: "",
      apiKeyMasked: "",
      credentialSource: "not_configured",
    });

    render(<SettingsCenter {...props} />);

    expect(screen.getByText(/语音服务账号未配置/)).toBeInTheDocument();
    const generateBtn = screen.getByRole("button", { name: /生成.*专属音色/ });
    expect(generateBtn).toBeDisabled();
  });

  it("只读展示固定语音模型 ASR 与 TTS", () => {
    const props = createMockVoiceProps();
    render(<SettingsCenter {...props} />);

    expect(screen.getByText("qwen-audio-3.0-asr-flash-streaming")).toBeInTheDocument();
    expect(screen.getByText("qwen-audio-3.0-tts-flash")).toBeInTheDocument();
    expect(screen.queryByLabelText("ASR 模型")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("TTS 模型")).not.toBeInTheDocument();
  });

  it("保留 VAD 用户语音输入开关", () => {
    const onSaveVoice = vi.fn();
    const props = { ...createMockVoiceProps(), onSaveVoice };
    render(<SettingsCenter {...props} />);

    const vadSwitch = screen.getByLabelText(/语音自动聆听/);
    expect(vadSwitch).toBeInTheDocument();
    expect(vadSwitch).toBeChecked();

    fireEvent.click(vadSwitch);
    expect(onSaveVoice).toHaveBeenCalledWith(
      expect.objectContaining({
        vadEnabled: false,
      }),
    );
  });
});
