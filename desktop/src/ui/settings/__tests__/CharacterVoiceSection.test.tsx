import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HarnessActions } from "../../../contracts/actions";
import type {
  CardGetResult,
  CharacterCardSource,
  CharacterCardState,
  CharacterVoiceState,
} from "../../../contracts/protocol";
import type { CharacterCardVoicePageViewModel } from "../../../contracts/view-models";
import { CharacterVoiceSection } from "../CharacterVoiceSection";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function createMockActions(overrides: Partial<HarnessActions> = {}): HarnessActions {
  return {
    createProject: vi.fn().mockResolvedValue(true),
    renameProject: vi.fn().mockResolvedValue(undefined),
    repairProjectPath: vi.fn().mockResolvedValue(undefined),
    selectProject: vi.fn().mockResolvedValue(undefined),
    archiveProject: vi.fn().mockResolvedValue(undefined),
    createConversation: vi.fn().mockResolvedValue(undefined),
    selectConversation: vi.fn().mockResolvedValue(undefined),
    openConversationTab: vi.fn().mockResolvedValue(undefined),
    closeConversationTab: vi.fn(),
    openConversationWindow: vi.fn().mockResolvedValue(undefined),
    renameConversation: vi.fn().mockResolvedValue(undefined),
    archiveConversation: vi.fn().mockResolvedValue(undefined),
    switchMode: vi.fn().mockResolvedValue(undefined),
    switchTheme: vi.fn(),
    submitMessage: vi.fn().mockResolvedValue({}),
    editQueueItem: vi.fn().mockResolvedValue(undefined),
    withdrawQueueItem: vi.fn().mockResolvedValue(undefined),
    prioritizeQueueItem: vi.fn().mockResolvedValue(undefined),
    editQueueFromStrip: vi.fn().mockResolvedValue(null),
    cancelTask: vi.fn().mockResolvedValue(undefined),
    resolveApproval: vi.fn().mockResolvedValue(undefined),
    setApprovalMode: vi.fn().mockResolvedValue(undefined),
    setReasoningEffort: vi.fn().mockResolvedValue(undefined),
    setVadEnabled: vi.fn().mockResolvedValue(undefined),
    startPushToTalk: vi.fn().mockResolvedValue(undefined),
    stopPushToTalk: vi.fn().mockResolvedValue(undefined),
    stopSpeech: vi.fn().mockResolvedValue(undefined),
    skipSpeech: vi.fn().mockResolvedValue(undefined),
    reconnect: vi.fn().mockResolvedValue(undefined),
    listAccounts: vi.fn().mockResolvedValue(undefined),
    registerAccount: vi.fn().mockResolvedValue(undefined),
    loginAccount: vi.fn().mockResolvedValue(undefined),
    logoutAccount: vi.fn().mockResolvedValue(undefined),
    updateAccountProfile: vi.fn().mockResolvedValue(undefined),
    changePassword: vi.fn().mockResolvedValue(undefined),
    completeOnboarding: vi.fn().mockResolvedValue(undefined),
    getConfig: vi.fn().mockResolvedValue(undefined),
    setConfig: vi.fn().mockResolvedValue(undefined),
    testConnection: vi.fn().mockResolvedValue("ok"),
    dismissToast: vi.fn(),
    codexOauthStart: vi.fn().mockResolvedValue(undefined),
    codexOauthStatus: vi.fn().mockResolvedValue({ status: "not_started" }),
    codexApiLogin: vi.fn().mockResolvedValue(undefined),
    codexLogout: vi.fn().mockResolvedValue(undefined),
    voicePreview: vi.fn().mockResolvedValue(undefined),
    provisionVoices: vi.fn().mockResolvedValue({}),
    listCards: vi.fn().mockResolvedValue(undefined),
    openCharacterLibrary: vi.fn().mockResolvedValue(undefined),
    openCharacterCreate: vi.fn().mockResolvedValue(undefined),
    openChat: vi.fn(),
    createCardDraft: vi.fn().mockResolvedValue("draft-123"),
    updateCard: vi.fn().mockResolvedValue(undefined),
    duplicateCard: vi.fn().mockResolvedValue(undefined),
    archiveCard: vi.fn().mockResolvedValue(undefined),
    deleteCard: vi.fn().mockResolvedValue(undefined),
    selectActiveCard: vi.fn().mockResolvedValue(undefined),
    cardGet: vi.fn().mockResolvedValue(createCardGetResult()),
    cardPeekImportJson: vi.fn().mockResolvedValue({ preview: {} as never }),
    cardImportJson: vi.fn().mockResolvedValue({} as never),
    cardExportJson: vi.fn().mockResolvedValue({} as never),
    cardPublish: vi.fn().mockResolvedValue({} as never),
    cardSetAvatar: vi.fn().mockResolvedValue({} as never),
    cardRemoveAvatar: vi.fn().mockResolvedValue({} as never),
    voiceCardBindReference: vi.fn().mockResolvedValue({
      card_id: "card-saved-002",
      asset_id: "ref-audio-001",
      duration_seconds: 5.2,
      size_bytes: 102400,
      mime_type: "audio/wav",
    }),
    voiceCardCreate: vi.fn().mockResolvedValue({
      card_id: "card-saved-002",
      state: "voice_ready" as CharacterVoiceState,
      voice_id: "mock-voice-123",
    }),
    voiceCardUnbind: vi.fn().mockResolvedValue({
      card_id: "card-saved-002",
      state: "voice_unconfigured" as CharacterVoiceState,
    }),
    voiceCardPreview: vi.fn().mockResolvedValue(undefined),
    voiceMobilePttStart: vi.fn().mockResolvedValue({ session_id: "mock-session" }),
    voiceMobileAudioChunk: vi.fn().mockResolvedValue(undefined),
    voiceMobilePttStop: vi.fn().mockResolvedValue({
      session_id: "mock-session",
      transcript: "",
      conversation_id: "",
    }),
    voiceMobileTtsStop: vi.fn().mockResolvedValue(undefined),
    issuePairingCode: vi.fn().mockResolvedValue(undefined),
    listRemoteDevices: vi.fn().mockResolvedValue(undefined),
    revokeRemoteDevice: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function createCardGetResult(overrides: {
  cardId?: string;
  name?: string;
  source?: CharacterCardSource;
  state?: CharacterCardState;
  readOnly?: boolean;
  voiceState?: CharacterVoiceState;
  voiceId?: string;
  creationMode?: string;
  prefix?: string;
  referenceAudioAsset?: {
    asset_id: string;
    duration_seconds: number;
    size_bytes: number;
    mime_type: string;
  } | null;
  lastError?: string | null;
} = {}): CardGetResult {
  const {
    cardId = "card-saved-002",
    name = "卡芙卡",
    source = "user_created",
    state = "saved",
    readOnly = false,
    voiceState = "voice_unconfigured",
    voiceId = "",
    creationMode = "",
    prefix = "",
    referenceAudioAsset = null,
    lastError = null,
  } = overrides;
  return {
    card_id: cardId,
    state,
    source,
    created_at: "2026-08-18T21:40:00+00:00",
    updated_at: "2026-08-18T21:40:00+00:00",
    read_only: readOnly,
    avatar: null,
    card: {
      spec: "chara_card_v3",
      spec_version: "3.0",
      data: {
        name,
        extensions: {
          hsr: {
            voice_profile: {
              voice_id: voiceId,
              state: voiceState,
              creation_mode: creationMode,
              prefix,
              reference_audio_asset: referenceAudioAsset,
              last_error: lastError,
              updated_at: "2026-08-18T21:40:00+00:00",
            },
          },
        },
      },
    },
  };
}

/** 全量并行下 waitFor 通过到 fireEvent 之间可能落进 busy 窗口（按钮短暂禁用，click 被
    静默吞掉）：仅在按钮可点时刻点击，命中即停（断言强度不变，仅消除时序竞争）。 */
async function clickCreateWhenEnabled(testId: string, isDone: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const btn = screen.getByTestId<HTMLButtonElement>(testId);
    if (!btn.disabled) {
      fireEvent.click(btn);
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
    if (isDone()) return;
  }
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
        hasReferenceAudio: false,
        referenceAudio: null,
        voiceId: null,
        lastError: null,
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
        hasReferenceAudio: false,
        referenceAudio: null,
        voiceId: "builtin-voice-phainon",
        lastError: null,
      },
      {
        cardId: "card-imported-004",
        name: "砂金",
        state: "imported",
        source: "imported_png",
        hasAvatar: true,
        voiceState: "voice_failed",
        active: false,
        readOnly: false,
        hasReferenceAudio: false,
        referenceAudio: null,
        voiceId: null,
        lastError: "模拟音色创建失败",
      },
    ],
    selectedCardId: null,
    selectedCard: null,
    ...overrides,
  };
}

describe("CharacterVoiceSection", () => {
  it("渲染角色选择器与空提示（未选卡）", () => {
    const actions = createMockActions();
    render(<CharacterVoiceSection characterVoice={createVm()} actions={actions} />);

    expect(screen.getByTestId("character-voice-section")).toBeInTheDocument();
    expect(screen.getByText("为角色创建音色")).toBeInTheDocument();
    expect(screen.getByLabelText("选择角色")).toBeInTheDocument();
    const select = screen.getByLabelText("选择角色") as HTMLSelectElement;
    expect(Array.from(select.options).some((o) => o.text.includes("卡芙卡"))).toBe(true);
    expect(Array.from(select.options).some((o) => o.text.includes("白厄"))).toBe(true);
  });

  it("选择自定义卡后调用 cardGet 拉取音色详情", async () => {
    const actions = createMockActions();
    render(<CharacterVoiceSection characterVoice={createVm()} actions={actions} />);

    fireEvent.change(screen.getByLabelText("选择角色"), {
      target: { value: "card-saved-002" },
    });

    await waitFor(() => {
      expect(actions.cardGet).toHaveBeenCalledWith("card-saved-002");
    });
    expect(screen.getByTestId("voice-state-unconfigured")).toBeInTheDocument();
    expect(screen.getByTestId("pick-reference-btn")).toBeInTheDocument();
  });

  it("选择内置只读卡时展示只读说明，不提供创建入口", async () => {
    const actions = createMockActions();
    render(<CharacterVoiceSection characterVoice={createVm()} actions={actions} />);

    fireEvent.change(screen.getByLabelText("选择角色"), {
      target: { value: "builtin:phainon" },
    });

    await waitFor(() => {
      expect(screen.getByTestId("builtin-readonly-block")).toBeInTheDocument();
    });
    expect(screen.getByText(/内置角色只读/)).toBeInTheDocument();
    expect(screen.queryByTestId("create-voice-btn")).not.toBeInTheDocument();
  });

  it("参考音频选择成功并展示音频信息", async () => {
    const onPickFile = vi.fn().mockResolvedValue("C:/refs/kafka_ref.wav");
    const cardGet = vi
      .fn()
      .mockResolvedValueOnce(createCardGetResult())
      .mockResolvedValue(
        createCardGetResult({
          referenceAudioAsset: {
            asset_id: "ref-audio-001",
            duration_seconds: 5.2,
            size_bytes: 102400,
            mime_type: "audio/wav",
          },
        }),
      );
    const actions = createMockActions({ cardGet, voiceCardBindReference: vi.fn().mockResolvedValue({
      card_id: "card-saved-002",
      asset_id: "ref-audio-001",
      duration_seconds: 5.2,
      size_bytes: 102400,
      mime_type: "audio/wav",
    }) });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
        onPickFile={onPickFile}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("pick-reference-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("pick-reference-btn"));

    await waitFor(() => {
      expect(onPickFile).toHaveBeenCalledWith({
        title: "选择参考音频",
        filters: [
          { name: "音频文件", extensions: ["wav", "mp3", "m4a"] },
          { name: "全部文件", extensions: ["*"] },
        ],
      });
    });
    await waitFor(() => {
      expect(actions.voiceCardBindReference).toHaveBeenCalledWith(
        "card-saved-002",
        "C:/refs/kafka_ref.wav",
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("reference-audio-section")).toHaveTextContent("audio/wav");
      expect(screen.getByTestId("reference-audio-section")).toHaveTextContent("00:05");
    });
  });

  it("参考音频绑定错误如实展示原始错误", async () => {
    const onPickFile = vi.fn().mockResolvedValue("C:/refs/bad.txt");
    const error = new Error("voice_reference_invalid：仅支持 wav/mp3/m4a");
    (error as Error & { code?: string }).code = "voice_reference_invalid";
    const actions = createMockActions({
      voiceCardBindReference: vi.fn().mockRejectedValue(error),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
        onPickFile={onPickFile}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("pick-reference-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("pick-reference-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("operation-error")).toHaveTextContent(
        "voice_reference_invalid：仅支持 wav/mp3/m4a",
      );
    });
  });

  it("clone 模式创建音色成功并展示 voice_id", async () => {
    const actions = createMockActions({
      cardGet: vi
        .fn()
        .mockResolvedValueOnce(createCardGetResult())
        .mockResolvedValue(
          createCardGetResult({
            voiceState: "voice_ready",
            voiceId: "mock-voice-abc",
            creationMode: "clone",
          }),
        ),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(actions.cardGet).toHaveBeenCalledWith("card-saved-002");
    });
    // prefix 由 cardDetail 到达后的 effect 种子化为默认前缀「card」；空前缀合法但
    // 效果随时序，点击落在种子化之前会提交 {}（全量并行下偶发）。等种子落定再点。
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>("prefix-input")).toHaveValue("card");
    });
    await waitFor(() => {
      expect(screen.getByTestId("create-voice-btn")).toBeEnabled();
    });
    await clickCreateWhenEnabled(
      "create-voice-btn",
      () => (actions.voiceCardCreate as ReturnType<typeof vi.fn>).mock.calls.length > 0,
    );

    await waitFor(() => {
      expect(actions.voiceCardCreate).toHaveBeenCalledWith("card-saved-002", "clone", { prefix: "card" });
    });
    await waitFor(() => {
      expect(screen.getByTestId("voice-state-ready")).toBeInTheDocument();
      expect(screen.getByText("mock-voice-abc")).toBeInTheDocument();
    });
  });

  it("design 模式缺少声音描述词时禁用创建按钮", async () => {
    const actions = createMockActions();
    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("create-mode-design")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("create-mode-design"));

    // 全量套件并行线程竞争下 jsdom 渲染可能超过 waitFor 默认 1000ms 墙钟，
    // 断言不变，仅放宽超时窗口（曾观察到偶发闪烁失败）。
    await waitFor(
      () => {
        expect(screen.getByTestId("create-voice-btn")).toBeDisabled();
      },
      { timeout: 5000 },
    );
    expect(actions.voiceCardCreate).not.toHaveBeenCalled();
  });

  it("design 模式提交声音描述词与试听文本", async () => {
    const actions = createMockActions({
      cardGet: vi
        .fn()
        .mockResolvedValueOnce(createCardGetResult())
        .mockResolvedValue(
          createCardGetResult({
            voiceState: "voice_ready",
            voiceId: "mock-voice-design",
            creationMode: "design",
          }),
        ),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(actions.cardGet).toHaveBeenCalledWith("card-saved-002");
    });
    // cardDetail 到达后的 effect 会把 createMode 重置为 clone、prefix 种子化为「card」；
    // 必须等 effect 落定后再切 design 模式，否则输入框出现后又消失（时序竞争）。
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>("prefix-input")).toHaveValue("card");
    });

    fireEvent.click(screen.getByTestId("create-mode-design"));
    // design 表单随模式同步渲染；waitFor 保证渲染落定再填充。
    await waitFor(() => {
      expect(screen.getByTestId("voice-prompt-input")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId("voice-prompt-input"), {
      target: { value: "温柔沉稳的女声" },
    });
    fireEvent.change(screen.getByTestId("preview-text-input"), {
      target: { value: "你好，这是设计试听。" },
    });

    await waitFor(() => {
      expect(screen.getByTestId("create-voice-btn")).toBeEnabled();
    });

    await clickCreateWhenEnabled(
      "create-voice-btn",
      () => (actions.voiceCardCreate as ReturnType<typeof vi.fn>).mock.calls.length > 0,
    );

    await waitFor(() => {
      expect(actions.voiceCardCreate).toHaveBeenCalledWith("card-saved-002", "design", {
        prefix: "card",
        voicePrompt: "温柔沉稳的女声",
        previewText: "你好，这是设计试听。",
      });
    });
  });

  it("创建中状态如实展示", async () => {
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue(createCardGetResult({ voiceState: "voice_creating" })),
      voiceCardCreate: vi.fn(
        () =>
          new Promise<{ card_id: string; state: "voice_ready"; voice_id: string }>((resolve) => {
            setTimeout(() => resolve({ card_id: "card-saved-002", state: "voice_ready", voice_id: "x" }), 100);
          }),
      ),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({
          selectedCardId: "card-saved-002",
          cards: createVm().cards.map((c) =>
            c.cardId === "card-saved-002" ? { ...c, voiceState: "voice_creating" as CharacterVoiceState } : c,
          ),
        })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("create-voice-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("create-voice-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("voice-state-creating")).toBeInTheDocument();
      expect(screen.getByText("正在创建音色…")).toBeInTheDocument();
    });
  });

  it("创建失败状态展示原始错误并允许重试", async () => {
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue(
        createCardGetResult({
          voiceState: "voice_failed",
          lastError: "TTS 服务返回 402：音色创建额度已用尽",
        }),
      ),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({
          selectedCardId: "card-saved-002",
          cards: createVm().cards.map((c) =>
            c.cardId === "card-saved-002" ? { ...c, voiceState: "voice_failed" as CharacterVoiceState } : c,
          ),
        })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("voice-state-failed")).toBeInTheDocument();
    });
    expect(screen.getByTestId("voice-last-error")).toHaveTextContent(
      "TTS 服务返回 402：音色创建额度已用尽",
    );

    fireEvent.click(screen.getByTestId("retry-create-btn"));
    await waitFor(() => {
      expect(actions.voiceCardCreate).toHaveBeenCalled();
    });
  });

  it("同卡重复提交创建返回 voice_card_provision_in_progress 时如实展示", async () => {
    const error = new Error("voice_card_provision_in_progress：同卡创建中");
    (error as Error & { code?: string }).code = "voice_card_provision_in_progress";
    const actions = createMockActions({
      voiceCardCreate: vi.fn().mockRejectedValue(error),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("create-voice-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("create-voice-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("operation-error")).toHaveTextContent(
        "voice_card_provision_in_progress：同卡创建中",
      );
    });
  });

  it("就绪音色可试听", async () => {
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue(
        createCardGetResult({
          voiceState: "voice_ready",
          voiceId: "mock-voice-123",
          creationMode: "clone",
        }),
      ),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({
          selectedCardId: "card-saved-002",
          cards: createVm().cards.map((c) =>
            c.cardId === "card-saved-002"
              ? { ...c, voiceState: "voice_ready" as CharacterVoiceState, voiceId: "mock-voice-123" }
              : c,
          ),
        })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("voice-state-ready")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("preview-voice-btn"));

    await waitFor(() => {
      expect(actions.voiceCardPreview).toHaveBeenCalledWith("card-saved-002", undefined);
    });
  });

  it("试听失败时如实展示 voice_card_not_ready 原始错误", async () => {
    const error = new Error("voice_card_not_ready：卡音色未就绪");
    (error as Error & { code?: string }).code = "voice_card_not_ready";
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue(
        createCardGetResult({
          voiceState: "voice_ready",
          voiceId: "mock-voice-123",
          creationMode: "clone",
        }),
      ),
      voiceCardPreview: vi.fn().mockRejectedValue(error),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({
          selectedCardId: "card-saved-002",
          cards: createVm().cards.map((c) =>
            c.cardId === "card-saved-002"
              ? { ...c, voiceState: "voice_ready" as CharacterVoiceState, voiceId: "mock-voice-123" }
              : c,
          ),
        })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("preview-voice-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("preview-voice-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("operation-error")).toHaveTextContent(
        "voice_card_not_ready：卡音色未就绪",
      );
    });
  });

  it("解除绑定流程二次确认并调用 voiceCardUnbind", async () => {
    const actions = createMockActions({
      cardGet: vi
        .fn()
        .mockResolvedValueOnce(
          createCardGetResult({
            voiceState: "voice_ready",
            voiceId: "mock-voice-123",
          }),
        )
        .mockResolvedValue(createCardGetResult()),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({
          selectedCardId: "card-saved-002",
          cards: createVm().cards.map((c) =>
            c.cardId === "card-saved-002"
              ? { ...c, voiceState: "voice_ready" as CharacterVoiceState, voiceId: "mock-voice-123" }
              : c,
          ),
        })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("unbind-voice-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("unbind-voice-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("voice-confirm-modal")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("confirm-ok"));

    await waitFor(() => {
      expect(actions.voiceCardUnbind).toHaveBeenCalledWith("card-saved-002");
    });
  });

  it("账号未配置时展示阻塞说明并提供跳转入口", () => {
    const onScroll = vi.fn();
    const actions = createMockActions();

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ voiceConfigured: false })}
        actions={actions}
        onScrollToAccountConfig={onScroll}
      />,
    );

    expect(screen.getByTestId("account-config-block")).toBeInTheDocument();
    expect(screen.getByText(/语音服务账号未配置/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("go-to-account-config"));
    expect(onScroll).toHaveBeenCalled();
  });

  it("未接入 actions 时展示环境不可用阻塞说明", () => {
    render(<CharacterVoiceSection characterVoice={createVm({ selectedCardId: "card-saved-002" })} />);

    expect(screen.getByTestId("environment-unavailable-block")).toBeInTheDocument();
    expect(screen.getByText(/角色音色服务未接入/)).toBeInTheDocument();
    expect(screen.queryByTestId("pick-reference-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("create-voice-btn")).not.toBeInTheDocument();
  });

  it("已接入 actions 但缺少文件选择器时展示提示", async () => {
    const actions = createMockActions();
    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("pick-reference-btn")).toBeDisabled();
    });
    expect(screen.getByText(/文件选择器尚未接入/)).toBeInTheDocument();
  });

  it("voiceCardFocus 变化时同步选中并拉取详情", async () => {
    const actions = createMockActions();
    const { rerender } = render(
      <CharacterVoiceSection characterVoice={createVm()} actions={actions} />,
    );

    expect(actions.cardGet).not.toHaveBeenCalled();

    rerender(
      <CharacterVoiceSection
        characterVoice={createVm()}
        voiceCardFocus="card-saved-002"
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(actions.cardGet).toHaveBeenCalledWith("card-saved-002");
    });
  });

  it("音色前缀校验阻止非法输入", async () => {
    const actions = createMockActions();
    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("prefix-input")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("prefix-input"), { target: { value: "ABC!" } });

    expect(screen.getByText(/前缀只能是/)).toBeInTheDocument();
    expect(screen.getByTestId("create-voice-btn")).toBeDisabled();
  });

  it("clone 模式未绑定参考音频时后端返回 voice_reference_missing 并如实展示", async () => {
    const error = new Error("voice_reference_missing：clone 模式需要参考音频");
    (error as Error & { code?: string }).code = "voice_reference_missing";
    const actions = createMockActions({
      voiceCardCreate: vi.fn().mockRejectedValue(error),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("create-voice-btn")).toBeEnabled();
    });
    fireEvent.click(screen.getByTestId("create-voice-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("operation-error")).toHaveTextContent(
        "voice_reference_missing：clone 模式需要参考音频",
      );
    });
  });

  it("后端返回 voice_not_configured 时如实展示原始错误", async () => {
    const error = new Error("voice_not_configured：账号未配置语音 Key");
    (error as Error & { code?: string }).code = "voice_not_configured";
    const actions = createMockActions({ voiceCardCreate: vi.fn().mockRejectedValue(error) });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002", voiceConfigured: true })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("create-voice-btn")).toBeEnabled();
    });
    fireEvent.click(screen.getByTestId("create-voice-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("operation-error")).toHaveTextContent(
        "voice_not_configured：账号未配置语音 Key",
      );
    });
  });

  it("cardGet 仅返回字符串 reference_audio_asset 时展示资产 ID", async () => {
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue({
        card_id: "card-saved-002",
        state: "saved",
        source: "user_created",
        created_at: "2026-08-18T21:40:00+00:00",
        updated_at: "2026-08-18T21:40:00+00:00",
        read_only: false,
        avatar: null,
        card: {
          spec: "chara_card_v3",
          spec_version: "3.0",
          data: {
            name: "卡芙卡",
            extensions: {
              hsr: {
                voice_profile: {
                  voice_id: "",
                  state: "voice_unconfigured",
                  creation_mode: "",
                  prefix: "",
                  reference_audio_asset: "ref-audio-card-saved-002",
                  last_error: null,
                  updated_at: "2026-08-18T21:40:00+00:00",
                },
              },
            },
          },
        },
      }),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("reference-audio-section")).toHaveTextContent(
        "ref-audio-card-saved-002",
      );
    });
  });

  it("音色详情载入中展示加载提示", async () => {
    const actions = createMockActions({
      cardGet: vi.fn(
        () => new Promise<CardGetResult>((resolve) => setTimeout(() => resolve(createCardGetResult()), 200)),
      ),
    });

    render(
      <CharacterVoiceSection
        characterVoice={createVm({ selectedCardId: "card-saved-002" })}
        actions={actions}
      />,
    );

    expect(screen.getByTestId("detail-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByTestId("detail-loading")).not.toBeInTheDocument();
    });
  });
});
