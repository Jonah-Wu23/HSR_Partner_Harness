import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ErrorBoundary } from "../ErrorBoundary";

function Boom(): never {
  throw new Error("渲染期原始错误");
}

describe("ErrorBoundary 组件", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("无异常时原样渲染子树", () => {
    render(
      <ErrorBoundary>
        <div>正常内容</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("正常内容")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("渲染期异常被捕获：呈现原始错误与重载入口，原始错误进 console", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("页面出错了");
    expect(alert).toHaveTextContent("渲染期原始错误");
    expect(screen.getByRole("button", { name: "重新加载" })).toBeTruthy();
    const logged = errorSpy.mock.calls
      .map((args) => String(args[0]))
      .join("\n");
    expect(logged).toContain("[ErrorBoundary]");
  });

  it("重载按钮点击走 location.reload（不清 localStorage）", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const reloadSpy = vi.fn();
    // jsdom 的 location.reload 不可 redefine，用 stubGlobal 替换全局 location。
    vi.stubGlobal("location", { reload: reloadSpy });
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(reloadSpy).toHaveBeenCalledTimes(1);
    expect(errorSpy).toHaveBeenCalled();
  });
});
