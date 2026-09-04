import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  PowerStatusBanner,
  type PowerStatusPayload,
} from "../PowerStatusBanner";

function buildStatus(overrides: Partial<PowerStatusPayload> = {}): PowerStatusPayload {
  return {
    supported: true,
    platform: "windows",
    plan_name: "平衡",
    ac_sleep_timeout_seconds: 600,
    dc_sleep_timeout_seconds: 1800,
    remote_serve_enabled: true,
    threshold_seconds: 900,
    at_risk: false,
    reason: "AC/DC 睡眠超时均不低于阈值",
    checked_at: "2026-09-02T10:00:00",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("PowerStatusBanner 组件", () => {
  it("status 为空时不渲染", () => {
    const { container } = render(<PowerStatusBanner status={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("supported=false（不支持的平台）时不渲染", () => {
    const { container } = render(
      <PowerStatusBanner
        status={buildStatus({
          supported: false,
          platform: "darwin",
          plan_name: "",
          ac_sleep_timeout_seconds: null,
          dc_sleep_timeout_seconds: null,
          at_risk: false,
          reason: "unsupported platform",
        })}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("at_risk=true 时呈现「电脑可能休眠」与 reason 原文", () => {
    render(
      <PowerStatusBanner
        status={buildStatus({
          at_risk: true,
          reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
        })}
      />,
    );
    expect(screen.getByTestId("power-status-banner")).toHaveClass("is-at-risk");
    expect(screen.getByTestId("power-status-title")).toHaveTextContent("电脑可能休眠");
    // reason 原文原样展示，不改写不摘要
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent(
      "AC 睡眠超时 600 秒低于阈值 900 秒",
    );
  });

  it("at_risk=true 时展示电源计划与 AC/DC 超时秒数，0 秒呈现为「从不」", () => {
    render(
      <PowerStatusBanner
        status={buildStatus({
          at_risk: true,
          plan_name: "高性能",
          ac_sleep_timeout_seconds: 600,
          dc_sleep_timeout_seconds: 0,
          reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
        })}
      />,
    );
    const detail = screen.getByTestId("power-status-detail");
    expect(detail).toHaveTextContent("高性能");
    expect(detail).toHaveTextContent("600 秒");
    expect(detail).toHaveTextContent("从不");
  });

  it("at_risk=true 且提供 onDismiss 时渲染「知道了」并回调", () => {
    const onDismiss = vi.fn();
    render(
      <PowerStatusBanner
        status={buildStatus({ at_risk: true })}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByTestId("btn-power-dismiss"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("at_risk=true 且未提供 onDismiss 时不渲染关闭按钮", () => {
    render(<PowerStatusBanner status={buildStatus({ at_risk: true })} />);
    expect(screen.queryByTestId("btn-power-dismiss")).toBeNull();
  });

  it("remote_serve_enabled=false 且无风险时按 reason 原文弱化呈现", () => {
    render(
      <PowerStatusBanner
        status={buildStatus({
          at_risk: false,
          remote_serve_enabled: false,
          reason: "远程服务未开启",
        })}
      />,
    );
    const banner = screen.getByTestId("power-status-banner");
    expect(banner).toHaveClass("is-muted");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent(
      "远程服务未开启",
    );
    // 弱化态不冒充休眠风险
    expect(screen.queryByTestId("power-status-title")).toBeNull();
  });

  it("正常态（远程服务开启且无风险）收敛不渲染", () => {
    const { container } = render(
      <PowerStatusBanner status={buildStatus({ at_risk: false, remote_serve_enabled: true })} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
