import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HarnessActions } from "../../../contracts/actions";
import type { DesktopCommand } from "../../../contracts/protocol";
import { createActionController } from "../../../services/actions";
import { DesktopRequestError, type DesktopBackend } from "../../../services/backend";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore, useDesktopStore } from "../../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../../test/fakeBackend";
import { CharacterLibraryPage } from "../CharacterLibraryPage";

/** 与 AppShell 一致：角色库视图模型取自 store，由 card.list 等命令的结果驱动。 */
function LibraryHost(props: {
  actions: HarnessActions;
  backend: DesktopBackend;
  onConfigureCardVoice?: (cardId: string) => void;
}) {
  const vm = useDesktopStore((state) => state.characterLibrary);
  return <CharacterLibraryPage vm={vm} {...props} />;
}

/** 打开角色库（card.list 装载卡片）后渲染页面。 */
async function renderLibrary(
  backend: DesktopBackend,
  props: { onConfigureCardVoice?: (cardId: string) => void } = {},
): Promise<void> {
  const { actions } = createActionController(backend);
  await actions.openCharacterLibrary();
  render(<LibraryHost actions={actions} backend={backend} {...props} />);
}

function requestLog(commands: readonly DesktopCommand[]): [string, Record<string, unknown>][] {
  return commands.map((command) => [command.method, command.params]);
}

async function click(element: HTMLElement): Promise<void> {
  await act(async () => {
    fireEvent.click(element);
  });
}

describe("CharacterLibraryPage", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  describe("空态", () => {
    it("零角色时只给创建与导入两个入口，不显示筛选控件", async () => {
      const { backend, commands } = fakeBackend((command) =>
        command.method === "card.list" ? { cards: [] } : unexpectedCommand(command),
      );
      await renderLibrary(backend);

      expect(screen.getByRole("heading", { name: "角色库还是空的" })).toBeInTheDocument();
      expect(screen.queryByLabelText("搜索角色")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("按来源筛选")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("按音色状态筛选")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /导入角色卡/ }));
      expect(screen.getByTestId("import-flow-modal")).toBeInTheDocument();

      await click(screen.getByRole("button", { name: /创建第一个角色/ }));
      expect(desktopStore.getState().mainView).toBe("characterCreate");
      expect(desktopStore.getState().characterCreate.cardId).toBeNull();
      expect(requestLog(commands)).toEqual([["card.list", { include_archived: true }]]);
    });

    it("筛选无结果时保留筛选栏，清空筛选后恢复列表", async () => {
      await renderLibrary(new MockDesktopBackend());

      const searchInput = screen.getByLabelText("搜索角色");
      fireEvent.change(searchInput, { target: { value: "不存在的神秘角色" } });

      expect(screen.getByRole("heading", { name: "还没有符合筛选的角色" })).toBeInTheDocument();
      expect(searchInput).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));

      expect(screen.queryByTestId("empty-library-filtered")).not.toBeInTheDocument();
      expect(screen.getByText("白厄")).toBeInTheDocument();
    });
  });

  describe("内置卡与兼容性", () => {
    it("内置卡标注只读，只提供查看与兼容性入口，查看时以只读方式打开创作页", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      expect(screen.getAllByText("内置 · 只读")).toHaveLength(3);
      for (const name of ["白厄", "流萤", "三月七"]) {
        expect(screen.getByRole("button", { name: `查看${name}` })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: `查看${name}的兼容性` })).toBeInTheDocument();
      }
      expect(screen.queryByRole("button", { name: "删除白厄" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "归档白厄" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "复制白厄" })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "查看白厄" }));

      await waitFor(() =>
        expect(desktopStore.getState().characterCreate).toMatchObject({
          cardId: "builtin:phainon",
          readOnly: true,
          loading: false,
        }),
      );
      expect(desktopStore.getState().mainView).toBe("characterCreate");
      expect(backend.recordedRequests.at(-1)).toMatchObject({
        method: "card.get",
        params: { card_id: "builtin:phainon" },
      });
    });

    it("兼容性按钮打开回看弹窗，展示 card.get 返回的报告", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);
      fireEvent.change(screen.getByLabelText("按来源筛选"), { target: { value: "archived" } });

      fireEvent.click(screen.getByRole("button", { name: "查看砂金的兼容性" }));

      expect(await screen.findByTestId("compat-modal-report")).toBeInTheDocument();
      expect(screen.getByText("声明式指令面板（1）")).toBeInTheDocument();
      expect(screen.getByText("data.extensions.hsr.command_panels")).toBeInTheDocument();
      expect(backend.recordedRequests.at(-1)).toMatchObject({
        method: "card.get",
        params: { card_id: "card-imported-004" },
      });
    });
  });

  describe("筛选", () => {
    it.each([
      ["按来源筛选", "all", ["card-saved-002", "builtin:phainon"], ["card-imported-004"]],
      ["按来源筛选", "builtin", ["builtin:phainon", "builtin:firefly"], ["card-saved-002", "card-draft-001"]],
      ["按来源筛选", "user_created", ["card-saved-002", "card-draft-001"], ["builtin:phainon"]],
      ["按来源筛选", "imported", ["card-invalid-003"], ["card-saved-002", "card-imported-004"]],
      ["按来源筛选", "draft", ["card-draft-001"], ["card-saved-002"]],
      ["按来源筛选", "archived", ["card-imported-004"], ["card-saved-002", "builtin:phainon"]],
      ["按音色状态筛选", "voice_ready", ["card-saved-002", "builtin:phainon"], ["card-draft-001"]],
      ["按音色状态筛选", "voice_unconfigured", ["card-draft-001", "builtin:firefly"], ["card-saved-002"]],
    ])("%s「%s」只显示符合条件的卡", async (selectLabel, value, visible, hidden) => {
      await renderLibrary(new MockDesktopBackend());

      fireEvent.change(screen.getByLabelText(selectLabel), { target: { value } });

      for (const cardId of visible) {
        expect(screen.getByTestId(`char-card-${cardId}`)).toBeInTheDocument();
      }
      for (const cardId of hidden) {
        expect(screen.queryByTestId(`char-card-${cardId}`)).not.toBeInTheDocument();
      }
    });
  });

  describe("卡片操作", () => {
    it("删除需二次确认：取消不发请求，确认后经 card.delete 删除并从列表移除", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      fireEvent.click(screen.getByRole("button", { name: "删除卡芙卡" }));
      expect(screen.getByRole("heading", { name: "删除「卡芙卡」？" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "取消" }));
      expect(screen.queryByTestId("delete-modal")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "删除卡芙卡" }));
      fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

      await waitFor(() => expect(screen.queryByTestId("char-card-card-saved-002")).not.toBeInTheDocument());
      expect(screen.queryByTestId("delete-modal")).not.toBeInTheDocument();
      expect(requestLog(backend.recordedRequests).slice(1)).toEqual([
        ["card.delete", { card_id: "card-saved-002", confirm: true }],
        ["card.list", { include_archived: true }],
      ]);
    });

    it("复制后列表出现副本", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      fireEvent.click(screen.getByRole("button", { name: "复制卡芙卡" }));

      expect(await screen.findByText("卡芙卡（副本）")).toBeInTheDocument();
      expect(requestLog(backend.recordedRequests).slice(1)).toEqual([
        ["card.duplicate", { card_id: "card-saved-002" }],
        ["card.list", { include_archived: true }],
      ]);
    });

    it("归档后卡片移出默认列表，在已归档筛选中可恢复", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      fireEvent.click(screen.getByRole("button", { name: "归档卡芙卡" }));
      await waitFor(() => expect(screen.queryByTestId("char-card-card-saved-002")).not.toBeInTheDocument());
      expect(screen.queryByTestId("in-use-strip")).not.toBeInTheDocument();

      fireEvent.change(screen.getByLabelText("按来源筛选"), { target: { value: "archived" } });
      fireEvent.click(screen.getByRole("button", { name: "恢复卡芙卡" }));
      await waitFor(() => expect(screen.queryByTestId("char-card-card-saved-002")).not.toBeInTheDocument());

      fireEvent.change(screen.getByLabelText("按来源筛选"), { target: { value: "all" } });
      expect(screen.getByTestId("char-card-card-saved-002")).toBeInTheDocument();
      expect(
        requestLog(backend.recordedRequests).filter(([method]) => method !== "card.list"),
      ).toEqual([
        ["card.archive", { card_id: "card-saved-002" }],
        ["card.unarchive", { card_id: "card-saved-002" }],
      ]);
    });

    it("使用已发布卡时按该卡绑定项建会话、更新使用中标记并回到聊天视图", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      // 砂金当前已归档；已发布且未归档的卡才进入可选搭档目录。
      fireEvent.change(screen.getByLabelText("按来源筛选"), { target: { value: "archived" } });
      fireEvent.click(screen.getByRole("button", { name: "恢复砂金" }));
      await waitFor(() =>
        expect(screen.queryByTestId("char-card-card-imported-004")).not.toBeInTheDocument(),
      );
      fireEvent.change(screen.getByLabelText("按来源筛选"), { target: { value: "all" } });

      fireEvent.click(screen.getByRole("button", { name: "使用砂金" }));

      await waitFor(() => expect(desktopStore.getState().mainView).toBe("chat"));
      // 角色库没有目录上下文，先按权威目录补取 pair.list；建会话用绑定 id（reuse_active 复用同绑定会话），
      // 会话创建成功后才经 card.select_active 更新「使用中」标记。
      expect(requestLog(backend.recordedRequests).slice(-4)).toEqual([
        ["pair.list", {}],
        [
          "conversation.create",
          { binding_id: "card-bind-card-imported-004", reuse_active: true },
        ],
        ["card.select_active", { card_id: "card-imported-004" }],
        ["card.list", { include_archived: true }],
      ]);
    });

    it("草稿卡不在搭档目录时如实报错，留在角色库且不发会话创建请求", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      fireEvent.click(screen.getByRole("button", { name: "使用新角色草稿" }));

      await waitFor(() =>
        expect(desktopStore.getState().toasts.at(-1)?.text).toBe(
          "该角色卡当前不在可选搭档目录中（草稿、已归档或绑定尚未生效），无法开始对话",
        ),
      );
      expect(desktopStore.getState().mainView).toBe("characters");
      expect(requestLog(backend.recordedRequests).slice(1)).toEqual([["pair.list", {}]]);
      expect(requestLog(backend.recordedRequests).filter(([method]) => method === "conversation.create")).toEqual([]);
      expect(requestLog(backend.recordedRequests).filter(([method]) => method === "card.select_active")).toEqual([]);
    });

    it("编辑按钮与使用中置顶条都打开该卡的创作页", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      const inUseStrip = screen.getByTestId("in-use-strip");
      expect(within(inUseStrip).getByText("卡芙卡")).toBeInTheDocument();
      expect(within(inUseStrip).getByText("使用中")).toBeInTheDocument();
      expect(within(inUseStrip).getByText("音色已绑定")).toBeInTheDocument();

      fireEvent.click(within(inUseStrip).getByRole("button"));
      await waitFor(() => expect(desktopStore.getState().characterCreate.cardId).toBe("card-saved-002"));
      expect(desktopStore.getState().mainView).toBe("characterCreate");

      fireEvent.click(screen.getByRole("button", { name: "编辑卡芙卡" }));
      await waitFor(() =>
        expect(backend.recordedRequests.filter((command) => command.method === "card.get")).toHaveLength(2),
      );
      expect(desktopStore.getState().characterCreate.cardId).toBe("card-saved-002");
    });

    it("返回聊天切回聊天视图", async () => {
      await renderLibrary(new MockDesktopBackend());
      expect(desktopStore.getState().mainView).toBe("characters");

      fireEvent.click(screen.getByRole("button", { name: "返回聊天" }));

      expect(desktopStore.getState().mainView).toBe("chat");
    });
  });

  describe("加载失败", () => {
    it("card.list 失败时显示错误原文，重试后显示卡片", async () => {
      let attempts = 0;
      const { backend } = fakeBackend((command) => {
        if (command.method !== "card.list") return unexpectedCommand(command);
        attempts += 1;
        if (attempts === 1) throw new DesktopRequestError("internal_error", "database is locked");
        return {
          cards: [
            {
              card_id: "builtin:phainon",
              name: "白厄",
              state: "saved",
              source: "builtin",
              updated_at: "",
              has_avatar: false,
              voice_state: "voice_ready",
              active: false,
              read_only: true,
              archived: false,
            },
          ],
        };
      });
      await renderLibrary(backend);

      expect(screen.getByTestId("library-error-banner")).toHaveTextContent("角色库加载失败：database is locked");

      fireEvent.click(screen.getByRole("button", { name: "重试" }));

      expect(await screen.findByText("白厄")).toBeInTheDocument();
      expect(screen.queryByTestId("library-error-banner")).not.toBeInTheDocument();
    });

    it("导入失败的卡显示失败提示，可查看详情与删除", async () => {
      await renderLibrary(new MockDesktopBackend());

      const card = screen.getByTestId("char-card-card-invalid-003");
      expect(within(card).getByText("导入失败")).toBeInTheDocument();
      expect(within(card).getByText("导入失败 · 未创建角色")).toBeInTheDocument();
      expect(within(card).getByText("解析中断：文件格式或元数据损坏。可移除后重新导入。")).toBeInTheDocument();

      fireEvent.click(within(card).getByRole("button", { name: "查看导入错误" }));
      expect(screen.getByTestId("notice-modal")).toHaveTextContent("导入失败详情");
      fireEvent.click(screen.getByRole("button", { name: "知道了" }));

      fireEvent.click(within(card).getByRole("button", { name: "删除（导入失败的角色卡）" }));
      expect(screen.getByTestId("delete-modal")).toBeInTheDocument();
    });
  });

  describe("导入、导出与音色入口", () => {
    it("工具栏导入按钮打开导入流程", async () => {
      await renderLibrary(new MockDesktopBackend());

      fireEvent.click(screen.getByRole("button", { name: "导入角色" }));

      expect(screen.getByTestId("import-flow-modal")).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "导入角色" })).toBeInTheDocument();
    });

    it("卡片导出按钮打开导出流程并读取该卡", async () => {
      const backend = new MockDesktopBackend();
      await renderLibrary(backend);

      fireEvent.click(screen.getByRole("button", { name: "导出卡芙卡" }));

      expect(screen.getByTestId("export-flow-modal")).toBeInTheDocument();
      expect(await screen.findByRole("heading", { name: "导出角色" })).toBeInTheDocument();
      expect(backend.recordedRequests.at(-1)).toMatchObject({
        method: "card.get",
        params: { card_id: "card-saved-002" },
      });
    });

    it.each([
      ["悬停操作栏", 0],
      ["底部音色状态", 1],
    ])("%s的配置音色入口把卡 id 交给 onConfigureCardVoice", async (_label, index) => {
      const onConfigureCardVoice = vi.fn();
      await renderLibrary(new MockDesktopBackend(), { onConfigureCardVoice });

      const entries = screen.getAllByRole("button", { name: "配置卡芙卡的音色" });
      expect(entries).toHaveLength(2);
      fireEvent.click(entries[index]);

      expect(onConfigureCardVoice).toHaveBeenCalledWith("card-saved-002");
    });

    it("未注入 onConfigureCardVoice 时不显示配置音色入口", async () => {
      await renderLibrary(new MockDesktopBackend());

      expect(screen.queryByRole("button", { name: "配置卡芙卡的音色" })).not.toBeInTheDocument();
    });
  });
});
