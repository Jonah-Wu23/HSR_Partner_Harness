import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopEvent, PowerStatusPayload } from "../../contracts/protocol";
import type { HarnessActions } from "../../contracts/actions";
import { desktopStore } from "../../stores/desktopStore";
import { PowerStatusSection } from "./PowerStatusSection";

afterEach(cleanup);

function powerPayload(overrides: Partial<PowerStatusPayload> = {}): PowerStatusPayload {
  return {
    supported: true,
    platform: "windows",
    plan_name: "平衡",
    ac_sleep_timeout_seconds: 1800,
    dc_sleep_timeout_seconds: 1200,
    remote_serve_enabled: true,
    threshold_seconds: 900,
    at_risk: false,
    reason: "AC/DC 睡眠超时均不低于阈值",
    checked_at: "2026-09-02T10:00:00+08:00",
    ...overrides,
  };
}

function powerEvent(sequence: number, payload: PowerStatusPayload): DesktopEvent {
  return {
    kind: "event",
    event: "power.status_changed",
    sequence,
    // 线缆载荷为无类型 JSON；运行时形状由 powerPayload 按契约 §1.5 保证。
    payload: payload as unknown as Record<string, unknown>,
  };
}

function actionsWith(powerGetStatus: HarnessActions["powerGetStatus"]): HarnessActions {
  return { powerGetStatus } as unknown as HarnessActions;
}

describe("PowerStatusSection（V0.3.7 设置页远程管理区）", () => {
  beforeEach(() => {
    desktopStore.setState({
      // status 停在初始 booting 会把业务事件暂存进 eventBuffer；事件路径测试需要 ready。
      status: "ready",
      powerStatus: null,
      powerError: null,
      powerQueryInFlight: false,
      powerPromptDismissed: false,
      lastSequence: -1,
      needsBootstrap: false,
      eventBuffer: [],
      streamId: null,
    });
  });

  it("挂载时主动查询并常驻展示电源计划/超时/阈值/远程服务", async () => {
    const powerGetStatus = vi.fn().mockResolvedValue(powerPayload());
    render(<PowerStatusSection actions={actionsWith(powerGetStatus)} />);

    const facts = await screen.findByTestId("power-status-facts");
    expect(powerGetStatus).toHaveBeenCalledOnce();
    expect(facts).toHaveTextContent("平衡");
    expect(facts).toHaveTextContent("1800 秒（30 分钟）");
    expect(facts).toHaveTextContent("1200 秒（20 分钟）");
    expect(facts).toHaveTextContent("900 秒");
    expect(facts).toHaveTextContent("已开启");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent(
      "AC/DC 睡眠超时均不低于阈值",
    );
  });

  it("查询失败如实显示错误原文，不伪造状态行", async () => {
    const powerGetStatus = vi
      .fn()
      .mockRejectedValue(new Error("power_status_unavailable: powercfg 退出码 1"));
    render(<PowerStatusSection actions={actionsWith(powerGetStatus)} />);

    const error = await screen.findByTestId("power-status-error");
    expect(error).toHaveTextContent("power_status_unavailable: powercfg 退出码 1");
    expect(error).toHaveAttribute("role", "alert");
    expect(screen.queryByTestId("power-status-facts")).not.toBeInTheDocument();
  });

  it("查询失败后事件成功到达：错误清除、状态行照常展示", async () => {
    const powerGetStatus = vi.fn().mockRejectedValue(new Error("power_status_unavailable"));
    render(<PowerStatusSection actions={actionsWith(powerGetStatus)} />);
    await screen.findByTestId("power-status-error");

    act(() => {
      desktopStore.getState().applyEvents([powerEvent(1, powerPayload())]);
    });

    await waitFor(() => expect(desktopStore.getState().powerError).toBeNull());
    expect(screen.queryByTestId("power-status-error")).not.toBeInTheDocument();
    expect(screen.getByTestId("power-status-facts")).toHaveTextContent("平衡");
  });

  it("power.status_changed 事件更新数据（AC 超时被调短后如实变化）", async () => {
    const powerGetStatus = vi.fn().mockResolvedValue(powerPayload());
    render(<PowerStatusSection actions={actionsWith(powerGetStatus)} />);
    await screen.findByTestId("power-status-facts");

    act(() => {
      desktopStore.getState().applyEvents([
        powerEvent(
          1,
          powerPayload({
            ac_sleep_timeout_seconds: 600,
            at_risk: true,
            reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
          }),
        ),
      ]);
    });

    const facts = screen.getByTestId("power-status-facts");
    expect(facts).toHaveTextContent("600 秒（10 分钟）");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent("存在休眠风险");
  });

  it("非 Windows 平台如实展示不支持原因", async () => {
    const powerGetStatus = vi.fn().mockResolvedValue(
      powerPayload({
        supported: false,
        platform: "linux",
        plan_name: "",
        ac_sleep_timeout_seconds: null,
        dc_sleep_timeout_seconds: null,
        reason: "unsupported platform",
      }),
    );
    render(<PowerStatusSection actions={actionsWith(powerGetStatus)} />);

    const unsupported = await screen.findByTestId("power-status-unsupported");
    expect(unsupported).toHaveTextContent("unsupported platform");
    expect(unsupported).toHaveTextContent("linux");
    expect(screen.queryByTestId("power-status-facts")).not.toBeInTheDocument();
  });
});
