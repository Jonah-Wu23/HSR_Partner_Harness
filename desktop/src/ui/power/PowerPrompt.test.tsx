import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DesktopEvent, PowerStatusPayload } from "../../contracts/protocol";
import type { HarnessActions } from "../../contracts/actions";
import { desktopStore } from "../../stores/desktopStore";
import { PowerPrompt } from "./PowerPrompt";

afterEach(cleanup);

function powerPayload(overrides: Partial<PowerStatusPayload> = {}): PowerStatusPayload {
  return {
    supported: true,
    platform: "windows",
    plan_name: "平衡",
    ac_sleep_timeout_seconds: 600,
    dc_sleep_timeout_seconds: 0,
    remote_serve_enabled: true,
    threshold_seconds: 900,
    at_risk: true,
    reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
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

describe("PowerPrompt（V0.3.7 V10）", () => {
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

  it("at_risk 时挂载主动查询并出现提示：展示 reason 原文与 AC/DC 超时秒数", async () => {
    const powerGetStatus = vi.fn().mockResolvedValue(powerPayload());
    render(<PowerPrompt actions={actionsWith(powerGetStatus)} />);

    const prompt = await screen.findByTestId("power-prompt");
    expect(powerGetStatus).toHaveBeenCalledOnce();
    expect(prompt).toHaveTextContent("AC 睡眠超时 600 秒低于阈值 900 秒");
    expect(prompt).toHaveTextContent("600 秒（10 分钟）");
    expect(prompt).toHaveTextContent("从不");
    expect(prompt).toHaveTextContent("900 秒");
    // 保持唤醒指引明确应用不代改电源设置
    expect(prompt).toHaveTextContent("不会代你修改电源设置");
  });

  it("supported=false、远程服务未开启、非风险状态均不出现提示", async () => {
    const powerGetStatus = vi.fn().mockResolvedValue(
      powerPayload({ supported: false, platform: "linux", at_risk: false, reason: "unsupported platform" }),
    );
    const { unmount } = render(<PowerPrompt actions={actionsWith(powerGetStatus)} />);
    await waitFor(() => expect(desktopStore.getState().powerStatus?.supported).toBe(false));
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();
    unmount();

    desktopStore.setState({ powerStatus: null, powerError: null });
    const serveOff = vi.fn().mockResolvedValue(powerPayload({ remote_serve_enabled: false }));
    render(<PowerPrompt actions={actionsWith(serveOff)} />);
    await waitFor(() => expect(desktopStore.getState().powerStatus?.remote_serve_enabled).toBe(false));
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();
    unmount();

    desktopStore.setState({ powerStatus: null, powerError: null });
    const noRisk = vi.fn().mockResolvedValue(
      powerPayload({ at_risk: false, reason: "AC/DC 睡眠超时均不低于阈值" }),
    );
    render(<PowerPrompt actions={actionsWith(noRisk)} />);
    await waitFor(() => expect(desktopStore.getState().powerStatus?.at_risk).toBe(false));
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();
  });

  it("power.status_changed 事件到达时更新：正常→风险出现，风险→正常消失", async () => {
    const powerGetStatus = vi.fn().mockResolvedValue(
      powerPayload({ at_risk: false, reason: "AC/DC 睡眠超时均不低于阈值" }),
    );
    render(<PowerPrompt actions={actionsWith(powerGetStatus)} />);
    await waitFor(() => expect(desktopStore.getState().powerStatus).not.toBeNull());
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();

    act(() => {
      desktopStore.getState().applyEvents([powerEvent(1, powerPayload())]);
    });
    expect(screen.getByTestId("power-prompt")).toBeInTheDocument();

    act(() => {
      desktopStore
        .getState()
        .applyEvents([powerEvent(2, powerPayload({ at_risk: false, reason: "AC/DC 睡眠超时均不低于阈值" }))]);
    });
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();
  });

  it("关闭后本次 at_risk 持续期内不再出现，状态消失再出现时重新允许", async () => {
    const powerGetStatus = vi.fn().mockResolvedValue(powerPayload());
    render(<PowerPrompt actions={actionsWith(powerGetStatus)} />);
    await screen.findByTestId("power-prompt");

    fireEvent.click(screen.getByRole("button", { name: "关闭电源提示" }));
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();

    // 同一次 at_risk 持续期内的轮询事件不重新弹出
    act(() => {
      desktopStore.getState().applyEvents([
        powerEvent(1, powerPayload({ checked_at: "2026-09-02T10:01:00+08:00" })),
      ]);
    });
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();

    // 状态消失（调回睡眠超时或 serve 停止终态）→ 复位关闭标记
    act(() => {
      desktopStore.getState().applyEvents([
        powerEvent(2, powerPayload({ at_risk: false, reason: "AC/DC 睡眠超时均不低于阈值" })),
      ]);
    });
    expect(desktopStore.getState().powerPromptDismissed).toBe(false);

    // 状态再次出现 → 提示重新允许出现
    act(() => {
      desktopStore.getState().applyEvents([powerEvent(3, powerPayload())]);
    });
    expect(screen.getByTestId("power-prompt")).toBeInTheDocument();
  });

  it("查询失败（power_status_unavailable）不显示提示，错误如实落入 store", async () => {
    const powerGetStatus = vi
      .fn()
      .mockRejectedValue(new Error("power_status_unavailable: powercfg 输出不可解析"));
    render(<PowerPrompt actions={actionsWith(powerGetStatus)} />);

    await waitFor(() =>
      expect(desktopStore.getState().powerError).toBe(
        "power_status_unavailable: powercfg 输出不可解析",
      ),
    );
    expect(desktopStore.getState().powerStatus).toBeNull();
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();
  });
});
