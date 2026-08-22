import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RemotePairingPanel, buildPairingUrl } from "../RemotePairingPanel";
import type { RemotePairingViewModel } from "../../../../contracts/view-models";

afterEach(cleanup);

function createMockPanelProps(overrides: Partial<RemotePairingViewModel> = {}) {
  const vm: RemotePairingViewModel = {
    code: null,
    ttlSeconds: 300,
    issuedAtEpochMs: null,
    devices: [],
    loading: false,
    error: null,
    ...overrides,
  };

  return {
    vm,
    onIssuePairingCode: vi.fn(),
    onListRemoteDevices: vi.fn(),
    onRevokeRemoteDevice: vi.fn(),
  };
}

describe("RemotePairingPanel (V0.3.3 远程设备配对面板)", () => {
  it("buildPairingUrl 组装正确的手机接入 URL", () => {
    const url = buildPairingUrl("654321", "192.168.1.50");
    expect(url).toBe("http://192.168.1.50:1421/?ws=ws://192.168.1.50:8765/ws&code=654321");
  });

  it("组件挂载时调用 onListRemoteDevices", () => {
    const props = createMockPanelProps();
    render(<RemotePairingPanel {...props} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(1);
  });

  it("回调引用变化不触发重复拉取（防 AppShell 内联回调渲染循环）", () => {
    const props = createMockPanelProps();
    const { rerender } = render(<RemotePairingPanel {...props} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(1);

    // AppShell 传入的是内联箭头，父级每次渲染都是新引用；面板不得因此重拉。
    rerender(<RemotePairingPanel {...props} onListRemoteDevices={vi.fn()} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(1);
  });

  it("未生成配对码时显示「生成配对码」按钮并可触发生成", () => {
    const props = createMockPanelProps();
    render(<RemotePairingPanel {...props} />);

    const issueBtn = screen.getByRole("button", { name: "生成配对码" });
    expect(issueBtn).toBeInTheDocument();
    fireEvent.click(issueBtn);
    expect(props.onIssuePairingCode).toHaveBeenCalledTimes(1);
  });

  it("配对码生成成功：展示六位配对码、二维码、倒计时与局域网说明", () => {
    const now = Date.now();
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: now,
      ttlSeconds: 300,
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByTestId("pairing-code")).toHaveTextContent("839201");
    expect(screen.getByTestId("pairing-countdown")).toBeInTheDocument();
    expect(
      screen.getByText("局域网地址以 Sidecar --serve 实际监听为准，请核对桌面端启动提示。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新生成配对码" })).toBeInTheDocument();
  });

  it("倒计时递减并在过期后展示「已过期，请重新生成」，过期码不再可用", () => {
    vi.useFakeTimers();
    const baseTime = 1700000000000;
    vi.setSystemTime(baseTime);

    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: baseTime,
      ttlSeconds: 300,
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByTestId("pairing-code")).toHaveTextContent("839201");
    expect(screen.getByTestId("pairing-countdown")).toHaveTextContent("5分00秒");

    // 前进 60 秒
    act(() => {
      vi.advanceTimersByTime(60000);
    });
    expect(screen.getByTestId("pairing-countdown")).toHaveTextContent("4分00秒");

    // 前进到过期（超过 300 秒）
    act(() => {
      vi.advanceTimersByTime(241000);
    });

    expect(screen.getByText("已过期，请重新生成")).toBeInTheDocument();
    expect(screen.queryByTestId("pairing-code")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pairing-countdown")).not.toBeInTheDocument();

    const regenBtn = screen.getByRole("button", { name: "重新生成配对码" });
    fireEvent.click(regenBtn);
    expect(props.onIssuePairingCode).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  it("Let It Fail：如实呈现配对错误信息", () => {
    const props = createMockPanelProps({
      error: "Sidecar 远程服务未开启：请使用 --serve 重新启动",
    });

    render(<RemotePairingPanel {...props} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Sidecar 远程服务未开启：请使用 --serve 重新启动");
  });

  it("处理中态：展示加载状态", () => {
    const props = createMockPanelProps({
      loading: true,
    });

    render(<RemotePairingPanel {...props} />);
    expect(screen.getByRole("status")).toHaveTextContent("处理中…");
  });

  it("设备列表渲染：支持已授权与已撤销状态", () => {
    const props = createMockPanelProps({
      devices: [
        {
          deviceName: "小米 14",
          issuedAt: "2026-08-19 09:00:00",
          lastUsedAt: "2026-08-19 12:30:00",
          revoked: false,
        },
        {
          deviceName: "iPad Pro",
          issuedAt: "2026-08-18 15:00:00",
          lastUsedAt: "2026-08-18 18:00:00",
          revoked: true,
        },
      ],
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByText("小米 14")).toBeInTheDocument();
    expect(screen.getByText("已授权")).toBeInTheDocument();
    expect(screen.getByText("iPad Pro")).toBeInTheDocument();
    expect(screen.getByText("已撤销")).toBeInTheDocument();

    // 只有未撤销设备有撤销按钮
    const revokeButtons = screen.getAllByRole("button", { name: "撤销" });
    expect(revokeButtons).toHaveLength(1);
  });

  it("撤销二次确认流：弹窗说明清除全部 token 与立即断连，确认后调用 onRevokeRemoteDevice", () => {
    const props = createMockPanelProps({
      devices: [
        {
          deviceName: "小米 14",
          issuedAt: "2026-08-19 09:00:00",
          lastUsedAt: "2026-08-19 12:30:00",
          revoked: false,
        },
      ],
    });

    render(<RemotePairingPanel {...props} />);

    // 点击撤销按钮，弹出确认弹窗
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));

    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveTextContent("确认撤销设备「小米 14」的连接授权？");
    expect(dialog).toHaveTextContent("撤销将清除该设备的全部授权 Token，该设备将立即失去连接并无法再操作。");

    // 点击取消，弹窗关闭且不触发撤销回调
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(props.onRevokeRemoteDevice).not.toHaveBeenCalled();

    // 再次点击撤销并确认
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    fireEvent.click(screen.getByRole("button", { name: "确认撤销" }));

    expect(props.onRevokeRemoteDevice).toHaveBeenCalledWith("小米 14");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
