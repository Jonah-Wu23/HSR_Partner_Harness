import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DelegationCard } from "../workspace/DelegationCard";

afterEach(cleanup);

describe("DelegationCard", () => {
  it("标明委派来源与摘要，运行中带状态并可取消", () => {
    const onCancel = vi.fn();
    render(
      <DelegationCard
        delegation={{
          delegationId: "d1",
          fromName: "白厄",
          summary: "读取项目结构并说明这个项目是什么",
          status: "running",
        }}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByLabelText("来自白厄的委派")).toBeInTheDocument();
    expect(screen.getByText("读取项目结构并说明这个项目是什么")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /取消任务/ }));
    expect(onCancel).toHaveBeenCalledWith("d1");
  });

  it("完成态不显示取消按钮", () => {
    render(
      <DelegationCard
        delegation={{ delegationId: "d2", fromName: "白厄", summary: "跑测试", status: "completed" }}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /取消任务/ })).not.toBeInTheDocument();
  });
});
