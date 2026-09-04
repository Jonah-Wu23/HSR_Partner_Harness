import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HarnessActions } from "../../../contracts/actions";
import type { CardGetResult } from "../../../contracts/protocol";
import type { DesktopBackend } from "../../../services/backend";
import { CharacterExportFlow } from "../CharacterExportFlow";

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
    cardGet: vi.fn().mockResolvedValue(sampleCardGet()),
    cardPeekImportJson: vi.fn().mockResolvedValue({}),
    cardImportJson: vi.fn().mockResolvedValue({}),
    cardExportJson: vi.fn().mockResolvedValue({
      exported: true,
      path: "C:/Cards/卡芙卡.json",
      avatar_saved: true,
    }),
    cardPeekImport: vi.fn().mockResolvedValue({}),
    cardImportPng: vi.fn().mockResolvedValue({}),
    cardExportPng: vi.fn().mockResolvedValue({
      exported: true,
      path: "C:/Cards/卡芙卡.png",
      name: "卡芙卡",
      spec_version: "3.0",
      greeting_count: 6,
      world_book_entries: 20,
      extensions: ["hsr"],
    }),
    cardPublish: vi.fn().mockResolvedValue({}),
    cardSetAvatar: vi.fn().mockResolvedValue({}),
    cardRemoveAvatar: vi.fn().mockResolvedValue({}),
    voiceCardBindReference: vi.fn().mockResolvedValue({}),
    voiceCardCreate: vi.fn().mockResolvedValue({}),
    voiceCardUnbind: vi.fn().mockResolvedValue({}),
    voiceCardPreview: vi.fn().mockResolvedValue(undefined),
    voiceMobilePttStart: vi.fn().mockResolvedValue({}),
    voiceMobileAudioChunk: vi.fn().mockResolvedValue(undefined),
    voiceMobilePttStop: vi.fn().mockResolvedValue({}),
    voiceMobileTtsStop: vi.fn().mockResolvedValue(undefined),
    issuePairingCode: vi.fn().mockResolvedValue(undefined),
    listRemoteDevices: vi.fn().mockResolvedValue(undefined),
    revokeRemoteDevice: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as HarnessActions;
}

function createMockBackend(saveResult: string | null = "C:/Cards/卡芙卡.json"): DesktopBackend {
  return {
    request: vi.fn().mockResolvedValue({}),
    openChatWindow: vi.fn().mockResolvedValue(""),
    pickFolder: vi.fn().mockResolvedValue(null),
    pickFile: vi.fn().mockResolvedValue(null),
    saveFile: vi.fn().mockResolvedValue(saveResult),
    subscribe: vi.fn().mockReturnValue(() => {}),
    reconnectSidecar: vi.fn().mockResolvedValue(undefined),
  };
}

function sampleCardGet(overrides: Partial<CardGetResult> = {}): CardGetResult {
  return {
    card_id: "card-saved-002",
    state: "saved",
    source: "user_created",
    created_at: "2026-08-18T21:40:00+00:00",
    updated_at: "2026-08-18T21:40:00+00:00",
    read_only: false,
    avatar: { mime_type: "image/png", data_base64: "abc" },
    card: {
      spec: "chara_card_v3",
      spec_version: "3.0",
      data: {
        name: "卡芙卡",
        description: "",
        personality: "",
        scenario: "",
        first_mes: "",
        mes_example: "",
        creator_notes: "",
        system_prompt: "",
        post_history_instructions: "",
        tags: [],
        creator: "",
        character_version: "1",
        alternate_greetings: [],
        character_book: {
          entries: [{ name: "entry1" }, { name: "entry2" }],
        },
        extensions: {
          hsr: {},
          talkativeness: 0.5,
        },
      },
    },
    ...overrides,
  };
}

describe("CharacterExportFlow", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("backend 缺失时显示不可用提示", async () => {
    const actions = createMockActions();
    render(<CharacterExportFlow cardId="card-1" cardName="卡芙卡" actions={actions} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("导出角色")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(screen.getByText(/环境不可用/)).toBeInTheDocument();
      expect(screen.getByText(/当前环境未提供桌面后端/)).toBeInTheDocument();
    });
  });

  it("完整流程：加载卡 → 确认面板 → 导出 → 成功", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/卡芙卡.json");
    const onSuccess = vi.fn();
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />,
    );

    await waitFor(() => {
      expect(actions.cardGet).toHaveBeenCalledWith("card-saved-002");
    });

    // 确认面板
    await waitFor(() => {
      expect(screen.getByLabelText("导出文件名")).toHaveValue("卡芙卡.json");
      expect(screen.getByText("2 条已包含")).toBeInTheDocument();
      expect(screen.getByText("hsr、talkativeness 等 2 项")).toBeInTheDocument();
      expect(screen.getByText("已绑定头像")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(backend.saveFile).toHaveBeenCalledWith({
        title: "导出角色卡",
        defaultPath: "卡芙卡.json",
        filters: [{ name: "Character Card JSON", extensions: ["json"] }],
      });
    });

    await waitFor(() => {
      expect(actions.cardExportJson).toHaveBeenCalledWith("card-saved-002", "C:/Cards/卡芙卡.json", true);
      expect(screen.getByText("导出完成")).toBeInTheDocument();
      expect(screen.getByText("C:/Cards/卡芙卡.json")).toBeInTheDocument();
      expect(screen.getByText("头像文件已配套保存")).toBeInTheDocument();
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it("取消保存对话框保持确认态", async () => {
    const actions = createMockActions();
    const backend = createMockBackend(null);
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("导出角色")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => expect(backend.saveFile).toHaveBeenCalled());

    expect(actions.cardExportJson).not.toHaveBeenCalled();
    expect(screen.getByLabelText("导出文件名")).toBeInTheDocument();
  });

  it("保存对话框打开失败如实进入错误态并保留原始错误", async () => {
    const actions = createMockActions();
    const backend = createMockBackend(null);
    backend.saveFile = vi.fn().mockRejectedValue(new Error("dialog plugin unavailable"));
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("导出角色")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(screen.getByText("打开保存对话框失败")).toBeInTheDocument();
      expect(screen.getByText(/dialog plugin unavailable/)).toBeInTheDocument();
    });
    expect(actions.cardExportJson).not.toHaveBeenCalled();
  });

  it("内置卡导出显示 read-only 引导并提供复制入口", async () => {
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue(sampleCardGet({ card_id: "builtin:phainon", read_only: true })),
    });
    const backend = createMockBackend("C:/Cards/白厄.json");
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    render(
      <CharacterExportFlow
        cardId="builtin:phainon"
        cardName="白厄"
        backend={backend}
        actions={actions}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("内置角色卡不可导出")).toBeInTheDocument();
      expect(screen.getByText(/内置角色卡只读/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "复制此卡" }));

    await waitFor(() => {
      expect(actions.duplicateCard).toHaveBeenCalledWith("builtin:phainon");
      expect(onSuccess).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("导出失败呈现原始错误摘要", async () => {
    const exportError = new Error("EACCES: 无法写入目录");
    (exportError as Error & { code?: string }).code = "card_export_failed";
    const actions = createMockActions({
      cardExportJson: vi.fn().mockRejectedValue(exportError),
    });
    const backend = createMockBackend("C:/Cards/卡芙卡.json");
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("导出角色")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(screen.getByText("导出失败")).toBeInTheDocument();
      expect(screen.getByText(/EACCES: 无法写入目录/)).toBeInTheDocument();
    });
  });

  it("save_avatar 勾选状态正确传入", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/卡芙卡.json");
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("导出角色")).toBeInTheDocument());

    const checkbox = screen.getByRole("checkbox", { name: "同时保存头像文件" });
    fireEvent.click(checkbox); // 默认 true，点击后 false

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(actions.cardExportJson).toHaveBeenCalledWith("card-saved-002", "C:/Cards/卡芙卡.json", false);
    });
  });

  it("无头像时显示无头像状态", async () => {
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue(sampleCardGet({ avatar: null })),
    });
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("无头像，JSON 中只保留引用")).toBeInTheDocument();
    });
  });

  it("加载卡失败显示错误", async () => {
    const actions = createMockActions({
      cardGet: vi.fn().mockRejectedValue(new Error("卡不存在")),
    });
    render(
      <CharacterExportFlow
        cardId="card-missing"
        cardName="missing"
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("加载角色卡失败")).toBeInTheDocument();
      expect(screen.getByText(/卡不存在/)).toBeInTheDocument();
    });
  });

  it("切换 PNG 格式：文件名扩展联动，导出调用 cardExportPng，成功展示 §1.3 结果字段", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/卡芙卡.png");
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("导出角色")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("radio", { name: "PNG 格式" }));

    expect(screen.getByLabelText("导出文件名")).toHaveValue("卡芙卡.png");
    // PNG 头像内嵌，不出现「另存头像文件」选项
    expect(screen.queryByRole("checkbox", { name: "同时保存头像文件" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(backend.saveFile).toHaveBeenCalledWith({
        title: "导出角色卡 PNG",
        defaultPath: "卡芙卡.png",
        filters: [{ name: "PNG Character Card", extensions: ["png"] }],
      });
    });

    await waitFor(() => {
      expect(actions.cardExportPng).toHaveBeenCalledWith("card-saved-002", "C:/Cards/卡芙卡.png");
      expect(screen.getByText("导出完成")).toBeInTheDocument();
      expect(screen.getByText("C:/Cards/卡芙卡.png")).toBeInTheDocument();
      expect(screen.getByText("卡芙卡")).toBeInTheDocument();
      expect(screen.getByText("Character Card v3.0")).toBeInTheDocument();
      expect(screen.getByText("hsr")).toBeInTheDocument();
      expect(screen.getByText(/头像已内嵌 PNG 图像块/)).toBeInTheDocument();
    });
  });

  it("无头像卡选 PNG：预览面板如实警告，导出被后端真实拒绝后呈现原始错误与设置头像引导", async () => {
    const exportError = new Error("卡未设置头像，请先设置头像后再导出 PNG");
    (exportError as Error & { code?: string }).code = "card_export_failed";
    const actions = createMockActions({
      cardGet: vi.fn().mockResolvedValue(sampleCardGet({ avatar: null })),
      cardExportPng: vi.fn().mockRejectedValue(exportError),
    });
    const backend = createMockBackend("C:/Cards/卡芙卡.png");
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("导出角色")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("radio", { name: "PNG 格式" }));

    expect(screen.getByText("未设置头像，PNG 导出将被拒绝")).toBeInTheDocument();
    expect(screen.getByText(/导出将被后端拒绝/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(actions.cardExportPng).toHaveBeenCalledWith("card-saved-002", "C:/Cards/卡芙卡.png");
      expect(screen.getByText("导出失败")).toBeInTheDocument();
      expect(screen.getByText(/card_export_failed/)).toBeInTheDocument();
      expect(screen.getByText(/卡未设置头像，请先设置头像后再导出 PNG/)).toBeInTheDocument();
      expect(screen.getByText("PNG 导出需要头像")).toBeInTheDocument();
      expect(screen.getByText(/请先在角色编辑页为该卡设置头像/)).toBeInTheDocument();
    });
  });

  it("JSON 格式（默认）的导出行为与头像行文案保持不变", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/卡芙卡.json");
    render(
      <CharacterExportFlow
        cardId="card-saved-002"
        cardName="卡芙卡"
        backend={backend}
        actions={actions}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("导出角色")).toBeInTheDocument());

    expect(screen.getByRole("radio", { name: "JSON 格式" })).toBeChecked();
    expect(screen.getByText("已绑定头像")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "导出" }));

    await waitFor(() => {
      expect(actions.cardExportJson).toHaveBeenCalledWith("card-saved-002", "C:/Cards/卡芙卡.json", true);
      expect(screen.getByText("头像文件已配套保存")).toBeInTheDocument();
    });
    expect(actions.cardExportPng).not.toHaveBeenCalled();
  });
});
