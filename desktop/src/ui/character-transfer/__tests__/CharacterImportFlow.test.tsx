import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HarnessActions } from "../../contracts/actions";
import type { CardImportPreviewPayload } from "../../contracts/protocol";
import type { DesktopBackend } from "../../services/backend";
import { CharacterImportFlow } from "../CharacterImportFlow";

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
    cardGet: vi.fn().mockResolvedValue({}),
    cardPeekImportJson: vi.fn().mockResolvedValue({ preview: samplePreview() }),
    cardImportJson: vi.fn().mockResolvedValue({
      card_id: "imported-1",
      name: "白厄（3.4前）",
      state: "imported",
      report: samplePreview().report,
    }),
    cardExportJson: vi.fn().mockResolvedValue({}),
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

function createMockBackend(pickResult: string | null = "C:/Cards/bai.json"): DesktopBackend {
  return {
    request: vi.fn().mockResolvedValue({}),
    openChatWindow: vi.fn().mockResolvedValue(""),
    pickFolder: vi.fn().mockResolvedValue(null),
    pickFile: vi.fn().mockResolvedValue(pickResult),
    saveFile: vi.fn().mockResolvedValue(null),
    subscribe: vi.fn().mockReturnValue(() => {}),
    reconnectSidecar: vi.fn().mockResolvedValue(undefined),
  };
}

function samplePreview(): CardImportPreviewPayload {
  return {
    name: "白厄（3.4前）",
    spec_version: "3.0",
    avatar_available: false,
    greeting_count: 6,
    world_book_entries: 20,
    tags: ["星核猎手"],
    report: {
      applied: ["data.name", "data.description", "data.character_book"],
      preserved: ["data.extensions.talkativeness"],
      not_executed: ["data.extensions.hsr.command_panels"],
      normalized_from_root: [],
      warnings: ["发现未知扩展字段"],
      errors: [],
    },
  };
}

const samplePreviewWithError = (): CardImportPreviewPayload => ({
  ...samplePreview(),
  report: {
    ...samplePreview().report,
    errors: ["spec_version 缺失"],
  },
});

describe("CharacterImportFlow", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("backend 缺失时显示不可用提示", async () => {
    const actions = createMockActions();
    render(<CharacterImportFlow actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(screen.getByText(/环境不可用/)).toBeInTheDocument();
    });
    expect(screen.getByText(/当前环境未提供桌面后端/)).toBeInTheDocument();
  });

  it("完整流程：选择文件 → 预览 → 确认导入 → 成功 → 刷新列表", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/bai.json");
    const onSuccess = vi.fn();
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} onSuccess={onSuccess} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(actions.cardPeekImportJson).toHaveBeenCalledWith("C:/Cards/bai.json");
    });

    // 预览面板
    await waitFor(() => {
      expect(screen.getByText("导入预览")).toBeInTheDocument();
      expect(screen.getByText("白厄（3.4前）")).toBeInTheDocument();
      expect(screen.getByText("6")).toBeInTheDocument();
      expect(screen.getByText("20")).toBeInTheDocument();
      expect(screen.getByText(/已应用 3 项/)).toBeInTheDocument();
      expect(screen.getByText(/警告 1 项/)).toBeInTheDocument();
    });

    // 确认导入
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    await waitFor(() => {
      expect(actions.cardImportJson).toHaveBeenCalledWith("C:/Cards/bai.json", false);
    });

    await waitFor(() => {
      expect(screen.getByText("导入完成")).toBeInTheDocument();
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it("「作为副本导入」选项传入 as_duplicate=true", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/bai.json");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(screen.getByText("导入预览")).toBeInTheDocument();
    });

    const checkbox = screen.getByRole("checkbox", { name: "作为副本导入" });
    fireEvent.click(checkbox);

    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    await waitFor(() => {
      expect(actions.cardImportJson).toHaveBeenCalledWith("C:/Cards/bai.json", true);
    });
  });

  it("用户取消文件对话框保持 idle", async () => {
    const actions = createMockActions();
    const backend = createMockBackend(null);
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(backend.pickFile).toHaveBeenCalled();
    });

    expect(actions.cardPeekImportJson).not.toHaveBeenCalled();
    expect(screen.getByText("导入角色")).toBeInTheDocument();
  });

  it("解析失败呈现原始错误摘要", async () => {
    const peekError = new Error("模拟导入失败：无法解析 C:/invalid.json");
    (peekError as Error & { code?: string }).code = "card_import_failed";
    const actions = createMockActions({
      cardPeekImportJson: vi.fn().mockRejectedValue(peekError),
    });
    const backend = createMockBackend("C:/invalid.json");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(screen.getByText("解析失败")).toBeInTheDocument();
      expect(screen.getByText(/card_import_failed/)).toBeInTheDocument();
      expect(screen.getByText(/无法解析 C:\/invalid\.json/)).toBeInTheDocument();
    });
  });

  it("导入失败呈现原始错误摘要", async () => {
    const importError = new Error("模拟导入失败：无法解析 C:/bad.json");
    (importError as Error & { code?: string }).code = "card_import_failed";
    const actions = createMockActions({
      cardImportJson: vi.fn().mockRejectedValue(importError),
    });
    const backend = createMockBackend("C:/bad.json");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));
    await waitFor(() => expect(screen.getByText("导入预览")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    await waitFor(() => {
      expect(screen.getByText("导入失败")).toBeInTheDocument();
      expect(screen.getByText(/card_import_failed/)).toBeInTheDocument();
    });
  });

  it("错误态可重试", async () => {
    const peekError = new Error("fail");
    const actions = createMockActions({
      cardPeekImportJson: vi.fn().mockRejectedValueOnce(peekError).mockResolvedValueOnce({ preview: samplePreview() }),
    });
    const backend = createMockBackend("C:/retry.json");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));
    await waitFor(() => expect(screen.getByText("解析失败")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => {
      expect(screen.getByText("导入预览")).toBeInTheDocument();
    });
  });

  it("导入成功后点击「继续导入」回到 idle", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/bai.json");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));
    await waitFor(() => expect(screen.getByText("导入预览")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
    await waitFor(() => expect(screen.getByText("导入完成")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "继续导入" }));

    expect(screen.getByText("导入角色")).toBeInTheDocument();
  });

  it("显示部分成功：兼容报告含 warnings/errors 时展示摘要", async () => {
    const actions = createMockActions({
      cardPeekImportJson: vi.fn().mockResolvedValue({ preview: samplePreviewWithError() }),
    });
    const backend = createMockBackend("C:/Cards/warn.json");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      // reportSummary 将数量拼接为单行摘要
      expect(screen.getByText(/警告 1 项/)).toBeInTheDocument();
      expect(screen.getByText(/错误 1 项/)).toBeInTheDocument();
      expect(screen.getByText(/spec_version 缺失/)).toBeInTheDocument();
    });
  });
});
