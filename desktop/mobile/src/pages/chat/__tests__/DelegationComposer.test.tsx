import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DelegationComposer } from "../DelegationComposer";

describe("DelegationComposer", () => {
  afterEach(() => {
    cleanup();
  });
  it("输入文本并点击「交给助手」成功提交", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<DelegationComposer onSubmit={onSubmit} />);

    const textarea = screen.getByTestId("delegation-input");
    const submitBtn = screen.getByTestId("delegation-submit-btn");

    expect(submitBtn).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "把所有测试跑一遍" } });
    expect(submitBtn).not.toBeDisabled();

    fireEvent.click(submitBtn);
    expect(onSubmit).toHaveBeenCalledWith("把所有测试跑一遍");

    await waitFor(() => {
      expect(textarea).toHaveValue("");
    });
  });

  it("委派提交失败时如实展示真实错误", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("Sidecar 远程连接中断"));
    render(<DelegationComposer onSubmit={onSubmit} />);

    const textarea = screen.getByTestId("delegation-input");
    const submitBtn = screen.getByTestId("delegation-submit-btn");

    fireEvent.change(textarea, { target: { value: "重新构建项目" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId("delegation-error")).toBeInTheDocument();
      expect(screen.getByText("委派失败：Sidecar 远程连接中断")).toBeInTheDocument();
    });

    // 点击关闭错误提示
    const closeBtn = screen.getByRole("button", { name: "关闭错误提示" });
    fireEvent.click(closeBtn);
    expect(screen.queryByTestId("delegation-error")).not.toBeInTheDocument();
  });
});
