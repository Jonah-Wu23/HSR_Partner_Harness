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
    warnings: [],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("PowerStatusBanner 组件", () => {
  it.each([
    { condition: "尚未取得电源状态", status: null },
    {
      condition: "平台不支持电源检测",
      status: buildStatus({
        supported: false,
        platform: "darwin",
        plan_name: "",
        ac_sleep_timeout_seconds: null,
        dc_sleep_timeout_seconds: null,
        reason: "unsupported platform",
      }),
    },
    { condition: "远程服务已开启且没有休眠风险", status: buildStatus() },
  ])("$condition 时不渲染", ({ status }) => {
    const { container } = render(<PowerStatusBanner status={status} />);
    expect(container.firstChild).toBeNull();
  });

  it("有休眠风险时显示「电脑可能休眠」与 reason 原文", () => {
    render(
      <PowerStatusBanner
        status={buildStatus({
          at_risk: true,
          reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
        })}
      />,
    );
    expect(screen.getByTestId("power-status-title")).toHaveTextContent("电脑可能休眠");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent(
      "AC 睡眠超时 600 秒低于阈值 900 秒",
    );
  });

  it("有休眠风险时展示电源计划与 AC/DC 睡眠超时，0 秒显示为「从不」", () => {
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

  it("有休眠风险时「知道了」回调 onDismiss，不传回调时不显示该按钮", () => {
    const onDismiss = vi.fn();
    const { rerender } = render(
      <PowerStatusBanner status={buildStatus({ at_risk: true })} onDismiss={onDismiss} />,
    );
    fireEvent.click(screen.getByTestId("btn-power-dismiss"));
    expect(onDismiss).toHaveBeenCalledTimes(1);

    rerender(<PowerStatusBanner status={buildStatus({ at_risk: true })} />);
    expect(screen.queryByTestId("btn-power-dismiss")).toBeNull();
  });

  it("远程服务未开启且没有休眠风险时只展示 reason 原文，不显示休眠警示", () => {
    render(
      <PowerStatusBanner
        status={buildStatus({
          at_risk: false,
          remote_serve_enabled: false,
          reason: "远程服务未开启",
        })}
      />,
    );
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent("远程服务未开启");
    expect(screen.queryByTestId("power-status-title")).toBeNull();
  });
});
