import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DemoModeNotice } from "../DemoModeNotice";
import { desktopStore } from "../../../stores/desktopStore";

afterEach(() => {
  cleanup();
  desktopStore.setState({ backendInfo: null });
});

describe("DemoModeNotice（V039-S4-002 演示模式标识）", () => {
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

  it("自报 demo=false（真实模式）时不常驻标识", () => {
    desktopStore.setState({ backendInfo: { pid: 4321, demo: false, modeSource: "default" } });
    render(<DemoModeNotice />);
    expect(screen.queryByTestId("demo-mode-badge")).not.toBeInTheDocument();
  });

  it("未上报运行模式（null）不冒充真实模式、也不冒充演示", () => {
    desktopStore.setState({ backendInfo: null });
    render(<DemoModeNotice />);
    expect(screen.queryByTestId("demo-mode-badge")).not.toBeInTheDocument();

    // 只上报 PID、没上报 demo 时同样不下结论
    desktopStore.setState({ backendInfo: { pid: 99, demo: null, modeSource: null } });
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
