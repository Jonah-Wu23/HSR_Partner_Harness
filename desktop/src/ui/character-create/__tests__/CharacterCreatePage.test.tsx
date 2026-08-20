import { cleanup, fireEvent, render, screen, within, act } from "@testing-library/react";
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
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
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

  describe("头像入口占位提示 (Avatar entry)", () => {
    it("点击设置头像如实提示 V0.3.5 开放", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const avatarBtn = screen.getByRole("button", { name: "设置头像" });
      fireEvent.click(avatarBtn);

      expect(
        screen.getByText(/头像资产管理（选择\/裁切\/写盘）将于 V0.3.5 开放/),
      ).toBeInTheDocument();
    });

    it("头像预览首字符随名称实时更新", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      expect(screen.getByTestId("avatar-preview")).toHaveTextContent("?");

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "流萤" } });

      expect(screen.getByTestId("avatar-preview")).toHaveTextContent("流");
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

  describe("快速创建与高级编辑模式切换 (Progressive disclosure)", () => {
    it("切换到高级编辑显示分区框架与 V0.3.5/V0.3.7 真实交付说明，草稿数据双向保留", () => {
      const actions = createMockActions();
      render(<CharacterCreatePage vm={defaultVm} actions={actions} />);

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "镜流" } });
      const tagInput = screen.getByLabelText("添加标签");
      fireEvent.change(tagInput, { target: { value: "剑首" } });
      fireEvent.keyDown(tagInput, { key: "Enter" });

      // 切换到高级编辑
      const advBtn = screen.getByTestId("mode-btn-advanced");
      fireEvent.click(advBtn);

      expect(screen.getByTestId("advanced-panel")).toBeInTheDocument();
      expect(
        screen.getByText(/完整字段编辑随 V0.3.5 交付/),
      ).toBeInTheDocument();
      expect(screen.getByText(/角色名称：镜流/)).toBeInTheDocument();
      expect(screen.getByText(/已添加标签数：1 个/)).toBeInTheDocument();

      // 点击返回快速创建
      const returnBtn = screen.getByTestId("btn-return-quick");
      fireEvent.click(returnBtn);

      expect(screen.getByLabelText(/名称/)).toHaveValue("镜流");
      const tagList = screen.getByTestId("tag-list");
      expect(within(tagList).getByText("剑首")).toBeInTheDocument();
    });
  });

  describe("只读卡片查看 (vm.readOnly = true)", () => {
    it("readOnly=true 时禁用全部输入项与保存动作", () => {
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

    it("vm.error 显示真实错误与重试按钮", () => {
      const actions = createMockActions();
      render(
        <CharacterCreatePage
          vm={{ ...defaultVm, cardId: "card-999", error: "未找到该角色卡 (404)" }}
          actions={actions}
        />,
      );

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
});
