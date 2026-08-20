import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DelegationCard } from "../DelegationCard";

describe("DelegationCard", () => {
  afterEach(() => {
    cleanup();
  });
  it("渲染运行中委派卡片", () => {
    render(
      <DelegationCard
        fromName="白厄"
        summary="分析项目架构并整理目录"
        status="running"
      />,
    );

    expect(screen.getByTestId("delegation-card")).toHaveAttribute("data-delegation-status", "running");
    expect(screen.getByText("来自 白厄 的委派")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("分析项目架构并整理目录")).toBeInTheDocument();
  });

  it("渲染失败态并如实呈现错误", () => {
    render(
      <DelegationCard
        fromName="卡芙卡"
        summary="下载依赖并编译"
        status="failed"
        error="Network timeout: connect to server failed"
      />,
    );

    expect(screen.getByTestId("delegation-card")).toHaveAttribute("data-delegation-status", "failed");
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(screen.getByText("Network timeout: connect to server failed")).toBeInTheDocument();
  });

  it("渲染已完成态与已取消态", () => {
    const { rerender } = render(
      <DelegationCard summary="任务一" status="completed" />,
    );
    expect(screen.getByText("已完成")).toBeInTheDocument();

    rerender(<DelegationCard summary="任务二" status="cancelled" />);
    expect(screen.getByText("已取消")).toBeInTheDocument();
  });
});
