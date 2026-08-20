import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HarnessActions } from "../../../contracts/actions";
import type {
  CharacterCardSummaryView,
  CharacterLibraryViewModel,
} from "../../../contracts/view-models";
import { CharacterLibraryPage } from "../CharacterLibraryPage";

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
    testConnection: vi.fn().mockResolvedValue("连接正常"),
    dismissToast: vi.fn(),
    codexOauthStart: vi.fn().mockResolvedValue(undefined),
    codexOauthStatus: vi.fn().mockResolvedValue({ status: "ready" }),
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

const BUILTIN_CARDS: CharacterCardSummaryView[] = [
  {
    cardId: "builtin:phainon",
    name: "白厄",
    state: "saved",
    source: "builtin",
    updatedAt: "",
    hasAvatar: false,
    voiceState: "voice_ready",
    active: false,
    readOnly: true,
    archived: false,
  },
  {
    cardId: "builtin:firefly",
    name: "流萤",
    state: "saved",
    source: "builtin",
    updatedAt: "",
    hasAvatar: false,
    voiceState: "voice_unconfigured",
    active: false,
    readOnly: true,
    archived: false,
  },
  {
    cardId: "builtin:march7",
    name: "三月七",
    state: "saved",
    source: "builtin",
    updatedAt: "",
    hasAvatar: false,
    voiceState: "voice_unconfigured",
    active: false,
    readOnly: true,
    archived: false,
  },
];

const SAMPLE_CARDS: CharacterCardSummaryView[] = [
  ...BUILTIN_CARDS,
  {
    cardId: "card-draft-001",
    name: "新角色草稿",
    state: "draft",
    source: "user_created",
    updatedAt: "2026-08-19T10:00:00+00:00",
    hasAvatar: false,
    voiceState: "voice_unconfigured",
    active: false,
    readOnly: false,
    archived: false,
  },
  {
    cardId: "card-saved-002",
    name: "卡芙卡",
    state: "saved",
    source: "user_created",
    updatedAt: "2026-08-18T21:40:00+00:00",
    hasAvatar: true,
    voiceState: "voice_ready",
    active: true,
    readOnly: false,
    archived: false,
  },
  {
    cardId: "card-invalid-003",
    name: "blade_broken.json",
    state: "invalid",
    source: "imported_json",
    updatedAt: "2026-08-17T08:00:00+00:00",
    hasAvatar: false,
    voiceState: "voice_unconfigured",
    active: false,
    readOnly: false,
    archived: false,
  },
  {
    cardId: "card-imported-004",
    name: "砂金",
    state: "imported",
    source: "imported_png",
    updatedAt: "2026-08-16T12:00:00+00:00",
    hasAvatar: true,
    voiceState: "voice_failed",
    active: false,
    readOnly: false,
    archived: true,
  },
  {
    cardId: "card-creating-005",
    name: "镜流",
    state: "saved",
    source: "user_created",
    updatedAt: "2026-08-15T16:00:00+00:00",
    hasAvatar: true,
    voiceState: "voice_creating",
    active: false,
    readOnly: false,
    archived: false,
  },
];

describe("CharacterLibraryPage", () => {
  afterEach(() => {
    cleanup();
  });

  describe("双空态渲染与交互", () => {
    it("空态 1：零角色空库渲染正确引导与 CTA，且无筛选控件", () => {
      const vm: CharacterLibraryViewModel = {
        cards: [],
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      // 零角色空态存在
      expect(screen.getByTestId("empty-library-zero")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "角色库还是空的" })).toBeInTheDocument();
      expect(
        screen.getByText("从空白创建第一个角色，或导入酒馆角色卡开始。所有角色都会集中在这里管理。"),
      ).toBeInTheDocument();

      // CTA 按钮
      const createFirstBtn = screen.getByRole("button", { name: /创建第一个角色/ });
      expect(createFirstBtn).toBeInTheDocument();
      fireEvent.click(createFirstBtn);
      expect(actions.openCharacterCreate).toHaveBeenCalledTimes(1);

      const importBtn = screen.getByRole("button", { name: /导入角色卡/ });
      expect(importBtn).toBeInTheDocument();
      fireEvent.click(importBtn);
      // 提示弹窗如实说明将于 V0.3.5 开放
      expect(screen.getByTestId("notice-modal")).toBeInTheDocument();
      expect(screen.getByText("导入酒馆角色卡（JSON / PNG）功能将于 V0.3.5 开放。")).toBeInTheDocument();

      // 无筛选 UI
      expect(screen.queryByLabelText("搜索角色")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("按来源筛选")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("按音色状态筛选")).not.toBeInTheDocument();
    });

    it("空态 2：筛选无结果态保留筛选栏，提供清空筛选与创建角色", () => {
      const vm: CharacterLibraryViewModel = {
        cards: SAMPLE_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      // 搜索不存在的角色名
      const searchInput = screen.getByLabelText("搜索角色");
      fireEvent.change(searchInput, { target: { value: "不存在的神秘角色" } });

      // 筛选无结果空态
      expect(screen.getByTestId("empty-library-filtered")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "还没有符合筛选的角色" })).toBeInTheDocument();

      // 筛选控件仍然存在
      expect(searchInput).toBeInTheDocument();

      // 清空筛选操作
      const clearBtn = screen.getByRole("button", { name: "清空筛选" });
      fireEvent.click(clearBtn);

      // 清空后恢复卡片展示
      expect(screen.queryByTestId("empty-library-filtered")).not.toBeInTheDocument();
      expect(screen.getByText("白厄")).toBeInTheDocument();
    });
  });

  describe("内置角色卡渲染与只读约束", () => {
    it("内置三卡渲染正确信息与只读查看按钮", () => {
      const vm: CharacterLibraryViewModel = {
        cards: BUILTIN_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      expect(screen.getByText("白厄")).toBeInTheDocument();
      expect(screen.getByText("流萤")).toBeInTheDocument();
      expect(screen.getByText("三月七")).toBeInTheDocument();

      // 来源标注内置 · 只读
      expect(screen.getAllByText("内置 · 只读")).toHaveLength(3);

      // 内置卡只提供查看操作，不提供删除/归档/复制
      const viewButtons = screen.getAllByRole("button", { name: /^查看/ });
      expect(viewButtons).toHaveLength(3);

      fireEvent.click(viewButtons[0]);
      expect(actions.openCharacterCreate).toHaveBeenCalledWith("builtin:phainon");

      expect(screen.queryByRole("button", { name: "删除白厄" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "归档白厄" })).not.toBeInTheDocument();
    });
  });

  describe("来源与音色筛选", () => {
    it("按来源筛选内置、创建、导入、草稿、已归档", () => {
      const vm: CharacterLibraryViewModel = {
        cards: SAMPLE_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      const sourceSelect = screen.getByLabelText("按来源筛选");

      // 1. 默认状态（未归档的卡片，不含已归档的砂金）
      expect(screen.getByText("白厄")).toBeInTheDocument();
      expect(screen.getByTestId("char-card-card-saved-002")).toBeInTheDocument();
      expect(screen.queryByTestId("char-card-card-imported-004")).not.toBeInTheDocument();

      // 2. 筛选内置
      fireEvent.change(sourceSelect, { target: { value: "builtin" } });
      expect(screen.getByText("白厄")).toBeInTheDocument();
      expect(screen.getByText("流萤")).toBeInTheDocument();
      expect(screen.queryByTestId("char-card-card-saved-002")).not.toBeInTheDocument();
      expect(screen.queryByTestId("char-card-card-draft-001")).not.toBeInTheDocument();

      // 3. 筛选创建
      fireEvent.change(sourceSelect, { target: { value: "user_created" } });
      expect(screen.getByTestId("char-card-card-saved-002")).toBeInTheDocument();
      expect(screen.getByTestId("char-card-card-draft-001")).toBeInTheDocument();
      expect(screen.queryByTestId("char-card-builtin:phainon")).not.toBeInTheDocument();

      // 4. 筛选草稿
      fireEvent.change(sourceSelect, { target: { value: "draft" } });
      expect(screen.getByTestId("char-card-card-draft-001")).toBeInTheDocument();
      expect(screen.queryByTestId("char-card-card-saved-002")).not.toBeInTheDocument();

      // 5. 筛选已归档
      fireEvent.change(sourceSelect, { target: { value: "archived" } });
      expect(screen.getByTestId("char-card-card-imported-004")).toBeInTheDocument();
      expect(screen.queryByTestId("char-card-card-saved-002")).not.toBeInTheDocument();
      expect(screen.queryByTestId("char-card-builtin:phainon")).not.toBeInTheDocument();
    });

    it("按音色状态筛选已绑定、未配置、创建中、失败", () => {
      const vm: CharacterLibraryViewModel = {
        cards: SAMPLE_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      const voiceSelect = screen.getByLabelText("按音色状态筛选");

      // 1. 已绑定
      fireEvent.change(voiceSelect, { target: { value: "voice_ready" } });
      expect(screen.getByTestId("char-card-card-saved-002")).toBeInTheDocument();
      expect(screen.getByTestId("char-card-builtin:phainon")).toBeInTheDocument();
      expect(screen.queryByTestId("char-card-card-creating-005")).not.toBeInTheDocument();

      // 2. 创建中
      fireEvent.change(voiceSelect, { target: { value: "voice_creating" } });
      expect(screen.getByTestId("char-card-card-creating-005")).toBeInTheDocument();
      expect(screen.queryByTestId("char-card-card-saved-002")).not.toBeInTheDocument();
    });
  });

  describe("删除二次确认行为", () => {
    it("删除非只读角色卡必须弹出确认框，确认后才调用 deleteCard action", async () => {
      const vm: CharacterLibraryViewModel = {
        cards: SAMPLE_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      const deleteKafkaBtn = screen.getByRole("button", { name: "删除卡芙卡" });
      fireEvent.click(deleteKafkaBtn);

      // 弹窗可见
      expect(screen.getByTestId("delete-modal")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "删除「卡芙卡」？" })).toBeInTheDocument();
      expect(
        screen.getByText("角色的全部字段、世界书条目与头像将被移除，且无法恢复。已绑定的音色会一并解除绑定。"),
      ).toBeInTheDocument();

      // 点击取消
      const cancelBtn = screen.getByRole("button", { name: "取消" });
      fireEvent.click(cancelBtn);

      // 弹窗关闭且 action 未调用
      expect(screen.queryByTestId("delete-modal")).not.toBeInTheDocument();
      expect(actions.deleteCard).not.toHaveBeenCalled();

      // 再次点击删除并确认
      fireEvent.click(deleteKafkaBtn);
      const confirmDeleteBtn = screen.getByRole("button", { name: "确认删除" });
      fireEvent.click(confirmDeleteBtn);

      await waitFor(() => {
        expect(actions.deleteCard).toHaveBeenCalledWith("card-saved-002");
      });
      expect(screen.queryByTestId("delete-modal")).not.toBeInTheDocument();
    });
  });

  describe("真实加载失败态与重试", () => {
    it("展示 vm.error 真实文本并可通过重试按钮调用 listCards", () => {
      const vm: CharacterLibraryViewModel = {
        cards: [],
        loading: false,
        error: "Sidecar: 数据库查询超时 (timeout 3000ms)",
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      const errorBanner = screen.getByTestId("library-error-banner");
      expect(errorBanner).toBeInTheDocument();
      expect(errorBanner).toHaveTextContent("Sidecar: 数据库查询超时 (timeout 3000ms)");

      const retryBtn = screen.getByRole("button", { name: "重试" });
      fireEvent.click(retryBtn);

      expect(actions.listCards).toHaveBeenCalledTimes(1);
    });
  });

  describe("Invalid 导入失败卡片条目态", () => {
    it("正确渲染导入失败卡片的信息、错误提示与移除入口", () => {
      const vm: CharacterLibraryViewModel = {
        cards: SAMPLE_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      expect(screen.getByText("blade_broken.json")).toBeInTheDocument();
      expect(screen.getByText("导入失败")).toBeInTheDocument();
      expect(screen.getByText("导入失败 · 未创建角色")).toBeInTheDocument();
      expect(
        screen.getByText("解析中断：文件格式或元数据损坏。可移除后重新导入。"),
      ).toBeInTheDocument();

      // 查看错误详情
      const viewErrorBtn = screen.getByRole("button", { name: "查看导入错误" });
      fireEvent.click(viewErrorBtn);
      expect(screen.getByTestId("notice-modal")).toBeInTheDocument();
      expect(screen.getByText(/导入失败详情/)).toBeInTheDocument();

      // 关闭错误详情
      fireEvent.click(screen.getByRole("button", { name: "知道了" }));

      // 移除失败条目
      const deleteBrokenBtn = screen.getByRole("button", { name: "删除blade_broken.json" });
      fireEvent.click(deleteBrokenBtn);
      expect(screen.getByTestId("delete-modal")).toBeInTheDocument();
    });
  });

  describe("其他卡片操作交互", () => {
    it("卡片操作：复制、归档/恢复、使用、编辑与返回聊天", () => {
      const vm: CharacterLibraryViewModel = {
        cards: SAMPLE_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      // 1. 复制
      const duplicateBtn = screen.getByRole("button", { name: "复制卡芙卡" });
      fireEvent.click(duplicateBtn);
      expect(actions.duplicateCard).toHaveBeenCalledWith("card-saved-002");

      // 2. 归档
      const archiveBtn = screen.getByRole("button", { name: "归档卡芙卡" });
      fireEvent.click(archiveBtn);
      expect(actions.archiveCard).toHaveBeenCalledWith("card-saved-002");

      // 3. 编辑
      const editBtn = screen.getByRole("button", { name: "编辑卡芙卡" });
      fireEvent.click(editBtn);
      expect(actions.openCharacterCreate).toHaveBeenCalledWith("card-saved-002");

      // 4. 返回聊天
      const backChatBtn = screen.getByRole("button", { name: "返回聊天" });
      fireEvent.click(backChatBtn);
      expect(actions.openChat).toHaveBeenCalledTimes(1);

      // 5. 导出占位如实说明
      const exportBtn = screen.getByRole("button", { name: "导出卡芙卡" });
      fireEvent.click(exportBtn);
      expect(screen.getByTestId("notice-modal")).toBeInTheDocument();
      expect(screen.getByText("角色卡导出（酒馆 v3 JSON / PNG）功能将于 V0.3.5 开放。")).toBeInTheDocument();
    });

    it("使用中置顶条渲染与点击编辑", () => {
      const vm: CharacterLibraryViewModel = {
        cards: SAMPLE_CARDS,
        loading: false,
        error: null,
        loaded: true,
      };
      const actions = createMockActions();

      render(<CharacterLibraryPage vm={vm} actions={actions} />);

      const inUseStrip = screen.getByTestId("in-use-strip");
      expect(inUseStrip).toBeInTheDocument();
      expect(within(inUseStrip).getByText("卡芙卡")).toBeInTheDocument();
      expect(within(inUseStrip).getByText("使用中")).toBeInTheDocument();
      expect(within(inUseStrip).getByText("音色已绑定")).toBeInTheDocument();

      const continueEditBtn = inUseStrip.querySelector("button")!;
      fireEvent.click(continueEditBtn);
      expect(actions.openCharacterCreate).toHaveBeenCalledWith("card-saved-002");
    });
  });
});
