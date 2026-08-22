import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ReasoningRibbon } from "../ReasoningRibbon";

describe("ReasoningRibbon", () => {
  afterEach(() => {
    cleanup();
  });
  it("默认折叠，显示耗时摘要与「展开」入口", () => {
    render(
      <ReasoningRibbon
        text="首先分析用户的问题，检查代码仓库结构..."
        elapsedSeconds={4}
      />,
    );

    const ribbon = screen.getByTestId("reasoning-ribbon");
    expect(ribbon).toHaveAttribute("data-expanded", "false");
    expect(screen.getByText("思考了 4 秒")).toBeInTheDocument();
    expect(screen.getByText("展开")).toBeInTheDocument();
    expect(screen.queryByText("首先分析用户的问题，检查代码仓库结构...")).not.toBeInTheDocument();
  });

  it("点击展开后展示思考正文，再次点击收起", () => {
    render(
      <ReasoningRibbon
        text="正在推演函数调用链..."
        elapsedSeconds={2}
      />,
    );

    const toggleBtn = screen.getByRole("button");
    // 点击展开
    fireEvent.click(toggleBtn);
    expect(screen.getByTestId("reasoning-ribbon")).toHaveAttribute("data-expanded", "true");
    expect(screen.getByText("正在推演函数调用链...")).toBeInTheDocument();
    expect(screen.getByText("收起")).toBeInTheDocument();

    // 点击收起
    fireEvent.click(toggleBtn);
    expect(screen.getByTestId("reasoning-ribbon")).toHaveAttribute("data-expanded", "false");
    expect(screen.queryByText("正在推演函数调用链...")).not.toBeInTheDocument();
  });

  it("流式进行中展示「正在思考…」并直接展开", () => {
    render(
      <ReasoningRibbon
        text="模型正在逐步生成思维链..."
        streaming
      />,
    );

    expect(screen.getByTestId("reasoning-ribbon")).toHaveAttribute("data-expanded", "true");
    expect(screen.getByText("正在思考…")).toBeInTheDocument();
    expect(screen.getByText("模型正在逐步生成思维链...")).toBeInTheDocument();
  });

  it("无文本且非流式时不渲染", () => {
    const { container } = render(<ReasoningRibbon text="" streaming={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
