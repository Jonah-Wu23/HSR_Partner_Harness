import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CardGetResult, DesktopCommand } from "../../../contracts/protocol";
import { createActionController } from "../../../services/actions";
import { DesktopRequestError, type DesktopBackend } from "../../../services/backend";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../../test/fakeBackend";
import { CharacterExportFlow } from "../CharacterExportFlow";

/** mock 后端里已保存、音色已绑定的用户卡。 */
const KAFKA = { cardId: "card-saved-002", cardName: "卡芙卡" };

/** card.get 的响应：带两条世界书条目与两个扩展键的卡。 */
function cardGetResult(overrides: Partial<CardGetResult> = {}): CardGetResult {
  return {
    card_id: KAFKA.cardId,
    state: "saved",
    source: "user_created",
    created_at: "2026-08-18T21:40:00+00:00",
    updated_at: "2026-08-18T21:40:00+00:00",
    read_only: false,
    avatar: { mime_type: "image/png", data_base64: "iVBORw0KGgo=" },
    card: {
      spec: "chara_card_v3",
      spec_version: "3.0",
      data: {
        name: "卡芙卡",
        first_mes: "又见面了。",
        alternate_greetings: ["好久不见。"],
        character_book: { entries: [{ keys: ["星核"], content: "条目一" }, { keys: ["猎手"], content: "条目二" }] },
        extensions: { hsr: {}, talkativeness: 0.5 },
      },
    },
    compat_report: {
      applied: [],
      preserved: [],
      not_executed: [],
      normalized_from_root: [],
      warnings: [],
      errors: [],
    },
    ...overrides,
  };
}

function renderExport(backend: DesktopBackend, card: { cardId: string; cardName: string } = KAFKA) {
  const { actions } = createActionController(backend);
  const onSuccess = vi.fn();
  const onClose = vi.fn();
  render(
    <CharacterExportFlow
      cardId={card.cardId}
      cardName={card.cardName}
      backend={backend}
      actions={actions}
      onClose={onClose}
      onSuccess={onSuccess}
    />,
  );
  return { onSuccess, onClose };
}

/** mock 后端先经 card.set_avatar 给卡芙卡设置头像，card.get 才会带回头像。 */
async function mockWithAvatar(saveFileResult: string | null): Promise<MockDesktopBackend> {
  const backend = new MockDesktopBackend("single-project", { saveFileResult });
  await createActionController(backend).actions.cardSetAvatar(KAFKA.cardId, "C:/avatars/kafka.png");
  return backend;
}

function paramsOf(commands: readonly DesktopCommand[], method: string): Record<string, unknown>[] {
  return commands.filter((command) => command.method === method).map((command) => command.params);
}

async function clickExport(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "导出" }));
  });
}

describe("CharacterExportFlow", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it.each([
    { label: "已设置头像", avatar: { mime_type: "image/png", data_base64: "iVBORw0KGgo=" }, avatarText: "已绑定头像" },
    { label: "没有头像", avatar: null, avatarText: "无头像，JSON 中只保留引用" },
  ])("确认面板按 card.get 结果列出卡内容（$label）", async ({ avatar, avatarText }) => {
    const { backend, commands } = fakeBackend((command) =>
      command.method === "card.get" ? cardGetResult({ avatar }) : unexpectedCommand(command),
    );
    renderExport(backend);

    expect(await screen.findByLabelText("导出文件名")).toHaveValue("卡芙卡.json");
    expect(screen.getByText(avatarText)).toBeInTheDocument();
    expect(screen.getByText("Character Card v3.0")).toBeInTheDocument();
    expect(screen.getByText("2 条（含开场白与备选）")).toBeInTheDocument();
    expect(screen.getByText("2 条已包含")).toBeInTheDocument();
    expect(screen.getByText("hsr、talkativeness 等 2 项")).toBeInTheDocument();
    expect(paramsOf(commands, "card.get")).toEqual([{ card_id: KAFKA.cardId }]);
  });

  it.each([
    { label: "保持勾选", uncheck: false, saveAvatar: true, resultText: "头像文件已配套保存" },
    { label: "取消勾选", uncheck: true, saveAvatar: false, resultText: "未保存头像文件" },
  ])("JSON 导出时$label「同时保存头像文件」，下发 save_avatar=$saveAvatar", async ({ uncheck, saveAvatar, resultText }) => {
    const backend = await mockWithAvatar("C:/Cards/卡芙卡.json");
    const { onSuccess } = renderExport(backend);
    await screen.findByText("已绑定头像");
    if (uncheck) fireEvent.click(screen.getByRole("checkbox", { name: "同时保存头像文件" }));

    await clickExport();

    expect(await screen.findByText("导出完成")).toBeInTheDocument();
    expect(screen.getByText("C:/Cards/卡芙卡.json")).toBeInTheDocument();
    expect(screen.getByText(resultText)).toBeInTheDocument();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(paramsOf(backend.recordedRequests, "card.export_json")).toEqual([
      { card_id: KAFKA.cardId, path: "C:/Cards/卡芙卡.json", save_avatar: saveAvatar },
    ]);
  });

  it("取消保存对话框时停留在确认面板且不导出", async () => {
    const backend = new MockDesktopBackend("single-project", { saveFileResult: null });
    renderExport(backend);
    await screen.findByLabelText("导出文件名");

    await clickExport();

    expect(screen.getByLabelText("导出文件名")).toBeInTheDocument();
    expect(paramsOf(backend.recordedRequests, "card.export_json")).toEqual([]);
  });

  it("保存对话框打开失败时进入错误态并显示原始错误", async () => {
    const backend = new MockDesktopBackend();
    // Tauri dialog 插件不可用属于平台边界，这里让保存对话框直接抛错。
    backend.saveFile = () => Promise.reject(new Error("dialog plugin unavailable"));
    renderExport(backend);
    await screen.findByLabelText("导出文件名");

    await clickExport();

    expect(await screen.findByText("打开保存对话框失败")).toBeInTheDocument();
    expect(screen.getByText(/dialog plugin unavailable/)).toBeInTheDocument();
    expect(paramsOf(backend.recordedRequests, "card.export_json")).toEqual([]);
  });

  it("内置卡只读时引导复制，复制后刷新角色库并关闭流程", async () => {
    const { backend, commands } = fakeBackend((command) => {
      switch (command.method) {
        case "card.get":
          return cardGetResult({ card_id: "builtin:phainon", source: "builtin", read_only: true });
        case "card.duplicate":
          return { card_id: "card-copy-9", name: "白厄（副本）" };
        case "card.list":
          return { cards: [] };
        default:
          return unexpectedCommand(command);
      }
    });
    const { onSuccess, onClose } = renderExport(backend, { cardId: "builtin:phainon", cardName: "白厄" });

    expect(await screen.findByText("内置角色卡不可导出")).toBeInTheDocument();
    expect(screen.getByText("内置角色卡只读，导出前请先复制。")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "复制此卡" }));
    });

    expect(commands.map((command) => [command.method, command.params])).toEqual([
      ["card.get", { card_id: "builtin:phainon" }],
      ["card.duplicate", { card_id: "builtin:phainon" }],
      ["card.list", { include_archived: true }],
    ]);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("JSON 导出失败时显示错误码与原文", async () => {
    const { backend } = fakeBackend(
      (command) => {
        if (command.method === "card.get") return cardGetResult();
        if (command.method === "card.export_json") {
          throw new DesktopRequestError("card_export_failed", "写出角色卡文件失败：[Errno 13] Permission denied");
        }
        return unexpectedCommand(command);
      },
      { saveFileResult: "C:/Cards/卡芙卡.json" },
    );
    renderExport(backend);
    await screen.findByLabelText("导出文件名");

    await clickExport();

    expect(await screen.findByText("导出失败")).toBeInTheDocument();
    expect(
      screen.getByText("card_export_failed：写出角色卡文件失败：[Errno 13] Permission denied"),
    ).toBeInTheDocument();
    expect(screen.queryByText("PNG 导出需要头像")).not.toBeInTheDocument();
  });

  it("读取角色卡失败时显示错误码与原文", async () => {
    const { backend } = fakeBackend((command) => {
      if (command.method === "card.get") throw new DesktopRequestError("card_not_found", "角色卡不存在");
      return unexpectedCommand(command);
    });
    renderExport(backend, { cardId: "card-missing", cardName: "missing" });

    expect(await screen.findByText("加载角色卡失败")).toBeInTheDocument();
    expect(screen.getByText("card_not_found：角色卡不存在")).toBeInTheDocument();
  });

  it("切到 PNG 后文件名改为 .png、不再提供另存头像，完成页列出写入的卡信息", async () => {
    const backend = await mockWithAvatar("C:/Cards/卡芙卡.png");
    renderExport(backend);
    await screen.findByText("已绑定头像");

    fireEvent.click(screen.getByRole("radio", { name: "PNG 格式" }));

    expect(screen.getByLabelText("导出文件名")).toHaveValue("卡芙卡.png");
    expect(screen.getByText("已绑定头像，将内嵌为 PNG 图像块")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "同时保存头像文件" })).not.toBeInTheDocument();

    await clickExport();

    expect(await screen.findByText("导出完成")).toBeInTheDocument();
    expect(paramsOf(backend.recordedRequests, "card.export_png")).toEqual([
      { card_id: KAFKA.cardId, path: "C:/Cards/卡芙卡.png" },
    ]);
    expect(screen.getByText("C:/Cards/卡芙卡.png")).toBeInTheDocument();
    expect(screen.getByText("Character Card v3.0")).toBeInTheDocument();
    expect(screen.getByText("hsr")).toBeInTheDocument();
    expect(screen.getByText(/头像已内嵌 PNG 图像块/)).toBeInTheDocument();
  });

  it("无头像的卡切到 PNG 时先行警告，后端拒绝导出后显示原文与设置头像引导", async () => {
    const backend = new MockDesktopBackend("single-project", { saveFileResult: "C:/Cards/草稿.png" });
    renderExport(backend, { cardId: "card-draft-001", cardName: "新角色草稿" });
    await screen.findByText("无头像，JSON 中只保留引用");

    fireEvent.click(screen.getByRole("radio", { name: "PNG 格式" }));

    expect(screen.getByText("未设置头像，PNG 导出将被拒绝")).toBeInTheDocument();
    expect(screen.getByText(/导出将被后端拒绝/)).toBeInTheDocument();

    await clickExport();

    expect(await screen.findByText("导出失败")).toBeInTheDocument();
    expect(screen.getByText("card_export_failed：卡未设置头像，请先设置头像后再导出 PNG")).toBeInTheDocument();
    expect(screen.getByText("PNG 导出需要头像")).toBeInTheDocument();
    expect(paramsOf(backend.recordedRequests, "card.export_png")).toEqual([
      { card_id: "card-draft-001", path: "C:/Cards/草稿.png" },
    ]);
  });
});
