import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HarnessActions } from "../../../contracts/actions";
import type { CardGetResult } from "../../../contracts/protocol";
import { CharacterCompatModal } from "../CharacterCompatModal";

function createMockActions(cardGet: HarnessActions["cardGet"]): HarnessActions {
  return {
    cardGet,
  } as unknown as HarnessActions;
}

function cardGetResult(card: Record<string, unknown>): CardGetResult {
  return {
    card_id: "card-imported-001",
    state: "imported",
    source: "imported_png",
    created_at: "",
    updated_at: "",
    read_only: false,
    avatar: null,
    card,
  };
}

function cardWithStoredFields(): Record<string, unknown> {
  return {
    spec: "chara_card_v3",
    spec_version: "3.0",
    data: {
      name: "白厄",
      description: " {{setvar::hp::100}} 的描述",
      character_book: {
        entries: [
          {
            keys: ["白厄"],
            content: "条目一",
            probability: 70,
            extensions: { selectiveLogic: 9 },
          },
        ],
      },
      extensions: {
        hsr: {
          event_system: {
            events: [{ runtime_trigger: { kind: "time" } }],
          },
        },
      },
    },
  };
}

describe("CharacterCompatModal（V6：角色详情兼容性回看）", () => {
  afterEach(() => {
    cleanup();
  });

  it("载入中先呈现，随后渲染静态派生报告与边界说明", async () => {
    const cardGet = vi.fn().mockResolvedValue(cardGetResult(cardWithStoredFields()));
    render(<CharacterCompatModal cardId="card-imported-001" cardName="白厄" actions={createMockActions(cardGet)} onClose={vi.fn()} />);

    expect(screen.getByTestId("compat-modal-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("compat-modal-report")).toBeInTheDocument();
    });
    expect(cardGet).toHaveBeenCalledWith("card-imported-001");
    // 派生视图只呈现存而不运行与越界警告；导入时事实（已应用等）不在此还原
    expect(screen.getByText("未执行（存而不运行）")).toBeInTheDocument();
    expect(screen.getByText("世界书存而不运行字段（1）")).toBeInTheDocument();
    expect(screen.getByText(/selectiveLogic=9（越界，运行时按 0 处理）/)).toBeInTheDocument();
    expect(screen.queryByText("已应用")).not.toBeInTheDocument();
    expect(screen.getByText(/以导入当时的报告为准/)).toBeInTheDocument();
    // 紧凑变体挂载在角色详情
    const reportRoot = screen.getByTestId("compat-modal-report").firstElementChild as HTMLElement;
    expect(reportRoot.className).toContain("xfer-compat-report-compact");
  });

  it("卡内无存而不运行项时呈现「无兼容报告项」空态", async () => {
    const cardGet = vi.fn().mockResolvedValue(
      cardGetResult({
        spec: "chara_card_v3",
        spec_version: "3.0",
        data: { name: "白厄", description: "普通描述，{{char}} 宏不进报告" },
      }),
    );
    render(<CharacterCompatModal cardId="card-imported-001" cardName="白厄" actions={createMockActions(cardGet)} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("无兼容报告项")).toBeInTheDocument();
    });
  });

  it("card.get 失败如实呈现原始错误，可重试", async () => {
    const cardGet = vi
      .fn()
      .mockRejectedValueOnce(new Error("card_not_found: card-imported-001"))
      .mockResolvedValueOnce(cardGetResult(cardWithStoredFields()));
    const onClose = vi.fn();
    render(<CharacterCompatModal cardId="card-imported-001" cardName="白厄" actions={createMockActions(cardGet)} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByTestId("compat-modal-error")).toBeInTheDocument();
      expect(screen.getByText(/card_not_found: card-imported-001/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("compat-modal-retry"));
    await waitFor(() => {
      expect(screen.getByTestId("compat-modal-report")).toBeInTheDocument();
    });
    expect(cardGet).toHaveBeenCalledTimes(2);
  });

  it("card.get 返回缺少卡 JSON 时如实报协议不一致，不伪造空报告", async () => {
    const cardGet = vi.fn().mockResolvedValue({});
    render(<CharacterCompatModal cardId="card-imported-001" cardName="白厄" actions={createMockActions(cardGet)} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("compat-modal-error")).toBeInTheDocument();
      expect(screen.getByText(/缺少完整卡 JSON/)).toBeInTheDocument();
    });
    expect(screen.queryByTestId("compat-modal-report")).not.toBeInTheDocument();
  });

  it("关闭按钮与遮罩点击触发 onClose", async () => {
    const cardGet = vi.fn().mockResolvedValue(cardGetResult(cardWithStoredFields()));
    const onClose = vi.fn();
    render(<CharacterCompatModal cardId="card-imported-001" cardName="白厄" actions={createMockActions(cardGet)} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByTestId("compat-modal-report")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("compat-modal-close"));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("compat-modal"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
