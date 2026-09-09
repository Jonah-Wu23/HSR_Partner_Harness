import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConnectionDetails } from "../ConnectionDetails";
import { useMobileStore } from "../../../lib/mobileStore";

describe("ConnectionDetails 组件", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useMobileStore.setState({
      connection: "connected",
      deviceName: "我的手机",
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("默认处于收起状态，不渲染内部面板", () => {
    render(<ConnectionDetails />);
    const toggle = screen.getByTestId("btn-toggle-connection-details");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent("展开");
    expect(screen.queryByTestId("lease-status-panel")).toBeNull();
    expect(screen.queryByTestId("device-list-panel")).toBeNull();
  });

  it("点击后展开，展示连接状态、租约面板与设备面板，再次点击收起", () => {
    render(<ConnectionDetails />);
    const toggle = screen.getByTestId("btn-toggle-connection-details");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent("收起");

    expect(screen.getByTestId("connection-state-line")).toHaveTextContent("连接状态：已连接");
    expect(screen.getByTestId("lease-status-panel")).toBeInTheDocument();
    expect(screen.getByTestId("device-list-panel")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("lease-status-panel")).toBeNull();
  });
});
