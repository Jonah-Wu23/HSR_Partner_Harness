import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DemoModeNotice } from "../DemoModeNotice";
import { desktopStore } from "../../../stores/desktopStore";

afterEach(() => {
  cleanup();
  desktopStore.setState({ backendInfo: null });
});

describe("DemoModeNotice 演示模式标识", () => {
  it("Sidecar 自报 demo=true 时如实标注演示模式", () => {
    desktopStore.setState({ backendInfo: { pid: 4321, demo: true, modeSource: "flag" } });
    render(<DemoModeNotice />);

    const badge = screen.getByTestId("demo-mode-badge");
    expect(badge).toHaveTextContent("演示模式：未调用真实模型");
    // 技术细节（模式来源与 PID）随标识可查，但结论由 Sidecar 自报
    expect(badge).toHaveAttribute(
      "aria-label",
      "Sidecar 自报运行在演示模式（模式来源：flag），PID 4321：不会调用真实模型。",
    );
  });

  it.each([
    ["自报真实模式", { pid: 4321, demo: false, modeSource: "default" }],
    ["只上报 PID 未上报模式", { pid: 99, demo: null, modeSource: null }],
    ["尚未收到运行模式", null],
  ] as const)("%s时不显示标识", (_case, backendInfo) => {
    desktopStore.setState({ backendInfo });
    render(<DemoModeNotice />);
    expect(screen.queryByTestId("demo-mode-badge")).not.toBeInTheDocument();
  });

  it("detail 变体在技术详情里给出运行模式一行", () => {
    desktopStore.setState({ backendInfo: { pid: 7, demo: true, modeSource: "env" } });
    render(<DemoModeNotice variant="detail" />);

    const row = screen.getByTestId("demo-mode-detail");
    expect(row).toHaveTextContent("运行模式");
    expect(row).toHaveTextContent("演示模式（模式来源：env）");
  });
});
