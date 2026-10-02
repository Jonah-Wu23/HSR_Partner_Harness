import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PowerStatusPayload } from "../../contracts/protocol";
import { createActionController } from "../../services/actions";
import { MockDesktopBackend } from "../../services/mockDesktopBackend";
import { desktopStore } from "../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../test/fakeBackend";
import { PowerPrompt } from "./PowerPrompt";

afterEach(() => {
  cleanup();
  desktopStore.setState(desktopStore.getInitialState(), true);
});

/** Windows 上远程服务开启、AC 睡眠超时低于阈值时 power.get_status 的结果。 */
function powerPayload(overrides: Partial<PowerStatusPayload> = {}): PowerStatusPayload {
  return {
    supported: true,
    platform: "win32",
    plan_name: "平衡",
    ac_sleep_timeout_seconds: 600,
    dc_sleep_timeout_seconds: 0,
    remote_serve_enabled: true,
    threshold_seconds: 900,
    at_risk: true,
    reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
    checked_at: "2026-09-02T10:00:00+08:00",
    warnings: [],
    ...overrides,
  };
}

const NO_RISK: Partial<PowerStatusPayload> = {
  ac_sleep_timeout_seconds: 1800,
  at_risk: false,
  reason: "AC/DC 睡眠超时均不低于阈值",
};

/** power.get_status 按给定结果应答，其他命令直接失败。 */
function respondingWith(payload: PowerStatusPayload) {
  return fakeBackend((command) =>
    command.method === "power.get_status" ? payload : unexpectedCommand(command),
  );
}

/** 与 AppController 一致：后端事件转进 store，再拉启动快照。 */
async function connectMockBackend() {
  const backend = new MockDesktopBackend("single-project");
  const controller = createActionController(backend);
  backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
  await controller.loadBootstrap();
  return { backend, actions: controller.actions };
}

describe("PowerPrompt", () => {
  it("挂载时查询到休眠风险即出现提示，展示判定原文、AC/DC 睡眠超时与阈值", async () => {
    const { backend, commands } = respondingWith(powerPayload());
    render(<PowerPrompt actions={createActionController(backend).actions} />);

    const prompt = await screen.findByTestId("power-prompt");
    expect(commands.map(({ method, params }) => ({ method, params }))).toEqual([
      { method: "power.get_status", params: {} },
    ]);
    expect(prompt).toHaveTextContent("AC 睡眠超时 600 秒低于阈值 900 秒");
    expect(prompt).toHaveTextContent("600 秒（10 分钟）");
    expect(prompt).toHaveTextContent("从不");
    expect(prompt).toHaveTextContent("900 秒");
  });

  it.each([
    [
      "平台不支持电源检测",
      powerPayload({
        supported: false,
        platform: "linux",
        plan_name: "",
        ac_sleep_timeout_seconds: null,
        dc_sleep_timeout_seconds: null,
        at_risk: false,
        reason: "当前平台不支持电源状态检测",
      }),
    ],
    ["远程服务未开启", powerPayload({ remote_serve_enabled: false, at_risk: false, reason: "远程服务未开启" })],
    ["睡眠超时不低于阈值", powerPayload(NO_RISK)],
  ])("%s时不出现提示", async (_situation, payload) => {
    const { backend } = respondingWith(payload);
    render(<PowerPrompt actions={createActionController(backend).actions} />);

    await waitFor(() => expect(desktopStore.getState().powerStatus).toEqual(payload));
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();
  });

  it("power.status_changed 进入休眠风险时出现提示，风险解除后消失", async () => {
    const { backend, actions } = await connectMockBackend();
    render(<PowerPrompt actions={actions} />);
    // Mock 的 power.get_status 结果为远程服务未开启、无风险
    await waitFor(() => expect(desktopStore.getState().powerStatus).not.toBeNull());
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();

    act(() => backend.emitPowerStatusChanged(powerPayload()));
    expect(screen.getByTestId("power-prompt")).toBeInTheDocument();

    act(() => backend.emitPowerStatusChanged(powerPayload(NO_RISK)));
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();
  });

  it("关闭后同一段风险期内的后续事件不再弹出，风险解除后再次进入风险时重新出现", async () => {
    const { backend, actions } = await connectMockBackend();
    render(<PowerPrompt actions={actions} />);
    await waitFor(() => expect(desktopStore.getState().powerStatus).not.toBeNull());

    act(() => backend.emitPowerStatusChanged(powerPayload()));
    fireEvent.click(screen.getByRole("button", { name: "关闭电源提示" }));
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();

    // AC 睡眠超时再调短，仍在同一段风险期内
    act(() =>
      backend.emitPowerStatusChanged(
        powerPayload({ ac_sleep_timeout_seconds: 300, reason: "AC 睡眠超时 300 秒低于阈值 900 秒" }),
      ),
    );
    expect(screen.queryByTestId("power-prompt")).not.toBeInTheDocument();

    act(() => backend.emitPowerStatusChanged(powerPayload(NO_RISK)));
    act(() => backend.emitPowerStatusChanged(powerPayload()));
    expect(screen.getByTestId("power-prompt")).toBeInTheDocument();
  });
});
