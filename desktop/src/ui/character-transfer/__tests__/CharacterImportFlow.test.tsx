import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HarnessActions } from "../../../contracts/actions";
import type { CardImportPreviewPayload } from "../../../contracts/protocol";
import type { DesktopBackend } from "../../../services/backend";
import { CharacterImportFlow, resolveDroppedCardPath } from "../CharacterImportFlow";

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
    cardPeekImport: vi.fn().mockResolvedValue({ preview: samplePreview() }),
    cardImportJson: vi.fn().mockResolvedValue({
      card_id: "imported-1",
      name: "白厄（3.4前）",
      state: "imported",
      report: samplePreview().report,
    }),
    cardImportPng: vi.fn().mockResolvedValue({
      card_id: "imported-png-1",
      name: "白厄（3.4前）",
      state: "imported",
      report: samplePreview().report,
    }),
    cardExportJson: vi.fn().mockResolvedValue({}),
    cardExportPng: vi.fn().mockResolvedValue({}),
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

function samplePngPreview(): CardImportPreviewPayload {
  return {
    ...samplePreview(),
    format: "png",
    avatar_available: true,
    avatar_width: 512,
    avatar_height: 512,
  };
}

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
      expect(actions.cardPeekImport).toHaveBeenCalledWith("C:/Cards/bai.json");
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

  it("文件对话框打开失败如实进入错误态并保留原始错误", async () => {
    const dialogError = new Error("dialog plugin unavailable");
    const actions = createMockActions();
    const backend = createMockBackend(null);
    backend.pickFile = vi.fn().mockRejectedValue(dialogError);
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(screen.getByText("打开文件对话框失败")).toBeInTheDocument();
      expect(screen.getByText(/dialog plugin unavailable/)).toBeInTheDocument();
    });
    expect(actions.cardPeekImport).not.toHaveBeenCalled();
  });

  it("解析失败呈现原始错误摘要", async () => {
    const peekError = new Error("模拟导入失败：无法解析 C:/invalid.json");
    (peekError as Error & { code?: string }).code = "card_import_failed";
    const actions = createMockActions({
      cardPeekImport: vi.fn().mockRejectedValue(peekError),
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
      cardPeekImport: vi.fn().mockRejectedValueOnce(peekError).mockResolvedValueOnce({ preview: samplePreview() }),
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
      cardPeekImport: vi.fn().mockResolvedValue({ preview: samplePreviewWithError() }),
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

  it("StrictMode 双挂载后异步阶段仍能进入预览（mountedRef 守卫回归）", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/bai.json");
    render(
      <StrictMode>
        <CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />
      </StrictMode>,
    );

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    // StrictMode 开发构建会 mount→cleanup→再 mount；mountedRef 的 effect 体
    // 若不在重挂载时重新置 true，这里会永远停在「正在解析…」。
    await waitFor(() => {
      expect(actions.cardPeekImport).toHaveBeenCalledWith("C:/Cards/bai.json");
    });
    await waitFor(() => {
      expect(screen.getByText(/白厄（3.4前）/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/正在解析/)).not.toBeInTheDocument();
  });

  it("PNG 预览显示头像尺寸与「PNG 字节即头像」语义；确认导入分派到 cardImportPng", async () => {
    const actions = createMockActions({
      cardPeekImport: vi.fn().mockResolvedValue({ preview: samplePngPreview() }),
    });
    const backend = createMockBackend("C:/Cards/白厄.png");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(screen.getByText("PNG 卡")).toBeInTheDocument();
      expect(screen.getByText("512 × 512")).toBeInTheDocument();
      expect(screen.getByText(/PNG 字节即头像/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    await waitFor(() => {
      expect(actions.cardImportPng).toHaveBeenCalledWith("C:/Cards/白厄.png", false);
      expect(actions.cardImportJson).not.toHaveBeenCalled();
      expect(screen.getByText("导入完成")).toBeInTheDocument();
    });
  });

  it("PNG 副本导入把 as_duplicate=true 传给 cardImportPng", async () => {
    const actions = createMockActions({
      cardPeekImport: vi.fn().mockResolvedValue({ preview: samplePngPreview() }),
    });
    const backend = createMockBackend("C:/Cards/白厄.png");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));
    await waitFor(() => expect(screen.getByText("PNG 卡")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "作为副本导入" }));
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    await waitFor(() => {
      expect(actions.cardImportPng).toHaveBeenCalledWith("C:/Cards/白厄.png", true);
    });
  });

  it("PNG 预览中头像尺寸未解析时如实显示，不伪造数值", async () => {
    const actions = createMockActions({
      cardPeekImport: vi.fn().mockResolvedValue({
        preview: { ...samplePngPreview(), avatar_width: null, avatar_height: null },
      }),
    });
    const backend = createMockBackend("C:/Cards/broken-header.png");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(screen.getByText("未能解析")).toBeInTheDocument();
      expect(screen.queryByText(/×/)).not.toBeInTheDocument();
    });
  });

  it("导入分派跟随 peek 返回的 format，不信任扩展名（.png 文件但 format=json → cardImportJson）", async () => {
    const actions = createMockActions({
      cardPeekImport: vi.fn().mockResolvedValue({ preview: { ...samplePreview(), format: "json" } }),
    });
    const backend = createMockBackend("C:/Cards/伪装.png");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));
    await waitFor(() => expect(screen.getByText("JSON 卡")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    await waitFor(() => {
      expect(actions.cardImportJson).toHaveBeenCalledWith("C:/Cards/伪装.png", false);
      expect(actions.cardImportPng).not.toHaveBeenCalled();
    });
  });

  it("PNG 解析失败呈现原始错误摘要（card_import_failed）", async () => {
    const peekError = new Error("PNG 解析失败：IEND 块缺失");
    (peekError as Error & { code?: string }).code = "card_import_failed";
    const actions = createMockActions({
      cardPeekImport: vi.fn().mockRejectedValue(peekError),
    });
    const backend = createMockBackend("C:/Cards/damaged.png");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));

    await waitFor(() => {
      expect(screen.getByText("解析失败")).toBeInTheDocument();
      expect(screen.getByText(/card_import_failed/)).toBeInTheDocument();
      expect(screen.getByText(/IEND 块缺失/)).toBeInTheDocument();
    });
  });

  it("浏览器 DOM 拖放（无绝对路径）如实报错，不进入解析", async () => {
    const actions = createMockActions();
    const backend = createMockBackend("C:/Cards/bai.json");
    render(<CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} />);

    const dropzone = screen.getByRole("button", { name: "选择角色卡文件" });
    fireEvent.drop(dropzone, {
      dataTransfer: { files: [new File(["x"], "bai.png", { type: "image/png" })] },
    });

    await waitFor(() => {
      expect(screen.getByText(/不支持此操作/)).toBeInTheDocument();
      expect(screen.getByText(/浏览器环境无法从拖放文件获取绝对路径/)).toBeInTheDocument();
    });
    expect(actions.cardPeekImport).not.toHaveBeenCalled();
  });

  it("resolveDroppedCardPath：单文件通过，多文件与空拖放如实拒绝", () => {
    expect(resolveDroppedCardPath(["C:/Cards/bai.png"])).toEqual({ ok: true, path: "C:/Cards/bai.png" });
    const multi = resolveDroppedCardPath(["C:/a.png", "C:/b.png"]);
    expect(multi.ok).toBe(false);
    if (!multi.ok) expect(multi.reason).toMatch(/一次只能导入一个角色卡文件/);
    const empty = resolveDroppedCardPath([]);
    expect(empty.ok).toBe(false);
    if (!empty.ok) expect(empty.reason).toMatch(/未携带文件路径/);
  });
});
