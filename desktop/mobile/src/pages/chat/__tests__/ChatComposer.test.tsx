import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  ChatComposer,
  COMPOSER_MAX_TEXTAREA_HEIGHT_PX,
  computeTextareaHeight,
} from "../ChatComposer";

afterEach(cleanup);

describe("ChatComposer 聊天输入区", () => {
  it.each([
    { target: "character", placeholder: "发送消息给角色…", submit: "发送" },
    { target: "assistant", placeholder: "输入任务交给助手执行…", submit: "交给助手" },
  ] as const)("目标 $target 的占位与提交按钮文案", ({ target, placeholder, submit }) => {
    render(<ChatComposer target={target} onSubmit={vi.fn()} />);
    expect(screen.getByTestId("chat-input")).toHaveAttribute("placeholder", placeholder);
    expect(screen.getByTestId("chat-submit-btn")).toHaveTextContent(submit);
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

  // 未布局时 scrollHeight 为 0，不写高度，避免把输入框压成 0px。
  it.each([
    { case: "未布局", scrollHeight: 0, maxHeight: undefined, expected: null },
    { case: "测量值无效", scrollHeight: Number.NaN, maxHeight: undefined, expected: null },
    { case: "未超过默认上限", scrollHeight: 96, maxHeight: undefined, expected: 96 },
    {
      case: "超过默认上限",
      scrollHeight: 300,
      maxHeight: undefined,
      expected: COMPOSER_MAX_TEXTAREA_HEIGHT_PX,
    },
    { case: "超过传入上限", scrollHeight: 300, maxHeight: 240, expected: 240 },
  ])("自增高：$case", ({ scrollHeight, maxHeight, expected }) => {
    expect(computeTextareaHeight(scrollHeight, maxHeight)).toBe(expected);
  });

  it("禁用时不提交并展示禁用说明", () => {
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
