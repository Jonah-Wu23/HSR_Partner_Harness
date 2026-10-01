import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  CardGetResult,
  CharacterVoiceState,
  DesktopCommand,
  DesktopCommandMethod,
} from "../../../contracts/protocol";
import type { CharacterCardVoicePageViewModel } from "../../../contracts/view-models";
import { createMockScenario } from "../../../mocks/scenarios";
import { createActionController } from "../../../services/actions";
import { DesktopRequestError } from "../../../services/backend";
import { desktopStore } from "../../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../../test/fakeBackend";
import { CharacterVoiceSection, type CharacterVoiceSectionProps } from "../CharacterVoiceSection";

afterEach(() => {
  cleanup();
  desktopStore.setState(desktopStore.getInitialState(), true);
});

const KAFKA_ID = "card-saved-002";

/** card.get 里 data.extensions.hsr.voice_profile 的线缆形状：codec 序列化的字段全部是字符串。 */
interface VoiceProfileWire {
  state: string;
  voice_id: string;
  target_model: string;
  creation_mode: string;
  prefix: string;
  reference_audio_asset: string;
  reference_audio_url: string;
  voice_prompt_asset: string;
  last_error: string;
  updated_at: string;
}

function voiceProfile(overrides: Partial<VoiceProfileWire> = {}): VoiceProfileWire {
  return {
    state: "voice_unconfigured",
    voice_id: "",
    target_model: "qwen-audio-3.0-tts-flash",
    creation_mode: "",
    prefix: "",
    reference_audio_asset: "",
    reference_audio_url: "",
    voice_prompt_asset: "",
    last_error: "",
    updated_at: "2026-08-18T21:40:00+00:00",
    ...overrides,
  };
}

function cardGetResult(cardId: string, profile: VoiceProfileWire): CardGetResult {
  const builtin = cardId.startsWith("builtin:");
  return {
    card_id: cardId,
    state: "saved",
    source: builtin ? "builtin" : "user_created",
    created_at: "2026-08-18T21:40:00+00:00",
    updated_at: "2026-08-18T21:40:00+00:00",
    read_only: builtin,
    avatar: null,
    card: {
      spec: "chara_card_v3",
      spec_version: "3.0",
      data: { name: "卡芙卡", extensions: { hsr: { voice_profile: profile } } },
    },
    compat_report: {
      applied: [],
      preserved: [],
      not_executed: [],
      normalized_from_root: [],
      warnings: [],
      errors: [],
    },
  };
}

interface VoiceBackendOptions {
  profile?: VoiceProfileWire;
  /** 登记的命令回放为错误帧。 */
  errors?: Partial<Record<DesktopCommandMethod, DesktopRequestError>>;
  pickFileResult?: string | null;
  /** card.get 等到它完成才应答，用来观察读取中的界面。 */
  cardGetGate?: Promise<void>;
}

/** 按真实后端回放卡音色命令：card.get 带出当前 voice_profile，绑定、创建、解绑改写它。 */
function voiceBackend(options: VoiceBackendOptions = {}) {
  let profile = options.profile ?? voiceProfile();
  const { backend, commands } = fakeBackend(
    async (command) => {
      const error = options.errors?.[command.method];
      if (error) throw error;
      const cardId = String(command.params.card_id ?? "");
      switch (command.method) {
        case "card.get":
          await options.cardGetGate;
          return cardGetResult(cardId, profile);
        case "card.list":
          return { cards: [] };
        case "voice.card_bind_reference":
          profile = { ...profile, reference_audio_asset: "ref-audio-001" };
          return {
            card_id: cardId,
            asset_id: "ref-audio-001",
            duration_seconds: 5.2,
            size_bytes: 102400,
            mime_type: "audio/wav",
          };
        case "voice.card_create": {
          if (command.params.mode === "clone" && !profile.reference_audio_asset) {
            throw new DesktopRequestError(
              "voice_reference_missing",
              "请先绑定参考音频（voice.card_bind_reference）",
            );
          }
          const voiceId = `${String(command.params.prefix)}-voice-001`;
          profile = {
            ...profile,
            state: "voice_ready",
            voice_id: voiceId,
            creation_mode: String(command.params.mode),
            prefix: String(command.params.prefix),
            last_error: "",
          };
          return { card_id: cardId, state: "voice_ready", voice_id: voiceId };
        }
        case "voice.card_unbind":
          profile = { ...profile, state: "voice_unconfigured", voice_id: "", creation_mode: "", last_error: "" };
          return { card_id: cardId, state: "voice_unconfigured" };
        case "voice.card_preview":
          return { voice: createMockScenario("single-project").snapshot.voice };
        default:
          return unexpectedCommand(command);
      }
    },
    { pickFileResult: options.pickFileResult },
  );
  return {
    backend,
    commands,
    setProfile(next: VoiceProfileWire) {
      profile = next;
    },
  };
}

function paramsOf(commands: readonly DesktopCommand[], method: string): Record<string, unknown>[] {
  return commands.filter((command) => command.method === method).map((command) => command.params);
}

function createVm(
  overrides: Partial<CharacterCardVoicePageViewModel> = {},
): CharacterCardVoicePageViewModel {
  return {
    voiceConfigured: true,
    cards: [
      {
        cardId: "card-saved-002",
        name: "卡芙卡",
        state: "saved",
        source: "user_created",
        hasAvatar: true,
        voiceState: "voice_unconfigured",
        active: true,
        readOnly: false,
      },
      {
        cardId: "builtin:phainon",
        name: "白厄",
        state: "saved",
        source: "builtin",
        hasAvatar: false,
        voiceState: "voice_ready",
        active: false,
        readOnly: true,
      },
      {
        cardId: "card-imported-004",
        name: "砂金",
        state: "imported",
        source: "tavern_import",
        hasAvatar: true,
        voiceState: "voice_failed",
        active: false,
        readOnly: false,
      },
    ],
    ...overrides,
  };
}

/** 与设置中心一致：文件对话框走后端 pickFile。 */
function renderSection(
  { backend }: ReturnType<typeof voiceBackend>,
  props: Partial<CharacterVoiceSectionProps> = {},
) {
  const { actions } = createActionController(backend);
  const element = (next: Partial<CharacterVoiceSectionProps>) => (
    <CharacterVoiceSection
      characterVoice={createVm()}
      actions={actions}
      onPickFile={(options) => backend.pickFile(options)}
      {...next}
    />
  );
  const view = render(element(props));
  return { rerender: (next: Partial<CharacterVoiceSectionProps>) => view.rerender(element(next)) };
}

/** 卡详情到达后创建表单会重置并按角色名填入默认前缀，以此作为详情就绪的界面信号。 */
async function waitForDetail(): Promise<void> {
  await waitFor(() => expect(screen.getByTestId("prefix-input")).toHaveValue("card"));
}

async function click(testId: string): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByTestId(testId));
  });
}

function withSummaryVoiceState(voiceState: CharacterVoiceState): CharacterCardVoicePageViewModel {
  return createVm({
    cards: createVm().cards.map((card) => (card.cardId === KAFKA_ID ? { ...card, voiceState } : card)),
  });
}

describe("CharacterVoiceSection", () => {
  it("未选卡时只显示角色选择器，不读取卡详情", () => {
    const replay = voiceBackend();
    renderSection(replay);

    const options = Array.from((screen.getByLabelText("选择角色") as HTMLSelectElement).options).map(
      (option) => option.text,
    );
    expect(options).toEqual(["— 请选择 —", "卡芙卡（自定义）", "白厄（内置）", "砂金（导入）"]);
    expect(screen.queryByTestId("reference-audio-section")).not.toBeInTheDocument();
    expect(replay.commands).toEqual([]);
  });

  it("选择自定义卡后读取音色详情，未配置时引导选择参考音频", async () => {
    const replay = voiceBackend();
    renderSection(replay);

    fireEvent.change(screen.getByLabelText("选择角色"), { target: { value: KAFKA_ID } });

    expect(await screen.findByTestId("voice-state-unconfigured")).toBeInTheDocument();
    expect(screen.getByTestId("pick-reference-btn")).toBeInTheDocument();
    expect(paramsOf(replay.commands, "card.get")).toEqual([{ card_id: KAFKA_ID }]);
  });

  it("选择内置卡时显示只读说明，不提供创建入口", async () => {
    renderSection(voiceBackend());

    fireEvent.change(screen.getByLabelText("选择角色"), { target: { value: "builtin:phainon" } });

    expect(await screen.findByTestId("builtin-readonly-block")).toHaveTextContent("内置角色只读");
    expect(screen.queryByTestId("create-voice-btn")).not.toBeInTheDocument();
  });

  it("选择参考音频后经 voice.card_bind_reference 绑定并显示资产 ID", async () => {
    const replay = voiceBackend({ pickFileResult: "C:/refs/kafka_ref.wav" });
    renderSection(replay, { voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    await click("pick-reference-btn");

    expect(await screen.findByTestId("replace-reference-btn")).toBeInTheDocument();
    expect(screen.getByTestId("reference-audio-section")).toHaveTextContent("ref-audio-001");
    expect(screen.queryByTestId("voice-state-unconfigured")).not.toBeInTheDocument();
    expect(paramsOf(replay.commands, "voice.card_bind_reference")).toEqual([
      { card_id: KAFKA_ID, path: "C:/refs/kafka_ref.wav" },
    ]);
  });

  it("参考音频被后端拒绝时显示原文", async () => {
    const replay = voiceBackend({
      pickFileResult: "C:/refs/bad.txt",
      errors: {
        "voice.card_bind_reference": new DesktopRequestError("voice_reference_invalid", "参考音频仅支持 WAV / MP3 / M4A"),
      },
    });
    renderSection(replay, { voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    await click("pick-reference-btn");

    expect(await screen.findByTestId("operation-error")).toHaveTextContent("参考音频仅支持 WAV / MP3 / M4A");
  });

  it("clone 模式用已绑定的参考音频创建音色，完成后显示音色 ID", async () => {
    const replay = voiceBackend({ profile: voiceProfile({ reference_audio_asset: "ref-audio-001" }) });
    renderSection(replay, { voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    await click("create-voice-btn");

    expect(await screen.findByTestId("voice-state-ready")).toHaveTextContent("card-voice-001");
    expect(paramsOf(replay.commands, "voice.card_create")).toEqual([
      { card_id: KAFKA_ID, mode: "clone", prefix: "card" },
    ]);
  });

  it("design 模式缺少声音描述词时禁用创建按钮", async () => {
    const replay = voiceBackend();
    renderSection(replay, { voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    fireEvent.click(screen.getByTestId("create-mode-design"));

    expect(screen.getByTestId("create-voice-btn")).toBeDisabled();
    expect(paramsOf(replay.commands, "voice.card_create")).toEqual([]);
  });

  it("design 模式提交声音描述词与试听文本", async () => {
    const replay = voiceBackend();
    renderSection(replay, { voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    fireEvent.click(screen.getByTestId("create-mode-design"));
    fireEvent.change(screen.getByTestId("voice-prompt-input"), { target: { value: "温柔沉稳的女声" } });
    fireEvent.change(screen.getByTestId("preview-text-input"), { target: { value: "你好，这是设计试听。" } });
    await click("create-voice-btn");

    expect(await screen.findByTestId("voice-state-ready")).toBeInTheDocument();
    expect(paramsOf(replay.commands, "voice.card_create")).toEqual([
      {
        card_id: KAFKA_ID,
        mode: "design",
        prefix: "card",
        voice_prompt: "温柔沉稳的女声",
        preview_text: "你好，这是设计试听。",
      },
    ]);
  });

  it("卡详情为创建中时显示进度，卡库摘要离开创建中后重新读取详情", async () => {
    const replay = voiceBackend({ profile: voiceProfile({ state: "voice_creating" }) });
    const { rerender } = renderSection(replay, {
      characterVoice: withSummaryVoiceState("voice_creating"),
      voiceCardFocus: KAFKA_ID,
    });

    expect(await screen.findByTestId("voice-state-creating")).toHaveTextContent("正在创建音色…");

    // voice.card_provision_changed 把卡库摘要推进到 voice_ready，服务端此时已写入音色 ID。
    replay.setProfile(voiceProfile({ state: "voice_ready", voice_id: "card-voice-002" }));
    rerender({ characterVoice: withSummaryVoiceState("voice_ready"), voiceCardFocus: KAFKA_ID });

    expect(await screen.findByTestId("voice-state-ready")).toHaveTextContent("card-voice-002");
    expect(paramsOf(replay.commands, "card.get")).toHaveLength(2);
  });

  it("创建失败时显示失败原因，重试后重新创建", async () => {
    const replay = voiceBackend({
      profile: voiceProfile({
        state: "voice_failed",
        reference_audio_asset: "ref-audio-001",
        last_error: "TTS 服务返回 402：音色创建额度已用尽",
      }),
    });
    renderSection(replay, { characterVoice: withSummaryVoiceState("voice_failed"), voiceCardFocus: KAFKA_ID });

    expect(await screen.findByTestId("voice-last-error")).toHaveTextContent("TTS 服务返回 402：音色创建额度已用尽");
    await waitForDetail();

    await click("retry-create-btn");

    expect(await screen.findByTestId("voice-state-ready")).toBeInTheDocument();
    expect(paramsOf(replay.commands, "voice.card_create")).toEqual([
      { card_id: KAFKA_ID, mode: "clone", prefix: "card" },
    ]);
  });

  it.each([
    {
      code: "voice_card_provision_in_progress",
      message: "该角色卡正在创建音色，请等待完成后再试",
      reference: "ref-audio-001",
      fail: true,
    },
    {
      code: "voice_not_configured",
      message: "请先在语音页保存 DashScope API Key 与服务地址，再为角色创建音色",
      reference: "ref-audio-001",
      fail: true,
    },
    {
      code: "voice_reference_missing",
      message: "请先绑定参考音频（voice.card_bind_reference）",
      reference: "",
      fail: false,
    },
  ])("创建被后端以 $code 拒绝时显示原文", async ({ code, message, reference, fail }) => {
    const replay = voiceBackend({
      profile: voiceProfile({ reference_audio_asset: reference }),
      errors: fail ? { "voice.card_create": new DesktopRequestError(code, message) } : {},
    });
    renderSection(replay, { voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    await click("create-voice-btn");

    expect(await screen.findByTestId("operation-error")).toHaveTextContent(message);
    expect(screen.queryByTestId("voice-state-ready")).not.toBeInTheDocument();
  });

  it("就绪音色试听经 voice.card_preview 下发", async () => {
    const replay = voiceBackend({ profile: voiceProfile({ state: "voice_ready", voice_id: "card-voice-001" }) });
    renderSection(replay, { characterVoice: withSummaryVoiceState("voice_ready"), voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    await click("preview-voice-btn");

    await waitFor(() => expect(screen.getByTestId("preview-voice-btn")).toHaveTextContent("试听"));
    expect(paramsOf(replay.commands, "voice.card_preview")).toEqual([{ card_id: KAFKA_ID }]);
    expect(screen.queryByTestId("operation-error")).not.toBeInTheDocument();
  });

  it("试听被后端拒绝时显示原文", async () => {
    const replay = voiceBackend({
      profile: voiceProfile({ state: "voice_ready", voice_id: "card-voice-001" }),
      errors: { "voice.card_preview": new DesktopRequestError("voice_card_not_ready", "该角色卡尚未创建可用音色") },
    });
    renderSection(replay, { characterVoice: withSummaryVoiceState("voice_ready"), voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    await click("preview-voice-btn");

    expect(await screen.findByTestId("operation-error")).toHaveTextContent("该角色卡尚未创建可用音色");
  });

  it("解除绑定需二次确认，确认后经 voice.card_unbind 回到未配置", async () => {
    const replay = voiceBackend({
      profile: voiceProfile({ state: "voice_ready", voice_id: "card-voice-001", reference_audio_asset: "ref-audio-001" }),
    });
    renderSection(replay, { characterVoice: withSummaryVoiceState("voice_ready"), voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    fireEvent.click(screen.getByTestId("unbind-voice-btn"));
    fireEvent.click(screen.getByTestId("confirm-cancel"));
    expect(screen.queryByTestId("voice-confirm-modal")).not.toBeInTheDocument();
    expect(paramsOf(replay.commands, "voice.card_unbind")).toEqual([]);

    fireEvent.click(screen.getByTestId("unbind-voice-btn"));
    expect(screen.getByTestId("voice-confirm-modal")).toHaveTextContent("解除音色绑定？");
    await click("confirm-ok");

    await waitFor(() => expect(screen.queryByTestId("voice-state-ready")).not.toBeInTheDocument());
    expect(screen.queryByTestId("voice-confirm-modal")).not.toBeInTheDocument();
    expect(screen.getByTestId("reference-audio-section")).toHaveTextContent("ref-audio-001");
    expect(paramsOf(replay.commands, "voice.card_unbind")).toEqual([{ card_id: KAFKA_ID }]);
  });

  it("账号未配置时显示阻塞说明并提供跳转入口", () => {
    const replay = voiceBackend();
    const onScrollToAccountConfig = vi.fn();
    renderSection(replay, { characterVoice: createVm({ voiceConfigured: false }), onScrollToAccountConfig });

    expect(screen.getByTestId("account-config-block")).toHaveTextContent("语音服务账号未配置");

    fireEvent.click(screen.getByTestId("go-to-account-config"));

    expect(onScrollToAccountConfig).toHaveBeenCalledTimes(1);
    expect(replay.commands).toEqual([]);
  });

  it("card.get 返回枚举外的音色状态时报错", async () => {
    renderSection(voiceBackend({ profile: voiceProfile({ state: "voice_bogus" }) }), { voiceCardFocus: KAFKA_ID });

    expect(await screen.findByTestId("detail-error")).toHaveTextContent("角色卡音色状态未知：voice_bogus");
  });

  it("voiceCardFocus 变化时同步选中并读取详情", async () => {
    const replay = voiceBackend();
    const { rerender } = renderSection(replay);
    expect(replay.commands).toEqual([]);

    rerender({ voiceCardFocus: KAFKA_ID });

    expect(await screen.findByTestId("voice-state-unconfigured")).toBeInTheDocument();
    expect((screen.getByLabelText("选择角色") as HTMLSelectElement).value).toBe(KAFKA_ID);
    expect(paramsOf(replay.commands, "card.get")).toEqual([{ card_id: KAFKA_ID }]);
  });

  it("音色前缀不合法时提示并禁用创建", async () => {
    renderSection(voiceBackend(), { voiceCardFocus: KAFKA_ID });
    await waitForDetail();

    fireEvent.change(screen.getByTestId("prefix-input"), { target: { value: "ABC!" } });

    expect(screen.getByText("前缀只能是 1–10 位小写字母或数字")).toBeInTheDocument();
    expect(screen.getByTestId("create-voice-btn")).toBeDisabled();
  });

  it("读取音色详情期间显示载入提示", async () => {
    let release: () => void = () => {};
    const cardGetGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    renderSection(voiceBackend({ cardGetGate }), { voiceCardFocus: KAFKA_ID });

    expect(screen.getByTestId("detail-loading")).toBeInTheDocument();

    release();

    expect(await screen.findByTestId("voice-state-unconfigured")).toBeInTheDocument();
    expect(screen.queryByTestId("detail-loading")).not.toBeInTheDocument();
  });
});
