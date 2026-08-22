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
  };

  it("渲染已完成状态与标题", () => {
    render(<ToolCard run={baseRun} />);
    expect(screen.getByTestId("tool-card")).toHaveAttribute("data-tool-status", "succeeded");
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("工具调用")).toBeInTheDocument();
  });

  it("渲染运行中状态", () => {
    const runningRun: ToolRun = { ...baseRun, status: "running" };
    render(<ToolCard run={runningRun} />);
    expect(screen.getByTestId("tool-card")).toHaveAttribute("data-tool-status", "running");
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("渲染失败状态并展示真实错误", () => {
    const failedRun: ToolRun = {
      ...baseRun,
      status: "failed",
      summary: "命令执行失败",
      details: "Error: exit code 1: file not found",
    };
    render(<ToolCard run={failedRun} defaultExpanded />);
    expect(screen.getByTestId("tool-card")).toHaveAttribute("data-tool-status", "failed");
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(screen.getByText("Error: exit code 1: file not found")).toBeInTheDocument();
  });

  it("渲染已否决状态", () => {
    const deniedRun: ToolRun = { ...baseRun, status: "denied" };
    render(<ToolCard run={deniedRun} />);
    expect(screen.getByTestId("tool-card")).toHaveAttribute("data-tool-status", "denied");
    expect(screen.getByText("已否决")).toBeInTheDocument();
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
