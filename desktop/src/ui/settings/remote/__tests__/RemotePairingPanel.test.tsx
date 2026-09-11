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
    serveAddress: null,
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

describe("RemotePairingPanel (V0.3.3 远程设备配对面板)", () => {
  it("buildPairingUrl 按 serve 监听地址组装手机接入 URL（PWA 与 /ws 同端口）", () => {
    const url = buildPairingUrl("654321", "192.168.1.50", 8765);
    expect(url).toBe(
      "http://192.168.1.50:8765/?ws=ws%3A%2F%2F192.168.1.50%3A8765%2Fws&code=654321",
    );
  });

  it("buildPairingUrl 正确编码 IPv6 地址", () => {
    const url = buildPairingUrl("654321", "fe80::1", 8765);
    expect(url).toBe(
      "http://[fe80::1]:8765/?ws=ws%3A%2F%2F%5Bfe80%3A%3A1%5D%3A8765%2Fws&code=654321",
    );
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

  it("配对码生成成功且 serve 已上报：展示配对码、二维码、接入地址与倒计时", () => {
    const now = Date.now();
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: now,
      ttlSeconds: 300,
      serveAddress: { host: "192.168.1.50", port: 8765 },
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByTestId("pairing-code")).toHaveTextContent("839201");
    expect(screen.getByTestId("pairing-countdown")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.50:8765")).toBeInTheDocument();
    expect(screen.queryByTestId("pairing-qr-unavailable")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "作废旧码并生成新码" })).toBeInTheDocument();
  });

  it("V0.3.4 缺陷 6：serve 地址未知时不生成二维码，如实提示不可用", () => {
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: Date.now(),
      ttlSeconds: 300,
      serveAddress: null,
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByTestId("pairing-qr-unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("pairing-code")).toHaveTextContent("839201");
  });

  it("V039-S4-004：serve 已监听但无局域网地址时按真实状态说明，不再断言「未启动或启动失败」", () => {
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: Date.now(),
      ttlSeconds: 300,
      serveAddress: null,
      servePort: 8765,
      serveUnavailableReason: "no_lan_address",
    });

    render(<RemotePairingPanel {...props} />);

    const alert = screen.getByTestId("pairing-qr-unavailable");
    expect(alert).toHaveTextContent("远程服务已在监听端口 8765");
    expect(alert).toHaveTextContent("未探测到局域网地址");
    expect(alert).not.toHaveTextContent("未启动或启动失败");
  });

  it("V039-S4-004：serve 启动失败时原样转述后端报文", () => {
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: Date.now(),
      ttlSeconds: 300,
      serveAddress: null,
      serveFailure: "远程服务启动失败（端口 8765）：[WinError 10048] 地址已在使用",
    });

    render(<RemotePairingPanel {...props} />);

    expect(screen.getByTestId("pairing-qr-unavailable")).toHaveTextContent(
      "远程服务启动失败（端口 8765）：[WinError 10048] 地址已在使用",
    );
  });

  it("V039-S4-004：完全未收到上报时如实说明未收到地址，不编造原因", () => {
    const props = createMockPanelProps({
      code: "839201",
      issuedAtEpochMs: Date.now(),
      ttlSeconds: 300,
      serveAddress: null,
    });

    render(<RemotePairingPanel {...props} />);

    const alert = screen.getByTestId("pairing-qr-unavailable");
    expect(alert).toHaveTextContent("尚未收到 Sidecar 上报的远程服务地址");
    expect(alert).not.toHaveTextContent("启动失败");
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

    const regenBtn = screen.getByRole("button", { name: "作废旧码并生成新码" });
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

  /* —— V0.4.0 T7 改造测试 —— */

  describe("buildPairingUrl 动态协议与公网隧道", () => {
    it("传入公网隧道 https:// 地址时自动采用 https:// 与 wss:// 协议", () => {
      const url = buildPairingUrl("654321", "https://random-subdomain.trycloudflare.com");
      expect(url).toBe(
        "https://random-subdomain.trycloudflare.com/?ws=wss%3A%2F%2Frandom-subdomain.trycloudflare.com%2Fws&code=654321",
      );
    });

    it("传入带端口的 https:// 地址时正确保留端口并采用 wss://", () => {
      const url = buildPairingUrl("654321", "https://example.com:8443");
      expect(url).toBe(
        "https://example.com:8443/?ws=wss%3A%2F%2Fexample.com%3A8443%2Fws&code=654321",
      );
    });

    it("传入 tls=true 时自动生成 https:// 与 wss:// 协议", () => {
      const url = buildPairingUrl("654321", "192.168.1.50", 8765, true);
      expect(url).toBe(
        "https://192.168.1.50:8765/?ws=wss%3A%2F%2F192.168.1.50%3A8765%2Fws&code=654321",
      );
    });

    it("传入 wss:// 地址时自动解析为对应页面与 WebSocket 协议", () => {
      const url = buildPairingUrl("654321", "wss://tunnel.example.com");
      expect(url).toBe(
        "https://tunnel.example.com/?ws=wss%3A%2F%2Ftunnel.example.com%2Fws&code=654321",
      );
    });
  });

  describe("公网接入（Cloudflare Quick Tunnel）五态控制", () => {
    it("挂载时主动查询隧道初始状态（onQueryTunnelStatus）", () => {
      const props = createMockPanelProps();
      render(<RemotePairingPanel {...props} />);
      expect(props.onQueryTunnelStatus).toHaveBeenCalledTimes(1);
    });

    it("off 状态：展示未开启提示与「开启公网接入」按钮，点击调用 onTunnelStart", () => {
      const props = createMockPanelProps({
        tunnel: { state: "off", publicUrl: null, hostname: null, error: null },
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByText("未开启公网接入，仅可通过本地局域网或回环连接。")).toBeInTheDocument();
      const startBtn = screen.getByRole("button", { name: "开启公网接入" });
      expect(startBtn).toBeInTheDocument();

      fireEvent.click(startBtn);
      expect(props.onTunnelStart).toHaveBeenCalledTimes(1);
    });

    it("downloading 状态：展示下载中状态与禁用按钮", () => {
      const props = createMockPanelProps({
        tunnel: { state: "downloading", publicUrl: null, hostname: null, error: null },
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByText("正在下载 Cloudflare 隧道组件…")).toBeInTheDocument();
      const btn = screen.getByRole("button", { name: "下载中…" });
      expect(btn).toBeDisabled();
    });

    it("starting 状态：展示启动中状态与禁用按钮", () => {
      const props = createMockPanelProps({
        tunnel: { state: "starting", publicUrl: null, hostname: null, error: null },
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByText("正在启动公网隧道…")).toBeInTheDocument();
      const btn = screen.getByRole("button", { name: "启动中…" });
      expect(btn).toBeDisabled();
    });

    it("ready 状态：展示公网地址、切换为公网隧道标签、提供关闭按钮", async () => {
      const props = createMockPanelProps({
        code: "998877",
        issuedAtEpochMs: Date.now(),
        ttlSeconds: 300,
        serveAddress: { host: "127.0.0.1", port: 8765, mode: "loopback" },
        tunnel: {
          state: "ready",
          publicUrl: "https://demo-tunnel.trycloudflare.com",
          hostname: "demo-tunnel.trycloudflare.com",
          error: null,
        },
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByText("已就绪")).toBeInTheDocument();
      expect(screen.getAllByText(/demo-tunnel\.trycloudflare\.com/).length).toBeGreaterThan(0);
      expect(screen.getByText("（公网隧道）")).toBeInTheDocument();

      const stopBtn = screen.getByRole("button", { name: "关闭公网接入" });
      expect(stopBtn).toBeInTheDocument();
      fireEvent.click(stopBtn);
      expect(props.onTunnelStop).toHaveBeenCalledTimes(1);

      // 二维码正常呈现，不展示不可用警告
      expect(screen.queryByTestId("pairing-qr-unavailable")).not.toBeInTheDocument();
      const qrImg = await screen.findByRole("img", { name: "手机配对二维码" });
      expect(qrImg).toBeInTheDocument();
    });

    it("failed 状态：展示真实失败原因，并提供重试按钮", () => {
      const props = createMockPanelProps({
        tunnel: {
          state: "failed",
          publicUrl: null,
          hostname: null,
          error: "cloudflared 主机名解析超时 (30s)",
        },
      });
      render(<RemotePairingPanel {...props} />);

      const errorAlert = screen.getByTestId("tunnel-error");
      expect(errorAlert).toHaveTextContent("cloudflared 主机名解析超时 (30s)");

      const retryBtn = screen.getByRole("button", { name: "重试公网接入" });
      expect(retryBtn).toBeInTheDocument();
      fireEvent.click(retryBtn);
      expect(props.onTunnelStart).toHaveBeenCalledTimes(1);
    });
  });

  describe("局域网暴露警示与安全边界", () => {
    it("后端处于 --lan 模式且未开启隧道时，常驻展示局域网暴露警示", () => {
      const props = createMockPanelProps({
        serveAddress: { host: "192.168.1.50", port: 8765, mode: "lan" },
        tunnel: { state: "off", publicUrl: null, hostname: null, error: null },
      });
      render(<RemotePairingPanel {...props} />);

      const warning = screen.getByTestId("lan-exposure-warning");
      expect(warning).toBeInTheDocument();
      expect(warning).toHaveTextContent("当前处于局域网共享模式，请确保处于可信网络");
    });

    it("后端处于 loopback 模式时不展示局域网暴露警示", () => {
      const props = createMockPanelProps({
        serveAddress: { host: "127.0.0.1", port: 8765, mode: "loopback" },
        tunnel: { state: "off", publicUrl: null, hostname: null, error: null },
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.queryByTestId("lan-exposure-warning")).not.toBeInTheDocument();
    });

    it("后端处于 --lan 模式但公网隧道已就绪（ready）时不展示局域网暴露警示", () => {
      const props = createMockPanelProps({
        serveAddress: { host: "192.168.1.50", port: 8765, mode: "lan" },
        tunnel: {
          state: "ready",
          publicUrl: "https://secure-proxy.trycloudflare.com",
          hostname: "secure-proxy.trycloudflare.com",
          error: null,
        },
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.queryByTestId("lan-exposure-warning")).not.toBeInTheDocument();
    });
  });

  describe("配对码生成逻辑与文案（D4 单码有效）", () => {
    it("已有有效配对码时，按钮文案为「作废旧码并生成新码」，明确提示单码有效", () => {
      const props = createMockPanelProps({
        code: "123456",
        issuedAtEpochMs: Date.now(),
        ttlSeconds: 300,
        serveAddress: { host: "192.168.1.50", port: 8765 },
      });
      render(<RemotePairingPanel {...props} />);

      const button = screen.getByRole("button", { name: "作废旧码并生成新码" });
      expect(button).toBeInTheDocument();
      expect(
        screen.getByText("同时仅一枚配对码有效，生成新码将立即作废旧码与二维码。"),
      ).toBeInTheDocument();

      fireEvent.click(button);
      expect(props.onIssuePairingCode).toHaveBeenCalledTimes(1);
    });

    it("未生成配对码时文案为「生成配对码」", () => {
      const props = createMockPanelProps({
        code: null,
      });
      render(<RemotePairingPanel {...props} />);

      const button = screen.getByRole("button", { name: "生成配对码" });
      expect(button).toBeInTheDocument();
      fireEvent.click(button);
      expect(props.onIssuePairingCode).toHaveBeenCalledTimes(1);
    });
  });

  describe("已配对设备令牌到期时间展示", () => {
    it("设备列表项展示到期时间", () => {
      const props = createMockPanelProps({
        devices: [
          {
            deviceName: "Galaxy S24",
            issuedAt: "2026-09-11 10:00:00",
            lastUsedAt: "2026-09-11 10:30:00",
            expiresAt: "2026-09-18 10:30:00",
            revoked: false,
          },
        ],
      });
      render(<RemotePairingPanel {...props} />);

      expect(screen.getByText("Galaxy S24")).toBeInTheDocument();
      expect(screen.getByText("到期时间：2026-09-18 10:30:00")).toBeInTheDocument();
    });
  });
});
