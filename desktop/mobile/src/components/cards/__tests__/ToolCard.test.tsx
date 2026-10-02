import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ToolRun } from "@shared/contracts/protocol";
import { ToolCard } from "../ToolCard";

describe("ToolCard", () => {
  afterEach(() => {
    cleanup();
  });
  const baseRun: ToolRun = {
    tool_call_id: "tc-1",
    conversation_id: "c1",
    task_id: "task-1",
    engine_turn_id: "turn-1",
    sequence: 1,
    status: "succeeded",
    title: "git status",
    summary: "检查工作区状态",
    details: "On branch main\nnothing to commit",
    timeline_order: 1,
  };

  it.each([
    { status: "running", label: "运行中" },
    { status: "succeeded", label: "已完成" },
    { status: "failed", label: "失败" },
    { status: "denied", label: "已否决" },
  ] as const)("$status 状态显示「$label」", ({ status, label }) => {
    render(<ToolCard run={{ ...baseRun, status }} />);
    expect(screen.getByRole("button", { name: `工具调用：${label}` })).toBeInTheDocument();
  });

  it("默认折叠，点击头部展开/收起明细", () => {
    render(<ToolCard run={baseRun} />);
    const headBtn = screen.getByRole("button");
    expect(headBtn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("On branch main\nnothing to commit")).not.toBeInTheDocument();

    // 点击展开
    fireEvent.click(headBtn);
    expect(headBtn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/On branch main/i)).toBeInTheDocument();
    expect(screen.getByText("git status")).toBeInTheDocument();
    expect(screen.getByText("检查工作区状态")).toBeInTheDocument();

    // 再次点击收起
    fireEvent.click(headBtn);
    expect(headBtn).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/On branch main/i)).not.toBeInTheDocument();
  });
});
