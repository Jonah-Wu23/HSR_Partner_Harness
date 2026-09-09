import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { LeaseStatusPanel } from "../LeaseStatusPanel";
import type { RemoteControlState } from "@shared/contracts/protocol";

describe("LeaseStatusPanel 组件", () => {
  afterEach(() => {
    cleanup();
  });

  it("lease 为 null 时如实显示「尚未取得控制权状态」（不伪造 free/held 状态）", () => {
    render(
      <LeaseStatusPanel
        lease={null}
        selfDeviceKey={null}
        controlLostAt={null}
      />,
    );
    expect(screen.getByTestId("lease-unknown")).toHaveTextContent(
      "尚未取得控制权状态：等待 remote_control 快照或 remote.control_changed 事件。",
    );
    expect(screen.queryByTestId("lease-state")).toBeNull();
    expect(screen.queryByTestId("lease-lost-hint")).toBeNull();
  });

  it("lease.state === 'free' 时显示空闲文案与占位横杠", () => {
    const lease: RemoteControlState = {
      state: "free",
      device_key: null,
      expires_at: null,
      grace_expires_at: null,
      reason: "released",
    };
    render(
      <LeaseStatusPanel
        lease={lease}
        selfDeviceKey="dev-123"
        controlLostAt={null}
      />,
    );
    const stateEl = screen.getByTestId("lease-state");
    expect(stateEl).toHaveTextContent("空闲：没有设备持有控制权");
    expect(stateEl).toHaveClass("lease-status-free");
    expect(screen.getByTestId("lease-device")).toHaveTextContent("—");
    expect(screen.getByTestId("lease-expires")).toHaveTextContent("未知");
    expect(screen.getByTestId("lease-reason")).toHaveTextContent("released");
    expect(screen.queryByTestId("lease-grace-expires")).toBeNull();
  });

  it("lease.state === 'held' 且 device_key 与 selfDeviceKey 相等时显示「本机」", () => {
    const lease: RemoteControlState = {
      state: "held",
      device_key: "dev-self-1",
      expires_at: "2026-09-09T18:00:00Z",
      grace_expires_at: null,
      reason: "claimed",
    };
    render(
      <LeaseStatusPanel
        lease={lease}
        selfDeviceKey="dev-self-1"
        controlLostAt={null}
      />,
    );
    const stateEl = screen.getByTestId("lease-state");
    expect(stateEl).toHaveTextContent("已由设备持有控制权");
    expect(stateEl).toHaveClass("lease-status-held");
    expect(screen.getByTestId("lease-device")).toHaveTextContent("本机");
    expect(screen.getByTestId("lease-expires")).not.toHaveTextContent("未知");
    expect(screen.queryByTestId("lease-self-unknown")).toBeNull();
  });

  it("selfDeviceKey 为 null 时展示对方 device_key 原文，并提示无法判断是否为本机", () => {
    const lease: RemoteControlState = {
      state: "held",
      device_key: "dev-remote-88",
      expires_at: "2026-09-09T18:00:00Z",
      grace_expires_at: null,
      reason: "claimed",
    };
    render(
      <LeaseStatusPanel
        lease={lease}
        selfDeviceKey={null}
        controlLostAt={null}
      />,
    );
    expect(screen.getByTestId("lease-device")).toHaveTextContent("dev-remote-88");
    expect(screen.getByTestId("lease-self-unknown")).toHaveTextContent(
      "本机设备标识尚未取得，无法判断持有者是否为本机。",
    );
  });

  it("lease.state === 'grace' 时展示宽限期文案并呈现「宽限期结束」时间行", () => {
    const lease: RemoteControlState = {
      state: "grace",
      device_key: "dev-other-2",
      expires_at: "2026-09-09T18:00:00Z",
      grace_expires_at: "2026-09-09T18:00:15Z",
      reason: "disconnected",
    };
    render(
      <LeaseStatusPanel
        lease={lease}
        selfDeviceKey="dev-self-1"
        controlLostAt={null}
      />,
    );
    const stateEl = screen.getByTestId("lease-state");
    expect(stateEl).toHaveTextContent("宽限期：断连后暂未回收控制权");
    expect(stateEl).toHaveClass("lease-status-grace");
    expect(screen.getByTestId("lease-device")).toHaveTextContent("dev-other-2");
    expect(screen.getByTestId("lease-grace-expires")).toBeInTheDocument();
  });

  it("controlLostAt 有真实时点时渲染失去控制权轻提示", () => {
    const lease: RemoteControlState = {
      state: "free",
      device_key: null,
      expires_at: null,
      grace_expires_at: null,
      reason: "timeout",
    };
    render(
      <LeaseStatusPanel
        lease={lease}
        selfDeviceKey="dev-self-1"
        controlLostAt="2026-09-09T18:01:00Z"
      />,
    );
    const hint = screen.getByTestId("lease-lost-hint");
    expect(hint).toBeInTheDocument();
    expect(hint).toHaveTextContent("已失去对电脑的控制权");
  });
});
