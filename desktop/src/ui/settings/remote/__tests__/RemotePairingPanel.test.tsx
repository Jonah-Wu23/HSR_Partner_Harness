import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RemotePairingPanel, buildPairingUrl } from "../RemotePairingPanel";
import type { RemotePairingViewModel, TunnelViewModel } from "../../../../contracts/view-models";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function tunnelVm(overrides: Partial<TunnelViewModel> = {}): TunnelViewModel {
  return {
    state: "off",
    publicUrl: null,
    hostname: null,
    error: null,
    requestError: null,
    loading: false,
    ...overrides,
  };
}

const readyTunnel = tunnelVm({
  state: "ready",
  publicUrl: "https://demo-tunnel.trycloudflare.com",
  hostname: "demo-tunnel.trycloudflare.com",
});

function createMockPanelProps(overrides: Partial<RemotePairingViewModel> = {}) {
  const vm: RemotePairingViewModel = {
    code: null,
    ttlSeconds: 300,
    issuedAtEpochMs: null,
    devices: [],
    loading: false,
    error: null,
    serveAddress: null,
    tunnel: tunnelVm(),
    ...overrides,
  };

  return {
    vm,
    onIssuePairingCode: vi.fn(),
    onListRemoteDevices: vi.fn(),
    onRevokeRemoteDevice: vi.fn(),
    onTunnelStart: vi.fn(),
    onTunnelStop: vi.fn(),
    onQueryTunnelStatus: vi.fn(),
  };
}

describe("buildPairingUrl", () => {
  it.each<[string, string, number | undefined, boolean | undefined, string]>([
    [
      "局域网地址用 http 与 ws，PWA 与 /ws 同端口",
      "192.168.1.50",
      8765,
      undefined,
      "http://192.168.1.50:8765/?ws=ws%3A%2F%2F192.168.1.50%3A8765%2Fws&code=654321",
    ],
    [
      "IPv6 地址加方括号并编码",
      "fe80::1",
      8765,
      undefined,
      "http://[fe80::1]:8765/?ws=ws%3A%2F%2F%5Bfe80%3A%3A1%5D%3A8765%2Fws&code=654321",
    ],
    [
      "tls=true 时用 https 与 wss",
      "192.168.1.50",
      8765,
      true,
      "https://192.168.1.50:8765/?ws=wss%3A%2F%2F192.168.1.50%3A8765%2Fws&code=654321",
    ],
    [
      "公网隧道 https 地址用 wss",
      "https://random-subdomain.trycloudflare.com",
      undefined,
      undefined,
      "https://random-subdomain.trycloudflare.com/?ws=wss%3A%2F%2Frandom-subdomain.trycloudflare.com%2Fws&code=654321",
    ],
    [
      "带端口的 https 地址保留端口",
      "https://example.com:8443",
      undefined,
      undefined,
      "https://example.com:8443/?ws=wss%3A%2F%2Fexample.com%3A8443%2Fws&code=654321",
    ],
    [
      "wss 地址换算为 https 页面",
      "wss://tunnel.example.com",
      undefined,
      undefined,
      "https://tunnel.example.com/?ws=wss%3A%2F%2Ftunnel.example.com%2Fws&code=654321",
    ],
  ])("%s", (_name, host, port, tls, expected) => {
    expect(buildPairingUrl("654321", host, port, tls)).toBe(expected);
  });
});

describe("RemotePairingPanel", () => {
  it("挂载时拉取设备列表并查询隧道状态，devicesRevision 变化时只重拉设备列表", () => {
    const props = createMockPanelProps({ devicesRevision: 0 });
    const { rerender } = render(<RemotePairingPanel {...props} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(1);
    expect(props.onQueryTunnelStatus).toHaveBeenCalledTimes(1);

    // 手机配对成功（remote.paired）推进 revision，面板重拉列表
    rerender(<RemotePairingPanel {...props} vm={{ ...props.vm, devicesRevision: 1 }} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(2);

    // 同值重渲染（如倒计时 tick 触发的父级渲染）不再拉取
    rerender(<RemotePairingPanel {...props} vm={{ ...props.vm, devicesRevision: 1 }} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(2);

    rerender(<RemotePairingPanel {...props} vm={{ ...props.vm, devicesRevision: 2 }} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(3);
    expect(props.onQueryTunnelStatus).toHaveBeenCalledTimes(1);
  });

  it("父级回调引用变化不触发重复拉取", () => {
    const props = createMockPanelProps();
    const { rerender } = render(<RemotePairingPanel {...props} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(1);

    // AppShell 传入的是内联箭头，父级每次渲染都是新引用
    rerender(<RemotePairingPanel {...props} onListRemoteDevices={vi.fn()} />);
    expect(props.onListRemoteDevices).toHaveBeenCalledTimes(1);
  });

  it("未生成配对码时显示「生成配对码」按钮并可触发生成", () => {
    const props = createMockPanelProps();
    render(<RemotePairingPanel {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "生成配对码" }));
    expect(props.onIssuePairingCode).toHaveBeenCalledTimes(1);
  });

  it("已有有效配对码：展示配对码、倒计时、接入地址与单码有效提示，可作废旧码并生成新码", () => {
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: Date.now(),
      ttlSeconds: 300,
      serveAddress: { host: "192.168.1.50", port: 8765 },
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByTestId("pairing-code")).toHaveTextContent("839201");
    expect(screen.getByTestId("pairing-countdown")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.50:8765")).toBeInTheDocument();
    expect(screen.queryByTestId("pairing-qr-unavailable")).not.toBeInTheDocument();
    expect(
      screen.getByText("同时仅一枚配对码有效，生成新码将立即作废旧码与二维码。"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "作废旧码并生成新码" }));
    expect(props.onIssuePairingCode).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      "未收到 serve 上报时说明未收到地址",
      {},
      "尚未收到 Sidecar 上报的远程服务地址，二维码暂不可用。",
    ],
    [
      "serve 已监听但无局域网地址时说明端口与原因",
      { servePort: 8765, serveUnavailableReason: "no_lan_address" },
      "远程服务已在监听端口 8765，但没有可用的局域网接入地址（未探测到局域网地址），二维码暂不可用。",
    ],
    [
      "serve 启动失败时原样转述后端报文",
      { serveFailure: "远程服务启动失败（端口 8765）：[WinError 10048] 地址已在使用" },
      "远程服务启动失败（端口 8765）：[WinError 10048] 地址已在使用",
    ],
  ])("没有接入地址时不生成二维码，配对码照常显示：%s", (_name, serveState, expected) => {
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: Date.now(),
      ttlSeconds: 300,
      serveAddress: null,
      ...serveState,
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByTestId("pairing-qr-unavailable")).toHaveTextContent(expected);
    expect(screen.getByTestId("pairing-code")).toHaveTextContent("839201");
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

    act(() => {
      vi.advanceTimersByTime(60000);
    });
    expect(screen.getByTestId("pairing-countdown")).toHaveTextContent("4分00秒");

    act(() => {
      vi.advanceTimersByTime(241000);
    });

    expect(screen.getByText("已过期，请重新生成")).toBeInTheDocument();
    expect(screen.queryByTestId("pairing-code")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pairing-countdown")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "作废旧码并生成新码" }));
    expect(props.onIssuePairingCode).toHaveBeenCalledTimes(1);
  });

  it("配对请求错误原文显示为告警", () => {
    const props = createMockPanelProps({
      error: "Sidecar 远程服务未开启：请使用 --serve 重新启动",
    });

    render(<RemotePairingPanel {...props} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Sidecar 远程服务未开启：请使用 --serve 重新启动",
    );
  });

  it("处理中显示加载状态", () => {
    const props = createMockPanelProps({ loading: true });

    render(<RemotePairingPanel {...props} />);
    expect(screen.getByRole("status")).toHaveTextContent("处理中…");
  });

  it("设备列表展示授权状态与到期时间，只有未撤销设备可撤销", () => {
    const props = createMockPanelProps({
      devices: [
        {
          deviceName: "小米 14",
          issuedAt: "2026-08-19 09:00:00",
          lastUsedAt: "2026-08-19 12:30:00",
          expiresAt: "2026-08-26 12:30:00",
          revoked: false,
        },
        {
          deviceName: "iPad Pro",
          issuedAt: "2026-08-18 15:00:00",
          lastUsedAt: "2026-08-18 18:00:00",
          expiresAt: "2026-08-25 18:00:00",
          revoked: true,
        },
      ],
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByText("小米 14")).toBeInTheDocument();
    expect(screen.getByText("已授权")).toBeInTheDocument();
    expect(screen.getByText("到期时间：2026-08-26 12:30:00")).toBeInTheDocument();
    expect(screen.getByText("iPad Pro")).toBeInTheDocument();
    expect(screen.getByText("已撤销")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "撤销" })).toHaveLength(1);
  });

  it("撤销二次确认流：弹窗说明清除全部 token 与立即断连，确认后调用 onRevokeRemoteDevice", () => {
    const props = createMockPanelProps({
      devices: [
        {
          deviceName: "小米 14",
          issuedAt: "2026-08-19 09:00:00",
          lastUsedAt: "2026-08-19 12:30:00",
          expiresAt: "2026-08-26 12:30:00",
          revoked: false,
        },
      ],
    });

    render(<RemotePairingPanel {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("确认撤销设备「小米 14」的连接授权？");
    expect(dialog).toHaveTextContent("撤销将清除该设备的全部授权 Token，该设备将立即失去连接并无法再操作。");

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(props.onRevokeRemoteDevice).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    fireEvent.click(screen.getByRole("button", { name: "确认撤销" }));

    expect(props.onRevokeRemoteDevice).toHaveBeenCalledWith("小米 14");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  describe("公网接入（Cloudflare Quick Tunnel）", () => {
    it("off：展示未开启提示，「开启公网接入」触发 onTunnelStart", () => {
      const props = createMockPanelProps();
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByText("未开启公网接入，仅可通过本地局域网或回环连接。")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "开启公网接入" }));
      expect(props.onTunnelStart).toHaveBeenCalledTimes(1);
    });

    it.each([
      ["downloading", "正在下载 Cloudflare 隧道组件…", "下载中…"],
      ["starting", "正在启动公网隧道…", "启动中…"],
    ] as const)("%s：展示进行中状态，按钮禁用", (state, statusText, buttonName) => {
      const props = createMockPanelProps({ tunnel: tunnelVm({ state }) });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByRole("status")).toHaveTextContent(statusText);
      expect(screen.getByRole("button", { name: buttonName })).toBeDisabled();
    });

    it("ready：展示公网地址，二维码改用公网隧道地址，「关闭公网接入」触发 onTunnelStop", async () => {
      const props = createMockPanelProps({
        code: "998877",
        issuedAtEpochMs: Date.now(),
        ttlSeconds: 300,
        serveAddress: { host: "127.0.0.1", port: 8765, mode: "loopback" },
        tunnel: readyTunnel,
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByText("已就绪")).toBeInTheDocument();
      expect(screen.getAllByText(/demo-tunnel\.trycloudflare\.com/).length).toBeGreaterThan(0);
      expect(screen.getByText("（公网隧道）")).toBeInTheDocument();
      expect(screen.queryByTestId("pairing-qr-unavailable")).not.toBeInTheDocument();
      expect(await screen.findByRole("img", { name: "手机配对二维码" })).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "关闭公网接入" }));
      expect(props.onTunnelStop).toHaveBeenCalledTimes(1);
    });

    it("failed：展示失败原因，「重试公网接入」触发 onTunnelStart", () => {
      const props = createMockPanelProps({
        tunnel: tunnelVm({ state: "failed", error: "cloudflared 主机名解析超时 (30s)" }),
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByTestId("tunnel-error")).toHaveTextContent("cloudflared 主机名解析超时 (30s)");
      fireEvent.click(screen.getByRole("button", { name: "重试公网接入" }));
      expect(props.onTunnelStart).toHaveBeenCalledTimes(1);
    });
  });

  describe("局域网暴露警示", () => {
    it("后端处于 --lan 模式且未开启隧道时常驻展示警示", () => {
      const props = createMockPanelProps({
        serveAddress: { host: "192.168.1.50", port: 8765, mode: "lan" },
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByTestId("lan-exposure-warning")).toHaveTextContent(
        "当前处于局域网共享模式，请确保处于可信网络",
      );
    });

    it.each([
      ["后端处于 loopback 模式", { host: "127.0.0.1", port: 8765, mode: "loopback" as const }, tunnelVm()],
      ["后端处于 --lan 模式但公网隧道已就绪", { host: "192.168.1.50", port: 8765, mode: "lan" as const }, readyTunnel],
    ])("%s时不展示警示", (_name, serveAddress, tunnel) => {
      const props = createMockPanelProps({ serveAddress, tunnel });
      render(<RemotePairingPanel {...props} />);

      expect(screen.queryByTestId("lan-exposure-warning")).not.toBeInTheDocument();
    });
  });
});
