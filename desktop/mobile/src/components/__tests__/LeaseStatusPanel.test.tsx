import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { LeaseStatusPanel } from "../LeaseStatusPanel";
import type { RemoteControlState } from "@shared/contracts/protocol";

describe("LeaseStatusPanel 组件", () => {
  afterEach(() => {
    cleanup();
  });

  it("首次同步前没有租约状态时说明在等待快照或事件", () => {
    render(<LeaseStatusPanel lease={null} />);
    expect(screen.getByTestId("lease-unknown")).toHaveTextContent(
      "尚未取得控制权状态：等待 remote_control 快照或 remote.control_changed 事件。",
    );
    expect(screen.queryByTestId("lease-state")).toBeNull();
  });

  it.each<{
    lease: RemoteControlState;
    label: string;
    device: string;
    expiresKnown: boolean;
    graceRow: boolean;
    selfUnknown: boolean;
  }>([
    {
      lease: { state: "free", device_key: null, expires_at: null, grace_expires_at: null, reason: "released" },
      label: "空闲：没有设备持有控制权",
      device: "—",
      expiresKnown: false,
      graceRow: false,
      selfUnknown: false,
    },
    {
      lease: {
        state: "held",
        device_key: "dev-remote-88",
        expires_at: "2026-09-09T18:00:00Z",
        grace_expires_at: null,
        reason: "claimed",
      },
      label: "已由设备持有控制权",
      device: "dev-remote-88",
      expiresKnown: true,
      graceRow: false,
      selfUnknown: true,
    },
    {
      lease: {
        state: "grace",
        device_key: "dev-other-2",
        expires_at: "2026-09-09T18:00:00Z",
        grace_expires_at: "2026-09-09T18:00:15Z",
        reason: "disconnected",
      },
      label: "宽限期：断连后暂未回收控制权",
      device: "dev-other-2",
      expiresKnown: true,
      graceRow: true,
      selfUnknown: true,
    },
  ])("$lease.state 状态展示文案、持有设备与时间行", ({
    lease,
    label,
    device,
    expiresKnown,
    graceRow,
    selfUnknown,
  }) => {
    render(<LeaseStatusPanel lease={lease} />);

    expect(screen.getByTestId("lease-state")).toHaveTextContent(label);
    expect(screen.getByTestId("lease-device")).toHaveTextContent(device);
    expect(screen.getByTestId("lease-reason")).toHaveTextContent(lease.reason ?? "");
    expect(screen.getByTestId("lease-expires").textContent === "未知").toBe(!expiresKnown);
    expect(screen.queryByTestId("lease-grace-expires") !== null).toBe(graceRow);
    if (selfUnknown) {
      expect(screen.getByTestId("lease-self-unknown")).toHaveTextContent(
        "手机端无法判断它是否为本机",
      );
    } else {
      expect(screen.queryByTestId("lease-self-unknown")).toBeNull();
    }
  });
});
