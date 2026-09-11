import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HarnessActions } from "../../../contracts/actions";
import { desktopStore } from "../../../stores/desktopStore";
import { SettingsCenter } from "../SettingsCenter";

afterEach(cleanup);

/**
 * 只验证「长期记忆」页的接线（导航条目 + PAGES 映射 + actions 透传）。
 * 其余页面 props 与本用例无关，用显式 cast 提供最小集合。
 */
function renderMemoryPage() {
  const props = {
    open: true,
    page: "memory",
    onPageChange: vi.fn(),
    onClose: vi.fn(),
    // 该页只消费记忆命令；未接入时面板会如实说明。
    actions: undefined as HarnessActions | undefined,
  } as unknown as Parameters<typeof SettingsCenter>[0];
  render(<SettingsCenter {...props} />);
  return props;
}

describe("SettingsCenter 长期记忆页（V039-S4-003）", () => {
  it("导航包含「长期记忆」并指向 memory 页", () => {
    const props = renderMemoryPage();

    expect(screen.getByRole("dialog", { name: "设置" })).toBeInTheDocument();
    expect(screen.getByTestId("memory-panel")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "长期记忆" }));
    expect(props.onPageChange).toHaveBeenCalledWith("memory");
  });

  it("接入记忆命令时渲染真实操作能力，未接入时如实说明", () => {
    renderMemoryPage();
    expect(screen.getByTestId("memory-panel")).toHaveTextContent("未接入记忆命令");

    cleanup();
    desktopStore.setState({
      activeConversationId: "conv-1",
      memories: [],
      memoriesByConversation: { "conv-1": [] },
      memoryPanel: { conversationId: "conv-1", loading: false, error: null, loaded: true },
    });
    const withActions = {
      open: true,
      page: "memory",
      onPageChange: vi.fn(),
      onClose: vi.fn(),
      actions: {
        listMemories: vi.fn().mockResolvedValue([]),
        createMemory: vi.fn(),
        updateMemory: vi.fn(),
        deleteMemory: vi.fn(),
      } as unknown as HarnessActions,
    } as unknown as Parameters<typeof SettingsCenter>[0];
    render(<SettingsCenter {...withActions} />);

    expect(screen.getByTestId("memory-panel")).toHaveTextContent("长期记忆按 account");
    expect(screen.getByTestId("memory-create-submit")).toBeInTheDocument();
  });
});
