import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatComposer } from "../ChatComposer";

afterEach(cleanup);

describe("ChatComposer (V0.3.4 手机端聊天输入区)", () => {
  it("target=character：占位与提交文案面向角色消息", () => {
    render(<ChatComposer target="character" onSubmit={vi.fn()} />);
    expect(screen.getByTestId("chat-input")).toHaveAttribute(
      "placeholder",
      "发送消息给角色…",
    );
    expect(screen.getByTestId("chat-submit-btn")).toHaveTextContent("发送");
  });

  it("target=assistant：占位与提交文案面向委派", () => {
    render(<ChatComposer target="assistant" onSubmit={vi.fn()} />);
    expect(screen.getByTestId("chat-input")).toHaveAttribute(
      "placeholder",
      "输入任务交给助手执行…",
    );
    expect(screen.getByTestId("chat-submit-btn")).toHaveTextContent("交给助手");
  });

  it("提交非空文本并清空输入；空文本不提交", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ChatComposer target="character" onSubmit={onSubmit} />);

    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "  在吗  " } });
    fireEvent.click(screen.getByTestId("chat-submit-btn"));
    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith("在吗");
    });
    await waitFor(() => {
      expect(input).toHaveValue("");
    });

    fireEvent.click(screen.getByTestId("chat-submit-btn"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("Let It Fail：提交失败如实展示错误并保留输入", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("服务不可用"));
    render(<ChatComposer target="assistant" onSubmit={onSubmit} />);

    const input = screen.getByTestId("chat-input");
    fireEvent.change(input, { target: { value: "启动构建" } });
    fireEvent.click(screen.getByTestId("chat-submit-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("chat-composer-error")).toHaveTextContent(
        "委派失败：服务不可用",
      );
    });
    expect(input).toHaveValue("启动构建");
  });

  it("前置禁用：disabled 时不提交并展示禁用说明", () => {
    const onSubmit = vi.fn();
    render(
      <ChatComposer
        target="assistant"
        onSubmit={onSubmit}
        disabled
        disabledHint="对话模式下助手不接收委派，请先切换到协作模式。"
      />,
    );

    expect(screen.getByTestId("chat-input")).toBeDisabled();
    expect(screen.getByTestId("chat-submit-btn")).toBeDisabled();
    expect(screen.getByTestId("chat-composer-hint")).toHaveTextContent(
      "对话模式下助手不接收委派",
    );

    fireEvent.submit(screen.getByTestId("chat-composer").querySelector("form")!);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
