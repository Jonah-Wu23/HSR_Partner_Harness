import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CardImportPreviewPayload, DesktopCommand } from "../../../contracts/protocol";
import { createActionController } from "../../../services/actions";
import { DesktopRequestError, type DesktopBackend } from "../../../services/backend";
import { MockDesktopBackend } from "../../../services/mockDesktopBackend";
import { desktopStore } from "../../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../../test/fakeBackend";
import { CharacterImportFlow, resolveDroppedCardPath } from "../CharacterImportFlow";

/** card.peek_import 返回的预览，形状同 Sidecar。 */
function preview(overrides: Partial<CardImportPreviewPayload> = {}): CardImportPreviewPayload {
  return {
    name: "白厄（3.4前）",
    spec_version: "3.0",
    format: "json",
    avatar_available: false,
    avatar_width: null,
    avatar_height: null,
    greeting_count: 6,
    world_book_entries: 20,
    tags: ["星核猎手"],
    report: {
      applied: ["data.name", "data.description", "data.character_book"],
      preserved: ["data.extensions.talkativeness"],
      not_executed: [{ category: "command_panels", text: "data.extensions.hsr.command_panels" }],
      normalized_from_root: [],
      warnings: [],
      errors: [],
    },
    ...overrides,
  };
}

/** 回放一次导入：card.peek_import 返回 peek 的结果，导入成功后 actions 刷新 card.list。 */
function importReplay(path: string, peek: (command: DesktopCommand) => unknown) {
  return fakeBackend(
    (command) => {
      switch (command.method) {
        case "card.peek_import":
          return peek(command);
        case "card.import_json":
        case "card.import_png":
          return { card_id: "card-imported-9", name: "白厄（3.4前）", state: "imported", report: preview().report };
        case "card.list":
          return { cards: [] };
        default:
          return unexpectedCommand(command);
      }
    },
    { pickFileResult: path },
  );
}

function renderFlow(backend: DesktopBackend, options: { strict?: boolean } = {}) {
  const { actions } = createActionController(backend);
  const onSuccess = vi.fn();
  const flow = (
    <CharacterImportFlow backend={backend} actions={actions} onClose={vi.fn()} onSuccess={onSuccess} />
  );
  render(options.strict ? <StrictMode>{flow}</StrictMode> : flow);
  return { onSuccess };
}

async function pickFile(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "选择文件" }));
  });
}

function requestLog(commands: readonly DesktopCommand[]): [string, Record<string, unknown>][] {
  return commands.map((command) => [command.method, command.params]);
}

describe("CharacterImportFlow", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it("选择 JSON 卡后展示预览，确认导入写入角色库并刷新列表", async () => {
    const backend = new MockDesktopBackend("single-project", { pickFileResult: "C:/Cards/bai.json" });
    const { onSuccess } = renderFlow(backend);

    await pickFile();

    expect(await screen.findByText("导入预览")).toBeInTheDocument();
    expect(screen.getByText("JSON 卡")).toBeInTheDocument();
    expect(screen.getByText("白厄（3.4前）")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText(/已应用 3 项/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    expect(await screen.findByText("导入完成")).toBeInTheDocument();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(requestLog(backend.recordedRequests)).toEqual([
      ["card.peek_import", { path: "C:/Cards/bai.json" }],
      ["card.import_json", { path: "C:/Cards/bai.json", as_duplicate: false }],
      ["card.list", { include_archived: true }],
    ]);
    expect(desktopStore.getState().characterLibrary.cards.map((card) => card.name)).toContain("白厄（3.4前）");
  });

  it.each([
    ["JSON", "card.import_json", "C:/Cards/bai.json"],
    ["PNG", "card.import_png", "C:/Cards/白厄.png"],
  ])("%s 卡作为副本导入时按预览格式下发 %s 并带 as_duplicate", async (_label, method, path) => {
    const backend = new MockDesktopBackend("single-project", { pickFileResult: path });
    renderFlow(backend);

    await pickFile();
    await screen.findByText("导入预览");
    fireEvent.click(screen.getByRole("checkbox", { name: "作为副本导入" }));
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    expect(await screen.findByText("白厄（3.4前）（副本）")).toBeInTheDocument();
    expect(requestLog(backend.recordedRequests)).toEqual([
      ["card.peek_import", { path }],
      [method, { path, as_duplicate: true }],
      ["card.list", { include_archived: true }],
    ]);
  });

  it("导入命令跟随预览返回的 format，不看文件扩展名", async () => {
    const { backend, commands } = importReplay("C:/Cards/伪装.png", () => ({ preview: preview() }));
    renderFlow(backend);

    await pickFile();
    expect(await screen.findByText("JSON 卡")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    await screen.findByText("导入完成");
    expect(requestLog(commands)).toEqual([
      ["card.peek_import", { path: "C:/Cards/伪装.png" }],
      ["card.import_json", { path: "C:/Cards/伪装.png", as_duplicate: false }],
      ["card.list", { include_archived: true }],
    ]);
  });

  it.each([
    [512, 512, "512 × 512"],
    [null, null, "未能解析"],
  ])("PNG 预览说明头像取自 PNG 字节，头像尺寸 %s×%s 显示为「%s」", async (width, height, text) => {
    const { backend } = importReplay("C:/Cards/白厄.png", () => ({
      preview: preview({ format: "png", avatar_available: true, avatar_width: width, avatar_height: height }),
    }));
    renderFlow(backend);

    await pickFile();

    expect(await screen.findByText("PNG 卡")).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByText(/PNG 字节即头像/)).toBeInTheDocument();
  });

  it("用户取消文件对话框时停留在选择页且不发请求", async () => {
    const backend = new MockDesktopBackend("single-project", { pickFileResult: null });
    renderFlow(backend);

    await pickFile();

    expect(screen.getByRole("heading", { name: "导入角色" })).toBeInTheDocument();
    expect(backend.recordedRequests).toEqual([]);
  });

  it("文件对话框打开失败时进入错误态并显示原始错误", async () => {
    const backend = new MockDesktopBackend();
    // Tauri dialog 插件不可用属于平台边界，这里让文件对话框直接抛错。
    backend.pickFile = () => Promise.reject(new Error("dialog plugin unavailable"));
    renderFlow(backend);

    await pickFile();

    expect(screen.getByText("打开文件对话框失败")).toBeInTheDocument();
    expect(screen.getByText(/dialog plugin unavailable/)).toBeInTheDocument();
    expect(backend.recordedRequests).toEqual([]);
  });

  it("解析失败显示错误码与原文，重试后进入预览", async () => {
    let attempts = 0;
    const { backend, commands } = importReplay("C:/Cards/damaged.png", () => {
      attempts += 1;
      if (attempts === 1) {
        throw new DesktopRequestError("card_import_failed", "角色卡解析失败：PNG 缺少 chara 文本块");
      }
      return { preview: preview() };
    });
    renderFlow(backend);

    await pickFile();

    expect(await screen.findByText("解析失败")).toBeInTheDocument();
    expect(screen.getByText("card_import_failed：角色卡解析失败：PNG 缺少 chara 文本块")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("导入预览")).toBeInTheDocument();
    expect(requestLog(commands)).toEqual([
      ["card.peek_import", { path: "C:/Cards/damaged.png" }],
      ["card.peek_import", { path: "C:/Cards/damaged.png" }],
    ]);
  });

  it("导入失败显示错误码与原文", async () => {
    const { backend } = fakeBackend(
      (command) => {
        if (command.method === "card.peek_import") return { preview: preview() };
        if (command.method === "card.import_json") {
          throw new DesktopRequestError("card_import_failed", "读取角色卡文件失败：文件已被移动");
        }
        return unexpectedCommand(command);
      },
      { pickFileResult: "C:/Cards/bai.json" },
    );
    renderFlow(backend);

    await pickFile();
    await screen.findByText("导入预览");
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));

    expect(await screen.findByText("导入失败")).toBeInTheDocument();
    expect(screen.getByText("card_import_failed：读取角色卡文件失败：文件已被移动")).toBeInTheDocument();
  });

  it("导入完成后「继续导入」回到选择页", async () => {
    const backend = new MockDesktopBackend("single-project", { pickFileResult: "C:/Cards/bai.json" });
    renderFlow(backend);

    await pickFile();
    await screen.findByText("导入预览");
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
    await screen.findByText("导入完成");

    fireEvent.click(screen.getByRole("button", { name: "继续导入" }));

    expect(screen.getByRole("heading", { name: "导入角色" })).toBeInTheDocument();
  });

  it("兼容报告含警告与错误时，预览摘要列出数量并展示原文", async () => {
    const { backend } = importReplay("C:/Cards/warn.json", () => ({
      preview: preview({
        report: { ...preview().report, warnings: ["发现未知扩展字段"], errors: ["spec_version 缺失"] },
      }),
    }));
    renderFlow(backend);

    await pickFile();

    expect(await screen.findByText(/警告 1 项 · 错误 1 项/)).toBeInTheDocument();
    expect(screen.getByText("发现未知扩展字段")).toBeInTheDocument();
    expect(screen.getByText("spec_version 缺失")).toBeInTheDocument();
  });

  it("StrictMode 双挂载后异步解析仍进入预览", async () => {
    const backend = new MockDesktopBackend("single-project", { pickFileResult: "C:/Cards/bai.json" });
    renderFlow(backend, { strict: true });

    await pickFile();

    expect(await screen.findByText("导入预览")).toBeInTheDocument();
    expect(screen.queryByText(/正在解析/)).not.toBeInTheDocument();
  });

  it("浏览器拖放的文件没有绝对路径时报错且不解析", () => {
    const backend = new MockDesktopBackend();
    renderFlow(backend);

    fireEvent.drop(screen.getByRole("button", { name: "选择角色卡文件" }), {
      dataTransfer: { files: [new File(["x"], "bai.png", { type: "image/png" })] },
    });

    expect(screen.getByText("不支持此操作")).toBeInTheDocument();
    expect(screen.getByText(/浏览器环境无法从拖放文件获取绝对路径/)).toBeInTheDocument();
    expect(backend.recordedRequests).toEqual([]);
  });
});

describe("resolveDroppedCardPath", () => {
  it("单个文件返回其路径", () => {
    expect(resolveDroppedCardPath(["C:/Cards/bai.png"])).toEqual({ ok: true, path: "C:/Cards/bai.png" });
  });

  it.each([
    ["多个文件", ["C:/a.png", "C:/b.png"], /一次只能导入一个角色卡文件/],
    ["空拖放", [], /未携带文件路径/],
  ])("%s 时拒绝并说明原因", (_label, paths, reason) => {
    const result = resolveDroppedCardPath(paths);
    expect(result.ok).toBe(false);
    expect(result.ok ? "" : result.reason).toMatch(reason);
  });
});
