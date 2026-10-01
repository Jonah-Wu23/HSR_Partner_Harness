import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CardGetResult, DesktopCommand } from "../../../contracts/protocol";
import { createActionController } from "../../../services/actions";
import { DesktopRequestError } from "../../../services/backend";
import { desktopStore } from "../../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../../test/fakeBackend";
import { CharacterCompatModal } from "../CharacterCompatModal";

const CARD_ID = "card-imported-001";

/** card.get 的响应：compat_report 由后端对已存的卡重新扫描得到。 */
function cardGetResult(): CardGetResult {
  return {
    card_id: CARD_ID,
    state: "imported",
    source: "tavern_import",
    created_at: "2026-08-16T12:00:00+00:00",
    updated_at: "2026-08-16T12:00:00+00:00",
    read_only: false,
    avatar: null,
    card: { spec: "chara_card_v3", spec_version: "3.0", data: { name: "白厄" } },
    compat_report: {
      applied: ["data.name"],
      preserved: [],
      not_executed: [
        { category: "world_book", text: "character_book.entries[0].probability（存而不运行）" },
      ],
      normalized_from_root: [],
      warnings: ["character_book.entries[0].extensions.selectiveLogic=9（越界，运行时按 0 处理）"],
      errors: [],
    },
  };
}

function renderModal(respond: (command: DesktopCommand) => unknown) {
  const { backend, commands } = fakeBackend(respond);
  const { actions } = createActionController(backend);
  const onClose = vi.fn();
  render(<CharacterCompatModal cardId={CARD_ID} cardName="白厄" actions={actions} onClose={onClose} />);
  return { commands, onClose };
}

function respondCardGet(command: DesktopCommand): unknown {
  return command.method === "card.get" ? cardGetResult() : unexpectedCommand(command);
}

describe("CharacterCompatModal 角色详情兼容性回看", () => {
  afterEach(() => {
    cleanup();
    desktopStore.setState(desktopStore.getInitialState(), true);
  });

  it("先显示载入中，随后按 card.get 返回的 compat_report 呈现报告", async () => {
    const { commands } = renderModal(respondCardGet);

    expect(screen.getByTestId("compat-modal-loading")).toBeInTheDocument();
    await screen.findByTestId("compat-modal-report");
    expect(commands.map((command) => [command.method, command.params])).toEqual([
      ["card.get", { card_id: CARD_ID }],
    ]);
    expect(screen.getByText("以下按当前保存的卡内容重新扫描得到。")).toBeInTheDocument();
    expect(screen.getByText("data.name")).toBeInTheDocument();
    expect(screen.getByText("世界书存而不运行字段（1）")).toBeInTheDocument();
    expect(screen.getByText(/selectiveLogic=9（越界，运行时按 0 处理）/)).toBeInTheDocument();
  });

  it("card.get 失败时呈现错误码与原文，重试后显示报告", async () => {
    let attempts = 0;
    const { commands } = renderModal((command) => {
      if (command.method !== "card.get") return unexpectedCommand(command);
      attempts += 1;
      if (attempts === 1) throw new DesktopRequestError("internal_error", "database is locked");
      return cardGetResult();
    });

    expect(await screen.findByTestId("compat-modal-error")).toHaveTextContent(
      "兼容性视图加载失败：internal_error：database is locked",
    );

    fireEvent.click(screen.getByTestId("compat-modal-retry"));
    await screen.findByTestId("compat-modal-report");
    expect(commands.filter((command) => command.method === "card.get")).toHaveLength(2);
  });

  it("关闭按钮与遮罩点击触发 onClose", async () => {
    const { onClose } = renderModal(respondCardGet);
    await screen.findByTestId("compat-modal-report");

    fireEvent.click(screen.getByTestId("compat-modal-close"));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("compat-modal"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
