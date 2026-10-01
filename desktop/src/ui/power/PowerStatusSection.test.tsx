import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PowerStatusPayload } from "../../contracts/protocol";
import { createActionController } from "../../services/actions";
import { DesktopRequestError } from "../../services/backend";
import { MockDesktopBackend } from "../../services/mockDesktopBackend";
import { desktopStore } from "../../stores/desktopStore";
import { fakeBackend, unexpectedCommand } from "../../test/fakeBackend";
import { PowerStatusSection } from "./PowerStatusSection";

afterEach(() => {
  cleanup();
  desktopStore.setState(desktopStore.getInitialState(), true);
});

/** Windows 上远程服务开启时 power.get_status 的结果。 */
function powerPayload(overrides: Partial<PowerStatusPayload> = {}): PowerStatusPayload {
  return {
    supported: true,
    platform: "win32",
    plan_name: "平衡",
    ac_sleep_timeout_seconds: 1800,
    dc_sleep_timeout_seconds: 1200,
    remote_serve_enabled: true,
    threshold_seconds: 900,
    at_risk: false,
    reason: "AC/DC 睡眠超时均不低于阈值",
    checked_at: "2026-09-02T10:00:00+08:00",
    warnings: [],
    ...overrides,
  };
}

describe("PowerStatusSection", () => {
  it("挂载时查询电源状态并展示电源计划、AC/DC 睡眠超时、阈值、远程服务与判定", async () => {
    const backend = new MockDesktopBackend("single-project");
    render(<PowerStatusSection actions={createActionController(backend).actions} />);

    const facts = await screen.findByTestId("power-status-facts");
    expect(backend.recordedRequests.map(({ method, params }) => ({ method, params }))).toEqual([
      { method: "power.get_status", params: {} },
    ]);
    expect(facts).toHaveTextContent("平衡");
    expect(facts).toHaveTextContent("1800 秒（30 分钟）");
    expect(facts).toHaveTextContent("1200 秒（20 分钟）");
    expect(facts).toHaveTextContent("900 秒");
    expect(facts).toHaveTextContent("未开启");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent("判定：远程服务未开启");
  });

  it("查询失败时以 alert 显示 Sidecar 错误原文，不展示状态行", async () => {
    const { backend } = fakeBackend((command) => {
      if (command.method !== "power.get_status") return unexpectedCommand(command);
      throw new DesktopRequestError(
        "power_status_unavailable",
        "读取电源状态失败：PowerGetActiveScheme 失败（错误码 5）：拒绝访问。",
      );
    });
    render(<PowerStatusSection actions={createActionController(backend).actions} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "读取电源状态失败：PowerGetActiveScheme 失败（错误码 5）：拒绝访问。",
    );
    expect(screen.queryByTestId("power-status-facts")).not.toBeInTheDocument();
  });

  it("power.status_changed 到达后按新载荷更新状态行与风险判定", async () => {
    const backend = new MockDesktopBackend("single-project");
    const controller = createActionController(backend);
    // 与 AppController 一致：后端事件转进 store
    backend.subscribe((event) => desktopStore.getState().applyEvents([event]));
    await controller.loadBootstrap();
    render(<PowerStatusSection actions={controller.actions} />);
    await screen.findByTestId("power-status-facts");

    act(() =>
      backend.emitPowerStatusChanged(
        powerPayload({
          ac_sleep_timeout_seconds: 600,
          at_risk: true,
          reason: "AC 睡眠超时 600 秒低于阈值 900 秒",
        }),
      ),
    );

    const facts = screen.getByTestId("power-status-facts");
    expect(facts).toHaveTextContent("600 秒（10 分钟）");
    expect(facts).toHaveTextContent("已开启");
    expect(screen.getByTestId("power-status-reason")).toHaveTextContent(
      "存在休眠风险：AC 睡眠超时 600 秒低于阈值 900 秒",
    );
  });

  it("非 Windows 平台展示 Sidecar 给出的不支持原因与平台名，不展示状态行", async () => {
    const unsupported = powerPayload({
      supported: false,
      platform: "linux",
      plan_name: "",
      ac_sleep_timeout_seconds: null,
      dc_sleep_timeout_seconds: null,
      remote_serve_enabled: false,
      reason: "当前平台不支持电源状态检测",
    });
    const { backend } = fakeBackend((command) =>
      command.method === "power.get_status" ? unsupported : unexpectedCommand(command),
    );
    render(<PowerStatusSection actions={createActionController(backend).actions} />);

    expect(await screen.findByTestId("power-status-unsupported")).toHaveTextContent(
      "当前平台不支持电源状态检测（platform: linux）",
    );
    expect(screen.queryByTestId("power-status-facts")).not.toBeInTheDocument();
  });
});
