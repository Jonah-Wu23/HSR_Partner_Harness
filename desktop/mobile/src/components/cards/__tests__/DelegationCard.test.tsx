import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DelegationCard } from "../DelegationCard";

describe("DelegationCard", () => {
  afterEach(() => {
    cleanup();
  });
  it("展示委派来源与任务内容", () => {
    render(<DelegationCard fromName="白厄" summary="分析项目架构并整理目录" status="running" />);

    expect(screen.getByText("来自 白厄 的委派")).toBeInTheDocument();
    expect(screen.getByText("分析项目架构并整理目录")).toBeInTheDocument();
  });

  it.each([
    { status: "running", label: "运行中" },
    { status: "completed", label: "已完成" },
    { status: "failed", label: "失败" },
    { status: "cancelled", label: "已取消" },
  ] as const)("$status 状态显示「$label」", ({ status, label }) => {
    render(<DelegationCard summary="下载依赖并编译" status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("失败时展示错误原文", () => {
    render(
      <DelegationCard
        summary="下载依赖并编译"
        status="failed"
        error="Network timeout: connect to server failed"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Network timeout: connect to server failed");
  });
});
