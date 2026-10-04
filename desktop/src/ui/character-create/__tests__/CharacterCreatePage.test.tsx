import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HarnessActions } from "../../../contracts/actions";
import type { CardGetResult, DesktopCommand } from "../../../contracts/protocol";
import { createActionController } from "../../../services/actions";
import { DesktopRequestError, type DesktopBackend } from "../../../services/backend";
import { MockDesktopBackend, type MockDesktopBackendOptions } from "../../../services/mockDesktopBackend";
import { desktopStore, useDesktopStore } from "../../../stores/desktopStore";
import { fakeBackend, type FakeBackendOptions, unexpectedCommand } from "../../../test/fakeBackend";
import { CharacterCreatePage } from "../CharacterCreatePage";

/** mock 后端已有 4 张用户卡，新建草稿编号为 card-mock-5。 */
const NEW_DRAFT_ID = "card-mock-5";

/** 与 AppShell 一致：创作页视图模型取自 store，头像经后端文件对话框选择。 */
function CreateHost({ actions, backend }: { actions: HarnessActions; backend: DesktopBackend }) {
  const vm = useDesktopStore((state) => state.characterCreate);
  return <CharacterCreatePage vm={vm} actions={actions} onPickFile={(options) => backend.pickFile(options)} />;
}

/** 经 openCharacterCreate 打开创作页（传 cardId 时读取该卡）后渲染。 */
async function renderCreatePage(backend: DesktopBackend, cardId?: string): Promise<void> {
  const { actions } = createActionController(backend);
  await actions.openCharacterCreate(cardId);
  render(<CreateHost actions={actions} backend={backend} />);
}

function paramsOf(commands: readonly DesktopCommand[], method: string): Record<string, unknown>[] {
  return commands.filter((command) => command.method === method).map((command) => command.params);
}

async function click(element: HTMLElement): Promise<void> {
  await act(async () => {
    fireEvent.click(element);
  });
}

/** 推进假时钟并在 act 内等待由此触发的保存请求完成。 */
async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** method 命令回放为错误帧，其余命令交给 MockDesktopBackend。 */
function mockWithErrorFrame(
  method: string,
  error: DesktopRequestError,
  options: MockDesktopBackendOptions & FakeBackendOptions = {},
) {
  const mock = new MockDesktopBackend("single-project", options);
  return fakeBackend((command) => {
    if (command.method === method) throw error;
    return mock.request(command);
  }, options);
}

const EMPTY_REPORT: CardGetResult["compat_report"] = {
  applied: [],
  preserved: [],
  not_executed: [],
  normalized_from_root: [],
  warnings: [],
  errors: [],
};

/** 带世界书条目与 extensions.hsr（含未识别键）的已存卡。 */
const WIRED_CARD: Record<string, unknown> = {
  spec: "chara_card_v3",
  spec_version: "3.0",
  data: {
    name: "临海角色",
    description: "",
    tags: ["港口"],
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
};

function cardGetResult(overrides: Partial<CardGetResult> = {}): CardGetResult {
  return {
    card_id: "card-001",
    state: "saved",
    source: "user_created",
    created_at: "2026-08-18T21:40:00+00:00",
    updated_at: "2026-08-18T21:40:00+00:00",
    card: WIRED_CARD,
    read_only: false,
    avatar: null,
    compat_report: EMPTY_REPORT,
    ...overrides,
  };
}

/** 回放已存卡：card.get 返回 result，card.update 按协议回执。 */
function storedCardBackend(result: CardGetResult = cardGetResult()) {
  return fakeBackend((command) => {
    switch (command.method) {
      case "card.get":
        return result;
      case "card.update":
        return { card_id: command.params.card_id, updated_at: "2026-10-01T08:00:00+00:00" };
      default:
        return unexpectedCommand(command);
    }
  });
}

/** 回放新卡从建草稿到发布：card.publish 由 publish 决定成败，发布后 card.get 返回 saved。 */
function draftPublishBackend(publish: () => unknown) {
  let state: "draft" | "saved" = "draft";
  return fakeBackend((command) => {
    switch (command.method) {
      case "card.create_draft":
        return { card_id: "card-new-1", state: "draft" };
      case "card.update":
        return { card_id: "card-new-1", updated_at: "2026-10-01T08:00:00+00:00" };
      case "card.get":
        return cardGetResult({ card_id: "card-new-1", state, card: { spec: "chara_card_v3", data: {} } });
      case "card.publish": {
        const result = publish();
        state = "saved";
        return result;
      }
      case "card.list":
        return { cards: [] };
      default:
        return unexpectedCommand(command);
    }
  });
}

describe("CharacterCreatePage", () => {
  let originalCreateObjectURL: typeof URL.createObjectURL | undefined;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL | undefined;

  // jsdom 没有实现 URL.createObjectURL：头像 data URI 转 object URL 需要这个平台桩。
  beforeEach(() => {
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:avatar-preview") as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    if (originalCreateObjectURL) URL.createObjectURL = originalCreateObjectURL;
    if (originalRevokeObjectURL) URL.revokeObjectURL = originalRevokeObjectURL;
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  describe("名称必填", () => {
    it("空名称点击完成创建时不发请求，名称字段标红并提示", async () => {
      const backend = new MockDesktopBackend();
      await renderCreatePage(backend);

      fireEvent.click(screen.getByTestId("btn-submit"));

      expect(screen.getByText("名称为必填项，填写后才能完成创建")).toBeInTheDocument();
      expect(screen.getByLabelText(/名称/)).toHaveAttribute("aria-invalid", "true");
      expect(backend.recordedRequests).toEqual([]);
    });

    it("输入名称后错误信息自动清除", async () => {
      await renderCreatePage(new MockDesktopBackend());

      fireEvent.click(screen.getByTestId("btn-submit"));
      expect(screen.getByText("名称为必填项，填写后才能完成创建")).toBeInTheDocument();

      const nameInput = screen.getByLabelText(/名称/);
      fireEvent.change(nameInput, { target: { value: "卡芙卡" } });

      expect(screen.queryByText("名称为必填项，填写后才能完成创建")).not.toBeInTheDocument();
      expect(nameInput).toHaveAttribute("aria-invalid", "false");
    });
  });

  describe("标签", () => {
    it("输入标签按回车添加，并在表单与预览区同步展示", async () => {
      await renderCreatePage(new MockDesktopBackend());

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

    it("点击删除按钮移除标签", async () => {
      await renderCreatePage(new MockDesktopBackend());

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

    it("空标签或重复标签不重复添加", async () => {
      await renderCreatePage(new MockDesktopBackend());

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

  describe("字数统计", () => {
    it.each([
      [/性格/, "count-personality", "温和冷静，运筹帷幄", "9 / 2000 字"],
      [/对话场景/, "count-scenario", "空间站黑塔", "5 / 2000 字"],
      [/第一条消息/, "count-first-msg", "好久不见。", "5 / 2000 字"],
      [/示例对话/, "count-example", "<START>", "7 / 2000 字"],
    ])("%s 实时显示字数并限制 2000 字", async (label, countTestId, value, countText) => {
      await renderCreatePage(new MockDesktopBackend());

      const input = screen.getByLabelText(label);
      fireEvent.change(input, { target: { value } });

      expect(screen.getByTestId(countTestId)).toHaveTextContent(countText);
      expect(input).toHaveAttribute("maxLength", "2000");
    });
  });

  describe("头像", () => {
    it("未设置头像时使用名称首字符占位", async () => {
      await renderCreatePage(new MockDesktopBackend());

      expect(screen.getByTestId("avatar-preview")).toHaveTextContent("?");

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "流萤" } });

      expect(screen.getByTestId("avatar-preview")).toHaveTextContent("流");
    });

    it("保存前选的头像在建草稿后经 card.set_avatar 上传，移除后回到首字占位", async () => {
      const backend = new MockDesktopBackend("single-project", { pickFileResult: "C:/avatars/avatar.png" });
      await renderCreatePage(backend);
      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "头像测试" } });

      await click(screen.getByTestId("btn-set-avatar"));
      expect(screen.getByText("已选择头像，保存后上传")).toBeInTheDocument();
      expect(paramsOf(backend.recordedRequests, "card.set_avatar")).toEqual([]);

      fireEvent.click(screen.getByTestId("btn-draft"));

      expect(await screen.findByTestId("btn-remove-avatar")).toBeInTheDocument();
      expect(screen.getByTestId("btn-set-avatar")).toHaveTextContent("替换头像");
      expect(paramsOf(backend.recordedRequests, "card.set_avatar")).toEqual([
        { card_id: NEW_DRAFT_ID, path: "C:/avatars/avatar.png" },
      ]);

      fireEvent.click(screen.getByTestId("btn-remove-avatar"));

      await waitFor(() => expect(screen.getByTestId("avatar-preview")).toHaveTextContent("头"));
      expect(screen.queryByTestId("btn-remove-avatar")).not.toBeInTheDocument();
      expect(paramsOf(backend.recordedRequests, "card.remove_avatar")).toEqual([{ card_id: NEW_DRAFT_ID }]);
    });

    it("后端拒绝头像时在头像区显示原文", async () => {
      const { backend } = mockWithErrorFrame(
        "card.set_avatar",
        new DesktopRequestError("card_avatar_unsupported", "头像仅支持 PNG / JPEG / WebP 图片"),
        { pickFileResult: "C:/avatars/avatar.gif" },
      );
      await renderCreatePage(backend);
      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "格式测试" } });
      fireEvent.click(screen.getByTestId("btn-draft"));
      await screen.findByTestId("save-status-saved");

      fireEvent.click(screen.getByTestId("btn-set-avatar"));

      expect(await screen.findByTestId("avatar-error")).toHaveTextContent("头像仅支持 PNG / JPEG / WebP 图片");
    });
  });

  describe("保存", () => {
    // 防抖计时由测试推进。RTL 的 findBy/waitFor 依赖真实 setTimeout，这一组改用 act 等待保存链完成。
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("编辑后标为未保存，停止输入 1 秒后自动建草稿并整卡保存", async () => {
      const backend = new MockDesktopBackend();
      await renderCreatePage(backend);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "银狼" } });
      expect(screen.getByTestId("save-status-unsaved")).toHaveTextContent("未保存更改");

      await advance(999);
      expect(backend.recordedRequests).toEqual([]);

      await advance(1);

      expect(screen.getByTestId("save-status-saved")).toHaveTextContent(/已保存 \d{2}:\d{2}:\d{2}/);
      expect(paramsOf(backend.recordedRequests, "card.create_draft")).toEqual([{ name: "银狼" }]);
      expect(paramsOf(backend.recordedRequests, "card.update")).toEqual([
        { card_id: NEW_DRAFT_ID, card: expect.objectContaining({ data: expect.objectContaining({ name: "银狼" }) }) },
      ]);
    });

    it("首次保存建草稿，之后的保存只整卡更新同一张卡", async () => {
      const backend = new MockDesktopBackend();
      await renderCreatePage(backend);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "砂金" } });
      await click(screen.getByTestId("btn-draft"));
      expect(screen.getByTestId("save-status-saved")).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText(/简介/), { target: { value: "战略投资部高级干部" } });
      await click(screen.getByTestId("btn-draft"));
      expect(screen.getByTestId("save-status-saved")).toBeInTheDocument();

      expect(paramsOf(backend.recordedRequests, "card.create_draft")).toEqual([{ name: "砂金" }]);
      expect(paramsOf(backend.recordedRequests, "card.update")).toHaveLength(2);
      expect(paramsOf(backend.recordedRequests, "card.update")[1]).toEqual({
        card_id: NEW_DRAFT_ID,
        card: expect.objectContaining({
          data: expect.objectContaining({ name: "砂金", description: "战略投资部高级干部" }),
        }),
      });
    });

    it("保存失败时显示原始错误，表单与预览内容保留", async () => {
      const { backend } = mockWithErrorFrame(
        "card.create_draft",
        new DesktopRequestError("internal_error", "database or disk is full"),
      );
      await renderCreatePage(backend);

      const nameInput = screen.getByLabelText(/名称/);
      const descInput = screen.getByLabelText(/简介/);
      fireEvent.change(nameInput, { target: { value: "测试角色" } });
      fireEvent.change(descInput, { target: { value: "重要草稿不可丢" } });
      await click(screen.getByTestId("btn-draft"));

      expect(screen.getByTestId("save-error-banner")).toHaveTextContent(
        "保存失败：database or disk is full",
      );
      expect(screen.getByTestId("save-status-error")).toBeInTheDocument();
      expect(nameInput).toHaveValue("测试角色");
      expect(descInput).toHaveValue("重要草稿不可丢");
      expect(screen.getByTestId("preview-name")).toHaveTextContent("测试角色");
      expect(screen.getByTestId("preview-summary")).toHaveTextContent("重要草稿不可丢");
    });
  });

  describe("发布与开始对话", () => {
    it("完成创建先保存再发布，发布后按钮变为开始对话", async () => {
      const { backend, commands } = draftPublishBackend(() => ({ card_id: "card-new-1", state: "saved" }));
      await renderCreatePage(backend);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "发布角色" } });
      fireEvent.change(screen.getByLabelText(/第一条消息/), { target: { value: "你好。" } });
      fireEvent.click(screen.getByTestId("btn-submit"));

      expect(await screen.findAllByTestId("btn-start-chat")).toHaveLength(2);
      expect(paramsOf(commands, "card.create_draft")).toEqual([{ name: "发布角色" }]);
      expect(paramsOf(commands, "card.update")).toEqual([
        {
          card_id: "card-new-1",
          card: expect.objectContaining({
            data: expect.objectContaining({ name: "发布角色", first_mes: "你好。" }),
          }),
        },
      ]);
      expect(paramsOf(commands, "card.publish")).toEqual([{ card_id: "card-new-1" }]);
    });

    it("发布被后端拒绝时显示缺少的字段，按钮保持完成创建", async () => {
      const { backend } = draftPublishBackend(() => {
        throw new DesktopRequestError("card_publish_invalid", "完成创建前必填：第一条消息");
      });
      await renderCreatePage(backend);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "缺首句" } });
      fireEvent.click(screen.getByTestId("btn-submit"));

      expect(await screen.findByTestId("publish-error")).toHaveTextContent("完成创建前必填：第一条消息");
      expect(screen.getByTestId("btn-submit")).toHaveTextContent("完成创建");
      expect(screen.queryByTestId("btn-start-chat")).not.toBeInTheDocument();
    });

    it("已发布的卡点击开始对话：按该卡的绑定项建会话、设为当前角色并回到聊天视图", async () => {
      const backend = new MockDesktopBackend();
      desktopStore.setState({ currentProjectId: "project-1" });
      await renderCreatePage(backend, "card-saved-002");

      const [startChat] = await screen.findAllByTestId("btn-start-chat");
      fireEvent.click(startChat);

      await waitFor(() => expect(desktopStore.getState().mainView).toBe("chat"));
      // 创作页没有目录上下文，先按权威目录补取 pair.list；随后用绑定 id 建会话（reuse_active 复用），
      // 建会话成功后再经 card.select_active 更新角色库「使用中」标记。
      expect(
        backend.recordedRequests
          .filter((command) => command.method !== "card.get")
          .map((command) => [command.method, command.params]),
      ).toEqual([
        ["pair.list", {}],
        [
          "conversation.create",
          { project_id: "project-1", binding_id: "card-bind-card-saved-002", reuse_active: true },
        ],
        ["card.select_active", { card_id: "card-saved-002" }],
        ["card.list", { include_archived: true }],
      ]);
    });
  });

  describe("高级编辑", () => {
    it("切换到高级编辑可编辑系统提示、历史后指令、备选问候、群组问候", async () => {
      await renderCreatePage(new MockDesktopBackend());

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

    it("高级字段编辑后返回快速创建保留数据", async () => {
      await renderCreatePage(new MockDesktopBackend());

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.change(screen.getByTestId("f-system-prompt"), { target: { value: "系统提示保留" } });
      fireEvent.click(screen.getByTestId("btn-return-quick"));

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      expect(screen.getByTestId("f-system-prompt")).toHaveValue("系统提示保留");
    });

    it("高级编辑区可编辑示例对话，并在实时预览中显示", async () => {
      await renderCreatePage(new MockDesktopBackend());

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.click(screen.getByTestId("tree-item-mesexample"));
      fireEvent.change(screen.getByTestId("f-mes-example"), {
        target: { value: "<START>\n角色：你好。\n用户：你好呀。" },
      });
      fireEvent.click(screen.getByTestId("btn-return-quick"));

      expect(screen.getByTestId("preview-mes-example")).toHaveTextContent("角色：你好。");
    });

    it("原始数据分区以只读视图展示整卡 JSON", async () => {
      const { backend } = storedCardBackend();
      await renderCreatePage(backend, "card-001");

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.click(screen.getByTestId("tree-item-raw"));

      const rawView = screen.getByTestId("raw-json-view");
      expect(rawView).toHaveTextContent("character_book");
      expect(rawView).toHaveTextContent("one_line_pitch");
      expect(within(rawView).queryByRole("textbox")).not.toBeInTheDocument();
    });
  });

  describe("世界书与 mufy 高级设定随整卡保存", () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    async function flushAutoSave(): Promise<void> {
      await advance(1000);
      expect(screen.getByTestId("save-status-saved")).toBeInTheDocument();
    }

    it("世界书条目编辑合并回整卡，防抖后经 card.update 提交", async () => {
      const { backend, commands } = storedCardBackend();
      await renderCreatePage(backend, "card-001");

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.click(screen.getByTestId("tree-item-worldbook"));
      expect(screen.getByTestId("wb-entry-row-0")).toHaveTextContent("世界观总纲");

      fireEvent.click(screen.getByTestId("wb-entry-toggle-0"));
      fireEvent.change(screen.getByTestId("wb-entry-0-content"), { target: { value: "临海永远下雨。" } });
      expect(screen.getByTestId("save-status-unsaved")).toBeInTheDocument();
      expect(paramsOf(commands, "card.update")).toEqual([]);

      await flushAutoSave();

      expect(paramsOf(commands, "card.update")).toEqual([
        {
          card_id: "card-001",
          card: expect.objectContaining({
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
        },
      ]);
    });

    it("mufy 编辑合并回 extensions.hsr，未识别键原样保留", async () => {
      const { backend, commands } = storedCardBackend();
      await renderCreatePage(backend, "card-001");

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.click(screen.getByTestId("tree-item-mufy"));
      fireEvent.change(screen.getByTestId("mufy-value-world_architecture.world_foundation.one_line_pitch"), {
        target: { value: "永不晴天。" },
      });

      await flushAutoSave();

      expect(paramsOf(commands, "card.update")).toEqual([
        {
          card_id: "card-001",
          card: expect.objectContaining({
            data: expect.objectContaining({
              extensions: {
                hsr: {
                  world_architecture: { world_foundation: { one_line_pitch: "永不晴天。" } },
                  legacy_note: "旧版字段",
                },
              },
            }),
          }),
        },
      ]);
    });

    it("新建卡在 mufy 分区添加内容后，自动保存建草稿并提交带 extensions.hsr 的整卡", async () => {
      const backend = new MockDesktopBackend();
      await renderCreatePage(backend);

      fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "新角色" } });
      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.click(screen.getByTestId("tree-item-mufy"));
      fireEvent.click(screen.getByTestId("mufy-add-world_architecture.world_foundation"));

      await flushAutoSave();

      expect(paramsOf(backend.recordedRequests, "card.create_draft")).toEqual([{ name: "新角色" }]);
      expect(paramsOf(backend.recordedRequests, "card.update")).toEqual([
        {
          card_id: NEW_DRAFT_ID,
          card: expect.objectContaining({
            data: expect.objectContaining({
              extensions: { hsr: { world_architecture: { world_foundation: {} } } },
            }),
          }),
        },
      ]);
    });
  });

  describe("内置只读卡", () => {
    it("表单、世界书与 mufy 编辑器都不可编辑，不提供保存与发布", async () => {
      const { backend } = storedCardBackend(
        cardGetResult({ card_id: "builtin:phainon", source: "builtin", read_only: true }),
      );
      await renderCreatePage(backend, "builtin:phainon");

      expect(await screen.findByTestId("btn-start-chat")).toBeInTheDocument();
      expect(screen.getByText("内置角色卡为只读模式，不可修改或保存。")).toBeInTheDocument();
      for (const label of [/名称/, /简介/, /性格/, /对话场景/, /第一条消息/, /示例对话/]) {
        expect(screen.getByLabelText(label)).toBeDisabled();
      }
      expect(screen.getByLabelText("添加标签")).toBeDisabled();
      expect(screen.getByLabelText("删除标签「港口」")).toBeDisabled();
      expect(screen.getByTestId("btn-draft")).toBeDisabled();
      expect(screen.getByTestId("btn-set-avatar")).toBeDisabled();
      expect(screen.queryByTestId("btn-submit")).not.toBeInTheDocument();
      expect(screen.queryByTestId("btn-publish")).not.toBeInTheDocument();

      fireEvent.click(screen.getByTestId("mode-btn-advanced"));
      fireEvent.click(screen.getByTestId("tree-item-worldbook"));
      expect(screen.getByTestId("wb-entry-row-0")).toBeInTheDocument();
      expect(screen.queryByTestId("wb-add-entry")).not.toBeInTheDocument();
      expect(screen.queryByTestId("wb-entry-remove-0")).not.toBeInTheDocument();

      fireEvent.click(screen.getByTestId("tree-item-mufy"));
      expect(screen.getByTestId("mufy-value-world_architecture.world_foundation.one_line_pitch")).toBeDisabled();
      expect(screen.queryByTestId("mufy-block-raw-world_architecture")).not.toBeInTheDocument();
      expect(screen.queryByTestId("mufy-addkey-input-world_architecture")).not.toBeInTheDocument();
    });
  });

  describe("读取卡片", () => {
    it("读取期间显示载入提示，读取完成后用卡内容填充表单", async () => {
      let release: () => void = () => {};
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      const { backend } = fakeBackend(async (command) => {
        if (command.method !== "card.get") return unexpectedCommand(command);
        await gate;
        return cardGetResult();
      });
      const { actions } = createActionController(backend);
      const opening = actions.openCharacterCreate("card-001");
      render(<CreateHost actions={actions} backend={backend} />);

      expect(screen.getByText("载入角色卡数据中…")).toBeInTheDocument();

      await act(async () => {
        release();
        await opening;
      });

      expect(screen.queryByText("载入角色卡数据中…")).not.toBeInTheDocument();
      expect(screen.getByLabelText(/名称/)).toHaveValue("临海角色");
    });

    it("卡不存在时显示读取错误原文", async () => {
      await renderCreatePage(new MockDesktopBackend(), "card-999");

      expect(screen.getByText("角色卡加载失败：角色卡不存在")).toBeInTheDocument();
    });

    it("读取失败后点重试重新读取原来的卡，成功后用卡内容填充表单", async () => {
      let attempts = 0;
      const { backend, commands } = fakeBackend((command) => {
        if (command.method !== "card.get") return unexpectedCommand(command);
        attempts += 1;
        if (attempts === 1) throw new DesktopRequestError("internal_error", "database is locked");
        return cardGetResult();
      });
      await renderCreatePage(backend, "card-001");
      expect(screen.getByText("角色卡加载失败：database is locked")).toBeInTheDocument();

      await click(screen.getByRole("button", { name: "重试" }));

      await waitFor(() => expect(screen.getByLabelText(/名称/)).toHaveValue("临海角色"));
      expect(screen.queryByText(/角色卡加载失败/)).not.toBeInTheDocument();
      expect(paramsOf(commands, "card.get").slice(0, 2)).toEqual([
        { card_id: "card-001" },
        { card_id: "card-001" },
      ]);
    });

    it("页内读取卡状态失败时显示错误原文，重新读取成功后提示消失", async () => {
      let attempts = 0;
      const { backend, commands } = fakeBackend((command) => {
        if (command.method !== "card.get") return unexpectedCommand(command);
        attempts += 1;
        if (attempts === 2) throw new DesktopRequestError("internal_error", "database is locked");
        return cardGetResult();
      });
      await renderCreatePage(backend, "card-001");

      expect(await screen.findByTestId("card-details-error-banner")).toHaveTextContent(
        "读取角色卡状态失败：database is locked",
      );

      fireEvent.click(screen.getByRole("button", { name: "重新读取" }));

      await waitFor(() => expect(screen.queryByTestId("card-details-error-banner")).not.toBeInTheDocument());
      expect(paramsOf(commands, "card.get")).toEqual([
        { card_id: "card-001" },
        { card_id: "card-001" },
        { card_id: "card-001" },
      ]);
    });
  });

  describe("离开创作页", () => {
    it.each([
      { label: "没有未保存的更改时直接回到角色库", edit: false, confirmed: true, leaves: true },
      { label: "有未保存的更改且取消确认时留在创作页", edit: true, confirmed: false, leaves: false },
      { label: "有未保存的更改且确认离开时回到角色库", edit: true, confirmed: true, leaves: true },
    ])("$label", async ({ edit, confirmed, leaves }) => {
      // window.confirm 是浏览器原生对话框，按用户的选择作答。
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(confirmed);
      const backend = new MockDesktopBackend();
      await renderCreatePage(backend);
      if (edit) fireEvent.change(screen.getByLabelText(/名称/), { target: { value: "未保存" } });

      await act(async () => {
        fireEvent.click(screen.getAllByRole("button", { name: "返回角色库" })[0]);
      });

      expect(confirm.mock.calls).toEqual(edit ? [["有未保存的更改，确定要离开创作页吗？"]] : []);
      expect(desktopStore.getState().mainView).toBe(leaves ? "characters" : "characterCreate");
      expect(paramsOf(backend.recordedRequests, "card.list")).toHaveLength(leaves ? 1 : 0);
    });
  });
});
