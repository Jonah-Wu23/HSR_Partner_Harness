import { cleanup, fireEvent, render, screen, within, act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HarnessActions } from "../../../contracts/actions";
import type { CharacterCreateViewModel } from "../../../contracts/view-models";
import { CharacterCreatePage } from "../CharacterCreatePage";

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
    cardGet: vi.fn().mockResolvedValue({
      card_id: "draft-123",
      state: "draft",
      source: "user_created",
      created_at: "",
      updated_at: "",
      card: {},
      read_only: false,
      avatar: null,
    }),
    cardPeekImportJson: vi.fn().mockResolvedValue({ preview: {} as never }),
    cardPeekImport: vi.fn().mockResolvedValue({ preview: {} as never }),
    cardImportJson: vi.fn().mockResolvedValue({ card_id: "", name: "", state: "imported", report: {} as never }),
    cardImportPng: vi.fn().mockResolvedValue({ card_id: "", name: "", state: "imported", report: {} as never }),
    cardExportJson: vi.fn().mockResolvedValue({ exported: true, path: "", avatar_saved: false }),
    cardExportPng: vi.fn().mockResolvedValue({ exported: true, path: "", name: "", spec_version: "3.0", greeting_count: 0, world_book_entries: 0, extensions: [] }),
    cardPublish: vi.fn().mockResolvedValue({ card_id: "draft-123", state: "saved" }),
    cardSetAvatar: vi.fn().mockResolvedValue({ card_id: "draft-123", asset_id: "avatar-1", mime_type: "image/png" }),
    cardRemoveAvatar: vi.fn().mockResolvedValue({ card_id: "draft-123", removed: true }),
    powerGetStatus: vi.fn().mockResolvedValue({
      supported: false,
      platform: "windows",
      plan_name: "",
      ac_sleep_timeout_seconds: null,
      dc_sleep_timeout_seconds: null,
      remote_serve_enabled: false,
      threshold_seconds: 900,
      at_risk: false,
      reason: "",
      checked_at: "",
    }),
    voiceCardBindReference: vi.fn().mockResolvedValue({ card_id: "", asset_id: "", duration_seconds: 0, size_bytes: 0, mime_type: "" }),
    voiceCardCreate: vi.fn().mockResolvedValue({ card_id: "", state: "voice_ready", voice_id: "" }),
    voiceCardUnbind: vi.fn().mockResolvedValue({ card_id: "", state: "voice_unconfigured" }),
    voiceCardPreview: vi.fn().mockResolvedValue(undefined),
    voiceMobilePttStart: vi.fn().mockResolvedValue({ session_id: "" }),
    voiceMobileAudioChunk: vi.fn().mockResolvedValue(undefined),
    voiceMobilePttStop: vi.fn().mockResolvedValue({ session_id: "", transcript: "", conversation_id: "" }),
    voiceMobileTtsStop: vi.fn().mockResolvedValue(undefined),
    issuePairingCode: vi.fn().mockResolvedValue(undefined),
    listRemoteDevices: vi.fn().mockResolvedValue(undefined),
    revokeRemoteDevice: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const defaultVm: CharacterCreateViewModel = {
  cardId: null,
  card: null,
  readOnly: false,
  loading: false,
  error: null,
};

describe("CharacterCreatePage", () => {
  let originalCreateObjectURL: typeof URL.createObjectURL | undefined;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL | undefined;

  beforeEach(() => {
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:mock-preview-url") as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    if (originalCreateObjectURL) URL.createObjectURL = originalCreateObjectURL;
    if (originalRevokeObjectURL) URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("基础渲染：渲染标题、输入项、操作按钮与实时预览", () => {
    const actions = createMockActions();
    render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

    expect(screen.getByTestId("character-create-page")).toBeInTheDocument();
    expect(screen.getByLabelText(/名称/)).toBeInTheDocument();
    expect(screen.getByLabelText(/标签/)).toBeInTheDocument();
    expect(screen.getByLabelText(/简介/)).toBeInTheDocument();
    expect(screen.getByLabelText(/性格/)).toBeInTheDocument();
    expect(screen.getByLabelText(/对话场景/)).toBeInTheDocument();
    expect(screen.getByLabelText(/第一条消息/)).toBeInTheDocument();
    expect(screen.getByLabelText(/示例对话/)).toBeInTheDocument();
    expect(screen.getByTestId("btn-draft")).toBeInTheDocument();
    expect(screen.getByTestId("btn-submit")).toBeInTheDocument();
    expect(screen.getByTestId("live-preview")).toBeInTheDocument();
  });

  describe("名称必填校验 (Name validation)", () => {
    it("空名称点击保存草稿或完成创建时阻止保存并显示字段级错误", async () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const submitBtn = screen.getByTestId("btn-submit");
      fireEvent.click(submitBtn);

      expect(actions.createCardDraft).not.toHaveBeenCalled();
      expect(actions.updateCard).not.toHaveBeenCalled();
      expect(
        screen.getByText("名称为必填项，填写后才能完成创建"),
      ).toBeInTheDocument();
      expect(screen.getByLabelText(/名称/)).toHaveAttribute("aria-invalid", "true");
    });

    it("输入名称后错误信息自动清除", async () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.click(screen.getByTestId("btn-submit"));
      expect(screen.getByText("名称为必填项，填写后才能完成创建")).toBeInTheDocument();

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "卡芙卡" } });

      expect(screen.queryByText("名称为必填项，填写后才能完成创建")).not.toBeInTheDocument();
      expect(nameInput).toHaveAttribute("aria-invalid", "false");
    });
  });

  describe("标签增删 (Tags management)", () => {
    it("输入标签按回车添加，并在表单与预览区同步展示", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const tagInput = screen.getByLabelText("添加标签");
      fireEvent.change(tagInput, { target: { value: "星核猎手" } });
      fireEvent.keyDown(tagInput, { key: "Enter" });

      const tagList = screen.getByTestId("tag-list");
      expect(within(tagList).getByText("星核猎手")).toBeInTheDocument();
      expect(screen.getByTestId("preview-tags")).toHaveTextContent("星核猎手");
      expect(tagInput).toHaveValue("");

      // 添加第二个标签
      fireEvent.change(tagInput, { target: { value: "冷静" } });
      fireEvent.keyDown(tagInput, { key: "Enter" });

      expect(within(tagList).getByText("冷静")).toBeInTheDocument();
      expect(screen.getByTestId("preview-tags")).toHaveTextContent("冷静");
    });

    it("点击删除按钮移除标签", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const tagInput = screen.getByLabelText("添加标签");
      fireEvent.change(tagInput, { target: { value: "待删除标签" } });
      fireEvent.keyDown(tagInput, { key: "Enter" });

      const tagList = screen.getByTestId("tag-list");
      expect(within(tagList).getByText("待删除标签")).toBeInTheDocument();

      const delBtn = screen.getByLabelText("删除标签「待删除标签」");
      fireEvent.click(delBtn);

      expect(within(tagList).queryByText("待删除标签")).not.toBeInTheDocument();
      expect(screen.getByTestId("preview-tags")).toHaveTextContent("未添加标签");
    });

    it("空标签或重复标签不重复添加", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const tagInput = screen.getByLabelText("添加标签");
      fireEvent.change(tagInput, { target: { value: "   " } });
      fireEvent.keyDown(tagInput, { key: "Enter" });

      expect(screen.getByTestId("preview-tags")).toHaveTextContent("未添加标签");

      fireEvent.change(tagInput, { target: { value: "唯一标签" } });
      fireEvent.keyDown(tagInput, { key: "Enter" });
      fireEvent.change(tagInput, { target: { value: "唯一标签" } });
      fireEvent.keyDown(tagInput, { key: "Enter" });

      const tagList = screen.getByTestId("tag-list");
      const tagsInList = within(tagList).getAllByText("唯一标签");
      expect(tagsInList).toHaveLength(1);
    });
  });

  describe("字数计数与上限 (Character counters & limits)", () => {
    it("人格设定四个字段实时显示字数统计并限制 2000 字上限", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const personalityInput = screen.getByLabelText(/性格/);
      fireEvent.change(personalityInput, { target: { value: "温和冷静，运筹帷幄" } });
      expect(screen.getByTestId("count-personality")).toHaveTextContent("9 / 2000 字");
      expect(personalityInput).toHaveAttribute("maxLength", "2000");

      const scenarioInput = screen.getByLabelText(/对话场景/);
      fireEvent.change(scenarioInput, { target: { value: "空间站黑塔" } });
      expect(screen.getByTestId("count-scenario")).toHaveTextContent("5 / 2000 字");
      expect(scenarioInput).toHaveAttribute("maxLength", "2000");

      const firstMsgInput = screen.getByLabelText(/第一条消息/);
      fireEvent.change(firstMsgInput, { target: { value: "好久不见。" } });
      expect(screen.getByTestId("count-first-msg")).toHaveTextContent("5 / 2000 字");
      expect(firstMsgInput).toHaveAttribute("maxLength", "2000");

      const exampleInput = screen.getByLabelText(/示例对话/);
      fireEvent.change(exampleInput, { target: { value: "<START>" } });
      expect(screen.getByTestId("count-example")).toHaveTextContent("7 / 2000 字");
      expect(exampleInput).toHaveAttribute("maxLength", "2000");
    });
  });

  describe("头像体验 (Avatar)", () => {
    it("未设置头像时使用名称首字符占位", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      expect(screen.getByTestId("avatar-preview")).toHaveTextContent("?");

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "流萤" } });

      expect(screen.getByTestId("avatar-preview")).toHaveTextContent("流");
    });

    it("有 cardId 时选择头像调用 cardSetAvatar 并刷新预览", async () => {
      const actions = createMockActions({
        cardGet: vi.fn().mockResolvedValue({
          card_id: "draft-123",
          state: "draft",
          source: "user_created",
          created_at: "",
          updated_at: "",
          card: {},
          read_only: false,
          avatar: { mime_type: "image/png", data_base64: "iVBORw0KGgo=" },
        }),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "头像测试" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      expect(actions.createCardDraft).toHaveBeenCalledWith("头像测试");

      const fileInput = screen.getByTestId("avatar-file-input");
      const file = new File(["png"], "avatar.png", { type: "image/png" });

      await act(async () => {
        fireEvent.change(fileInput, { target: { files: [file] } });
      });

      await waitFor(() => {
        expect(actions.cardSetAvatar).toHaveBeenCalledWith("draft-123", "avatar.png");
        expect(actions.cardGet).toHaveBeenCalledWith("draft-123");
      });
    });

    it("不支持的图片格式显示真实错误", async () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "格式测试" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      const fileInput = screen.getByTestId("avatar-file-input");
      const file = new File(["gif"], "avatar.gif", { type: "image/gif" });

      await act(async () => {
        fireEvent.change(fileInput, { target: { files: [file] } });
      });

      expect(screen.getByTestId("avatar-error")).toHaveTextContent("不支持该图片格式");
      expect(actions.cardSetAvatar).not.toHaveBeenCalled();
    });

    it("移除头像调用 cardRemoveAvatar", async () => {
      const actions = createMockActions({
        cardGet: vi.fn().mockResolvedValue({
          card_id: "draft-123",
          state: "draft",
          source: "user_created",
          created_at: "",
          updated_at: "",
          card: {},
          read_only: false,
          avatar: { mime_type: "image/png", data_base64: "iVBORw0KGgo=" },
        }),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "移除测试" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      await waitFor(() => {
        expect(screen.getByTestId("btn-remove-avatar")).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-remove-avatar"));
      });

      await waitFor(() => {
        expect(actions.cardRemoveAvatar).toHaveBeenCalledWith("draft-123");
      });
    });
  });

  describe("保存态机流转 (Save state machine)", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("防抖自动保存态机：未保存更改 → 保存中… → 已保存 HH:MM:SS", async () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "银狼" } });

      // 刚改动时处于未保存状态
      expect(screen.getByTestId("save-status-unsaved")).toHaveTextContent("未保存更改");

      // 快进防抖计时器
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });

      expect(actions.createCardDraft).toHaveBeenCalledWith("银狼");
      expect(actions.updateCard).toHaveBeenCalledWith(
        "draft-123",
        expect.objectContaining({
          data: expect.objectContaining({ name: "银狼" }),
        }),
      );

      expect(screen.getByTestId("save-status-saved")).toHaveTextContent(/已保存 \d{2}:\d{2}:\d{2}/);
    });

    it("首次保存调用 createCardDraft 拿 cardId，后续保存直接 updateCard", async () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "砂金" } });

      // 手动触发第一次保存
      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      expect(actions.createCardDraft).toHaveBeenCalledTimes(1);
      expect(actions.createCardDraft).toHaveBeenCalledWith("砂金");
      expect(actions.updateCard).toHaveBeenCalledWith(
        "draft-123",
        expect.objectContaining({
          data: expect.objectContaining({ name: "砂金" }),
        }),
      );

      // 修改简介再次保存
      const descInput = screen.getByLabelText(/简介/);
      fireEvent.change(descInput, { target: { value: "战略投资部高级干部" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      // 不再重复调用 createCardDraft，继续调用 updateCard
      expect(actions.createCardDraft).toHaveBeenCalledTimes(1);
      expect(actions.updateCard).toHaveBeenCalledTimes(2);
      expect(actions.updateCard).toHaveBeenLastCalledWith(
        "draft-123",
        expect.objectContaining({
          data: expect.objectContaining({
            name: "砂金",
            description: "战略投资部高级干部",
          }),
        }),
      );
    });
  });

  describe("保存失败保留输入 (Let It Fail)", () => {
    it("保存抛出异常时展示真实错误信息，表单与预览数据绝对不丢失", async () => {
      const actions = createMockActions({
        createCardDraft: vi.fn().mockRejectedValue(new Error("Sidecar SQLite 磁盘写入失败: 0x80070070")),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const nameInput = screen.getByLabelText(/名称/);
      const descInput = screen.getByLabelText(/简介/);
      fireEvent.change(nameInput, { target: { value: "测试角色" } });
      fireEvent.change(descInput, { target: { value: "重要草稿不可丢" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      // 真实错误暴露在界面
      expect(screen.getByTestId("save-error-banner")).toHaveTextContent(
        "保存失败：Sidecar SQLite 磁盘写入失败: 0x80070070",
      );
      expect(screen.getByTestId("save-status-error")).toBeInTheDocument();

      // 用户输入内容完全保留
      expect(nameInput).toHaveValue("测试角色");
      expect(descInput).toHaveValue("重要草稿不可丢");
      expect(screen.getByTestId("preview-name")).toHaveTextContent("测试角色");
      expect(screen.getByTestId("preview-summary")).toHaveTextContent("重要草稿不可丢");
    });
  });

  describe("发布与开始对话 (Publish & Start Chat)", () => {
    it("完成创建按钮保存并发布草稿", async () => {
      const actions = createMockActions({
        // 发布后刷新 card.get 应返回 saved 状态，使按钮切换为「开始对话」。
        cardGet: vi.fn().mockResolvedValue({
          card_id: "draft-123",
          state: "saved",
          source: "user_created",
          created_at: "",
          updated_at: "",
          card: {},
          read_only: false,
          avatar: null,
        }),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "发布角色" } });
      fireEvent.change(screen.getByLabelText(/第一条消息/), { target: { value: "你好。" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-submit"));
      });

      expect(actions.createCardDraft).toHaveBeenCalledWith("发布角色");
      expect(actions.updateCard).toHaveBeenCalledWith(
        "draft-123",
        expect.objectContaining({
          data: expect.objectContaining({ name: "发布角色", first_mes: "你好。" }),
        }),
      );
      expect(actions.cardPublish).toHaveBeenCalledWith("draft-123");
      expect(actions.cardGet).toHaveBeenCalledWith("draft-123");
      expect(screen.getAllByTestId("btn-start-chat").length).toBeGreaterThanOrEqual(1);
    });

    it("发布校验错误如实呈现缺什么", async () => {
      const actions = createMockActions({
        cardPublish: vi.fn().mockRejectedValue(new Error("card_publish_invalid：缺少 first_mes")),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "缺首句" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-submit"));
      });

      await waitFor(() => {
        expect(screen.getByTestId("publish-error")).toHaveTextContent("card_publish_invalid：缺少 first_mes");
      });
    });

    it("已发布卡片显示开始对话按钮并走 selectActiveCard + createConversation + openChat", async () => {
      const actions = createMockActions({
        cardGet: vi.fn().mockResolvedValue({
          card_id: "card-saved-002",
          state: "saved",
          source: "user_created",
          created_at: "",
          updated_at: "",
          card: {},
          read_only: false,
          avatar: null,
        }),
      });
      const publishedVm: CharacterCreateViewModel = {
        cardId: "card-saved-002",
        card: {
          spec: "chara_card_v3",
          spec_version: "3.0",
          data: {
            name: "卡芙卡",
            description: "星核猎手成员",
            tags: ["星核猎手"],
            personality: "冷静果决",
            scenario: "未知星域",
            first_mes: "准备好了吗？",
            mes_example: "",
          },
        },
        readOnly: false,
        loading: false,
        error: null,
      };
      render(<CharacterCreatePage vm={publishedVm} actions={actions} />);

      await waitFor(() => {
        expect(screen.getAllByTestId("btn-start-chat").length).toBeGreaterThanOrEqual(1);
      });

      await act(async () => {
        fireEvent.click(screen.getAllByTestId("btn-start-chat")[0]);
      });

      expect(actions.selectActiveCard).toHaveBeenCalledWith("card-saved-002");
      expect(actions.createConversation).toHaveBeenCalled();
      expect(actions.openChat).toHaveBeenCalled();
    });
  });

  describe("高级字段编辑 (Advanced editor)", () => {
    it("切换到高级编辑可编辑系统提示、历史后指令、备选问候、群组问候", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      expect(screen.getByTestId("advanced-panel")).toBeInTheDocument();

      // 系统提示
      expect(screen.getByTestId("tree-item-sys")).toBeInTheDocument();
      fireEvent.change(screen.getByTestId("f-system-prompt"), { target: { value: "你是测试角色" } });
      expect(screen.getByTestId("f-system-prompt")).toHaveValue("你是测试角色");

      // 历史后指令
      fireEvent.click(screen.getByTestId("tree-item-post"));
      fireEvent.change(screen.getByTestId("f-post-history"), { target: { value: "保持冷静" } });
      expect(screen.getByTestId("f-post-history")).toHaveValue("保持冷静");

      // 备选问候
      fireEvent.click(screen.getByTestId("tree-item-altgreet"));
      fireEvent.click(screen.getByTestId("btn-add-greeting"));
      fireEvent.change(screen.getByTestId("greeting-input-0"), { target: { value: "问候一" } });
      fireEvent.click(screen.getByTestId("greeting-done-0"));
      expect(screen.getByTestId("greeting-text-0")).toHaveTextContent("问候一");

      // 群组问候
      fireEvent.click(screen.getByTestId("tree-item-groupgreet"));
      fireEvent.change(screen.getByTestId("f-group-greet"), { target: { value: "大家好" } });
      expect(screen.getByTestId("f-group-greet")).toHaveValue("大家好");
    });

    it("高级字段编辑后返回快速创建保留数据", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.change(screen.getByTestId("f-system-prompt"), { target: { value: "系统提示保留" } });
      fireEvent.click(screen.getByTestId("btn-return-quick"));

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      expect(screen.getByTestId("f-system-prompt")).toHaveValue("系统提示保留");
    });

    describe("V0.3.7 世界书与 mufy 接线 (V1/V2/V3 wiring)", () => {
      const wiredCardVm: CharacterCreateViewModel = {
        cardId: "card-001",
        card: {
          spec: "chara_card_v3",
          spec_version: "3.0",
          data: {
            name: "临海角色",
            description: "",
            personality: "",
            scenario: "",
            first_mes: "",
            mes_example: "",
            character_book: {
              name: "临海世界书",
              entries: [
                {
                  keys: ["临海"],
                  content: "临海是一座永远下雨的港口城市。",
                  comment: "世界观总纲",
                  enabled: true,
                  insertion_order: 100,
                  constant: false,
                  selective: false,
                  position: "before_char",
                },
              ],
            },
            extensions: {
              hsr: {
                world_architecture: {
                  world_foundation: { one_line_pitch: "一座永远下雨的港口城市。" },
                },
                legacy_note: "旧版字段",
              },
            },
          },
        },
        readOnly: false,
        loading: false,
        error: null,
      };

      beforeEach(() => {
        vi.useFakeTimers();
      });

      afterEach(() => {
        vi.useRealTimers();
      });

      it("世界书分区接 WorldBookEditor：条目编辑合并回整卡 JSON 并随防抖保存经 card.update 提交", async () => {
        const actions = createMockActions();
        render(<CharacterCreatePage vm={wiredCardVm} actions={actions} />);

        fireEvent.click(screen.getByTestId("mode-btn-advanced"));
        fireEvent.click(screen.getByTestId("tree-item-worldbook"));

        expect(screen.getByTestId("wb-editor")).toBeInTheDocument();
        expect(screen.getByTestId("wb-entry-row-0")).toHaveTextContent("世界观总纲");
        expect(screen.queryByText(/完整字段编辑随/)).not.toBeInTheDocument();

        fireEvent.click(screen.getByTestId("wb-entry-toggle-0"));
        fireEvent.change(screen.getByTestId("wb-entry-0-content"), {
          target: { value: "临海永远下雨。" },
        });

        expect(screen.getByTestId("save-status-unsaved")).toBeInTheDocument();
        expect(actions.updateCard).not.toHaveBeenCalled();

        await act(async () => {
          vi.advanceTimersByTime(1000);
        });

        expect(actions.updateCard).toHaveBeenCalledWith(
          "card-001",
          expect.objectContaining({
            data: expect.objectContaining({
              name: "临海角色",
              character_book: expect.objectContaining({
                name: "临海世界书",
                entries: [
                  expect.objectContaining({
                    keys: ["临海"],
                    content: "临海永远下雨。",
                    comment: "世界观总纲",
                    insertion_order: 100,
                    position: "before_char",
                  }),
                ],
              }),
            }),
          }),
        );
      });

      it("mufy 分区接 MufyAdvancedEditor：hsr 编辑合并回 extensions.hsr，未识别键原样保留", async () => {
        const actions = createMockActions();
        render(<CharacterCreatePage vm={wiredCardVm} actions={actions} />);

        fireEvent.click(screen.getByTestId("mode-btn-advanced"));
        fireEvent.click(screen.getByTestId("tree-item-mufy"));

        expect(screen.getByTestId("mufy-advanced-editor")).toBeInTheDocument();
        expect(screen.getByTestId("mufy-block-world_architecture")).toBeInTheDocument();
        expect(screen.queryByText(/完整字段编辑随/)).not.toBeInTheDocument();

        fireEvent.change(
          screen.getByTestId("mufy-value-world_architecture.world_foundation.one_line_pitch"),
          { target: { value: "永不晴天。" } },
        );

        await act(async () => {
          vi.advanceTimersByTime(1000);
        });

        expect(actions.updateCard).toHaveBeenCalledWith(
          "card-001",
          expect.objectContaining({
            data: expect.objectContaining({
              extensions: expect.objectContaining({
                hsr: expect.objectContaining({
                  world_architecture: { world_foundation: { one_line_pitch: "永不晴天。" } },
                  legacy_note: "旧版字段",
                }),
              }),
            }),
          }),
        );
      });

      it("新建卡在 mufy 分区添加内容后，自动保存生成带 extensions.hsr 的整卡 JSON", async () => {
        const actions = createMockActions();
        render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

        fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "新角色" } });

        fireEvent.click(screen.getByTestId("mode-btn-advanced"));
        fireEvent.click(screen.getByTestId("tree-item-mufy"));
        fireEvent.click(screen.getByTestId("mufy-add-world_architecture.world_foundation"));

        await act(async () => {
          vi.advanceTimersByTime(1000);
        });

        expect(actions.createCardDraft).toHaveBeenCalledWith("新角色");
        expect(actions.updateCard).toHaveBeenCalledWith(
          "draft-123",
          expect.objectContaining({
            data: expect.objectContaining({
              extensions: expect.objectContaining({
                hsr: { world_architecture: { world_foundation: {} } },
              }),
            }),
          }),
        );
      });

      it("原始数据分区保持只读 JSON 核对视图，实时反映最新编辑", () => {
        const actions = createMockActions();
        render(<CharacterCreatePage vm={wiredCardVm} actions={actions} />);

        fireEvent.click(screen.getByTestId("mode-btn-advanced"));
        fireEvent.click(screen.getByTestId("tree-item-raw"));

        const rawView = screen.getByTestId("raw-json-view");
        expect(rawView.tagName).toBe("PRE");
        expect(rawView).toHaveTextContent("character_book");
        expect(rawView).toHaveTextContent("one_line_pitch");
        expect(within(rawView).queryByRole("textbox")).not.toBeInTheDocument();
      });

      it("内置只读卡：readOnly 透传给世界书与 mufy 编辑器，不提供编辑入口", () => {
        const actions = createMockActions();
        render(<CharacterCreatePage vm={{ ...wiredCardVm, cardId: "builtin:baihe", readOnly: true }} actions={actions} />);

        fireEvent.click(screen.getByTestId("mode-btn-advanced"));
        fireEvent.click(screen.getByTestId("tree-item-worldbook"));

        expect(screen.getByTestId("wb-editor")).toBeInTheDocument();
        expect(screen.getByTestId("wb-entry-row-0")).toBeInTheDocument();
        expect(screen.queryByTestId("wb-add-entry")).not.toBeInTheDocument();
        expect(screen.queryByTestId("wb-entry-remove-0")).not.toBeInTheDocument();

        fireEvent.click(screen.getByTestId("tree-item-mufy"));
        expect(screen.getByTestId("mufy-advanced-editor")).toBeInTheDocument();
        expect(
          screen.getByTestId("mufy-value-world_architecture.world_foundation.one_line_pitch"),
        ).toBeDisabled();
        expect(screen.queryByTestId("mufy-block-raw-world_architecture")).not.toBeInTheDocument();
        expect(screen.queryByTestId("mufy-addkey-input-world_architecture")).not.toBeInTheDocument();
      });
    });
  });

  describe("只读卡片查看 (vm.readOnly = true)", () => {
    it("readOnly=true 时禁用全部输入项与保存动作", async () => {
      const actions = createMockActions();
      const readOnlyVm: CharacterCreateViewModel = {
        cardId: "builtin:phainon",
        card: {
          spec: "chara_card_v3",
          spec_version: "3.0",
          data: {
            name: "白厄",
            description: "星核猎手成员",
            tags: ["星核猎手"],
            personality: "冷静果决",
            scenario: "未知星域",
            first_mes: "准备好了吗？",
            mes_example: "",
          },
        },
        readOnly: true,
        loading: false,
        error: null,
      };

      render(<CharacterCreatePage vm={readOnlyVm} actions={actions} />);

      // 等待 cardGet 副作用完成
      await waitFor(() => {
        expect(actions.cardGet).toHaveBeenCalledWith("builtin:phainon");
      });

      expect(screen.getByText("内置角色卡为只读模式，不可修改或保存。")).toBeInTheDocument();
      expect(screen.getByLabelText(/名称/)).toBeDisabled();
      expect(screen.getByLabelText(/简介/)).toBeDisabled();
      expect(screen.getByLabelText(/性格/)).toBeDisabled();
      expect(screen.getByLabelText(/对话场景/)).toBeDisabled();
      expect(screen.getByLabelText(/第一条消息/)).toBeDisabled();
      expect(screen.getByLabelText(/示例对话/)).toBeDisabled();
      expect(screen.getByTestId("btn-draft")).toBeDisabled();
      expect(screen.getByTestId("btn-submit")).toBeDisabled();
      expect(screen.getByLabelText("添加标签")).toBeDisabled();
      expect(screen.getByLabelText("删除标签「星核猎手」")).toBeDisabled();
    });
  });

  describe("加载状态与加载错误呈现 (vm.loading & vm.error)", () => {
    it("vm.loading=true 显示载入中", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={{ ...defaultVm, loading: true }} actions={actions} />);
      expect(screen.getByText("载入角色卡数据中…")).toBeInTheDocument();
    });

    it("vm.error 显示真实错误与重试按钮", async () => {
      const actions = createMockActions();
      render(
        <CharacterCreatePage
          vm={{ ...defaultVm, cardId: "card-999", error: "未找到该角色卡 (404)" }}
          actions={actions}
        />,
      );

      await waitFor(() => {
        expect(actions.cardGet).toHaveBeenCalledWith("card-999");
      });

      expect(screen.getByText("角色卡加载失败：未找到该角色卡 (404)")).toBeInTheDocument();
      const retryBtn = screen.getByRole("button", { name: "重试" });
      fireEvent.click(retryBtn);
      expect(actions.openCharacterCreate).toHaveBeenCalledWith("card-999");
    });

    it("点击返回角色库触发 actions.openCharacterLibrary", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const backButtons = screen.getAllByRole("button", { name: /角色库/ });
      fireEvent.click(backButtons[0]);
      expect(actions.openCharacterLibrary).toHaveBeenCalled();
    });
  });

  describe("高级字段 mes_example", () => {
    it("高级编辑区可编辑示例对话，并在实时预览中显示", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.click(screen.getByTestId("tree-item-mesexample"));

      fireEvent.change(screen.getByTestId("f-mes-example"), {
        target: { value: "<START>\n角色：你好。\n用户：你好呀。" },
      });
      expect(screen.getByTestId("f-mes-example")).toHaveValue(
        "<START>\n角色：你好。\n用户：你好呀。",
      );

      // 返回快速创建，预览区应展示示例对话
      fireEvent.click(screen.getByTestId("btn-return-quick"));
      expect(screen.getByTestId("preview-mes-example")).toHaveTextContent("角色：你好。");
    });
  });

  describe("发布校验 (Publish validation)", () => {
    it("发布缺少名称时后端返回 card_publish_invalid，界面如实呈现", async () => {
      const actions = createMockActions({
        cardPublish: vi.fn().mockRejectedValue(new Error("card_publish_invalid：缺少 name")),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      // 只填首句不填名称，手动保存会触发名称校验，因此直接模拟后端返回缺少 name。
      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "有名称" } });
      fireEvent.change(screen.getByLabelText(/第一条消息/), { target: { value: "首句" } });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-submit"));
      });

      await waitFor(() => {
        expect(screen.getByTestId("publish-error")).toHaveTextContent(
          "card_publish_invalid：缺少 name",
        );
      });
    });
  });

  describe("头像后端错误状态 (Avatar backend errors)", () => {
    it("card_avatar_too_large 错误如实呈现在头像区域", async () => {
      const actions = createMockActions({
        cardSetAvatar: vi.fn().mockRejectedValue(new Error("card_avatar_too_large：文件超过 5MB")),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "大文件测试" } });
      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      const fileInput = screen.getByTestId("avatar-file-input");
      const file = new File(["png"], "avatar.png", { type: "image/png" });

      await act(async () => {
        fireEvent.change(fileInput, { target: { files: [file] } });
      });

      await waitFor(() => {
        expect(screen.getByTestId("avatar-error")).toHaveTextContent("card_avatar_too_large");
      });
    });

    it("有头像时显示替换按钮，移除时调用 cardRemoveAvatar", async () => {
      const actions = createMockActions({
        cardGet: vi.fn().mockResolvedValue({
          card_id: "draft-123",
          state: "draft",
          source: "user_created",
          created_at: "",
          updated_at: "",
          card: {},
          read_only: false,
          avatar: { mime_type: "image/png", data_base64: "iVBORw0KGgo=" },
        }),
      });
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "头像状态" } });
      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-draft"));
      });

      await waitFor(() => {
        expect(screen.getByTestId("btn-remove-avatar")).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByTestId("btn-remove-avatar"));
      });

      await waitFor(() => {
        expect(actions.cardRemoveAvatar).toHaveBeenCalledWith("draft-123");
      });
    });
  });

  describe("未保存退出确认 (Unsaved leave guard)", () => {
    it("有未保存变更时点击返回角色库弹出确认，取消则不离开", () => {
      const actions = createMockActions();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "未保存" } });
      expect(screen.getByTestId("save-status-unsaved")).toBeInTheDocument();

      const backButtons = screen.getAllByRole("button", { name: /角色库/ });
      fireEvent.click(backButtons[0]);

      expect(confirmSpy).toHaveBeenCalledWith("有未保存的更改，确定要离开创作页吗？");
      expect(actions.openCharacterLibrary).not.toHaveBeenCalled();
    });

    it("确认离开后调用 openCharacterLibrary", () => {
      const actions = createMockActions();
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "未保存" } });
      const backButtons = screen.getAllByRole("button", { name: /角色库/ });
      fireEvent.click(backButtons[0]);

      expect(confirmSpy).toHaveBeenCalled();
      expect(actions.openCharacterLibrary).toHaveBeenCalled();
    });
  });
});
