import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConnectionBanner } from "../ConnectionBanner";
import { useMobileStore } from "../../lib/mobileStore";
import * as router from "../../lib/router";

describe("ConnectionBanner 组件", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("connected 态完全收起（返回 null）", () => {
    const { container } = render(<ConnectionBanner connection="connected" />);
    expect(container.firstChild).toBeNull();
  });

  it("connecting 态展示警示色且无操作按钮", () => {
    render(<ConnectionBanner connection="connecting" />);
    const banner = screen.getByTestId("connection-banner");
    expect(banner).toHaveClass("is-warn");
    expect(banner).toHaveTextContent("正在连接桌面端…");
    expect(screen.queryByTestId("btn-repair")).toBeNull();
    expect(screen.queryByTestId("btn-reconnect")).toBeNull();
  });

  it("reconnecting 态展示警示色且文案提示重连中", () => {
    render(<ConnectionBanner connection="reconnecting" />);
    const banner = screen.getByTestId("connection-banner");
    expect(banner).toHaveClass("is-warn");
    expect(banner).toHaveTextContent("与桌面端连接中断，正在重连…");
  });

  it("unreachable 态展示醒目红色并提供「重试」按钮，点击调用 store.reconnect", () => {
    const reconnectSpy = vi.spyOn(useMobileStore.getState(), "reconnect");
    render(<ConnectionBanner connection="unreachable" />);
    const banner = screen.getByTestId("connection-banner");
    expect(banner).toHaveClass("is-down");
    expect(banner).toHaveTextContent("无法连接到桌面端");

    const retryBtn = screen.getByTestId("btn-reconnect");
    expect(retryBtn).toHaveTextContent("重试");
    fireEvent.click(retryBtn);
    expect(reconnectSpy).toHaveBeenCalledTimes(1);
  });

  it("auth_failed 态「重新配对」先清本地凭据再跳转 pair 页", () => {
    const navigateSpy = vi.spyOn(router, "navigate");
    const disconnectSpy = vi.spyOn(useMobileStore.getState(), "disconnect");
    render(<ConnectionBanner connection="auth_failed" />);
    const banner = screen.getByTestId("connection-banner");
    expect(banner).toHaveClass("is-down");
    expect(banner).toHaveTextContent("配对已失效或设备已被撤销");

    const repairBtn = screen.getByTestId("btn-repair");
    expect(repairBtn).toHaveTextContent("重新配对");
    fireEvent.click(repairBtn);
    // 只 navigate 会被 App 路由守卫按 token 存在性弹回列表页，必须先 disconnect 清凭据
    expect(disconnectSpy).toHaveBeenCalledTimes(1);
    expect(navigateSpy).toHaveBeenCalledWith({ name: "pair" });
  });

  it("disconnected 态展示醒目红色并提供「重试」入口", () => {
    const reconnectSpy = vi.spyOn(useMobileStore.getState(), "reconnect");
    render(<ConnectionBanner connection="disconnected" />);
    const banner = screen.getByTestId("connection-banner");
    expect(banner).toHaveClass("is-down");
    expect(banner).toHaveTextContent("已断开与桌面端的连接");

    const retryBtn = screen.getByTestId("btn-reconnect");
    fireEvent.click(retryBtn);
    expect(reconnectSpy).toHaveBeenCalledTimes(1);
  });
});
