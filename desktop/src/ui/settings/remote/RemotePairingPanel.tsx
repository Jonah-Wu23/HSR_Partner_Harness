import { useEffect, useRef, useState } from "react";
import type { RemotePairingViewModel } from "../../../contracts/view-models";
import { QrCode } from "../../primitives/QrCode";

export interface RemotePairingPanelProps {
  vm: RemotePairingViewModel;
  onIssuePairingCode: () => void;
  onListRemoteDevices: () => void;
  onRevokeRemoteDevice: (deviceName: string) => void;
  onTunnelStart?: () => void | Promise<void>;
  onTunnelStop?: () => void | Promise<void>;
  onQueryTunnelStatus?: () => void | Promise<void>;
}

/**
 * 组装手机端接入地址 URL（PWA 静态伺服与 /ws 同端口）。
 *
 * 支持动态协议（V0.4.0）：
 * - 如果 host 传入完整 URL（如公网隧道 https://xxx.trycloudflare.com），按其协议动态适配（https -> wss / http -> ws）
 * - 如果以 wss:// 或 ws:// 开头，自动解析对应页面与 ws 协议
 * - 如果指定 tls=true，采用 https:// 与 wss://
 * - 默认局域网/回环使用 http:// 与 ws://
 *
 * 形如 http://<局域网地址>:8765/?ws=ws://<局域网地址>:8765/ws&code=<配对码>
 * 或 https://<公网隧道>/?ws=wss://<公网隧道>/ws&code=<配对码>
 */
export function buildPairingUrl(
  code: string,
  host: string,
  port = 8765,
  tls?: boolean,
): string {
  if (/^https?:\/\//i.test(host)) {
    const pageUrl = new URL(host);
    const isHttps = pageUrl.protocol === "https:";
    const wsProto = isHttps ? "wss:" : "ws:";
    pageUrl.searchParams.set("ws", `${wsProto}//${pageUrl.host}/ws`);
    pageUrl.searchParams.set("code", code);
    return pageUrl.toString();
  }

  if (/^wss?:\/\//i.test(host)) {
    const isWss = host.toLowerCase().startsWith("wss://");
    const parsed = new URL(host.replace(/^ws/i, "http"));
    const httpProto = isWss ? "https:" : "http:";
    const wsProto = isWss ? "wss:" : "ws:";
    const pageUrl = new URL(`${httpProto}//${parsed.host}${parsed.pathname}`);
    pageUrl.searchParams.set("ws", `${wsProto}//${parsed.host}/ws`);
    pageUrl.searchParams.set("code", code);
    return pageUrl.toString();
  }

  const isHttps = Boolean(tls);
  const normalizedHost = host.startsWith("[") ? host : host.includes(":") ? `[${host}]` : host;
  const proto = isHttps ? "https" : "http";
  const wsProto = isHttps ? "wss" : "ws";
  const pageUrl = new URL(`${proto}://${normalizedHost}:${port}/`);
  pageUrl.searchParams.set("ws", `${wsProto}://${normalizedHost}:${port}/ws`);
  pageUrl.searchParams.set("code", code);
  return pageUrl.toString();
}

/**
 * V039-S4-004：二维码不可用时的真实原因。
 *
 * 只复述后端实际下发的事实：启动失败报文 / 已监听端口但无局域网地址（含原因码）/
 * 尚未收到上报。不再断言「Sidecar --serve 未启动或启动失败」——serve 已监听时
 * 那句话与事实相反。
 */
export function serveUnavailableMessage(vm: RemotePairingViewModel): string {
  if (vm.serveFailure) {
    return `远程服务地址未就绪：${vm.serveFailure}`;
  }
  if (vm.servePort) {
    const reason = vm.serveUnavailableReason
      ? `（${serveUnavailableReasonLabel(vm.serveUnavailableReason)}）`
      : "";
    return `远程服务已在监听端口 ${vm.servePort}，但没有可用的局域网接入地址${reason}，二维码暂不可用。`;
  }
  if (vm.serveUnavailableReason) {
    return `尚未获得可用的局域网接入地址（${serveUnavailableReasonLabel(vm.serveUnavailableReason)}），二维码暂不可用。`;
  }
  return "尚未收到 Sidecar 上报的远程服务地址，二维码暂不可用。若 Sidecar 未以 --serve 启动，手机端无法通过局域网连接。";
}

/** 协议原因码 → 人话；未知原因码原样展示，不猜含义。 */
function serveUnavailableReasonLabel(reason: string): string {
  if (reason === "no_lan_address") return "未探测到局域网地址";
  return reason;
}

/**
 * 设置中心「远程设备」页。
 *
 * 提供手机远程接入配对码生成、二维码展示、倒计时与过期控制、
 * 已配对设备列表展示与设备 token 撤销确认。
 */
export function RemotePairingPanel(props: RemotePairingPanelProps) {
  const {
    vm,
    onIssuePairingCode,
    onListRemoteDevices,
    onRevokeRemoteDevice,
    onTunnelStart,
    onTunnelStop,
    onQueryTunnelStatus,
  } = props;
  const [now, setNow] = useState(() => Date.now());
  const [revokingDeviceName, setRevokingDeviceName] = useState<string | null>(null);

  // 挂载时拉取设备列表。回调在 AppShell 是内联箭头，引用随每次渲染变化；
  // 用 ref 持有，避免 effect 依赖不稳定引用造成「拉取 → setState → 重渲染 → 重拉」死循环。
  const listDevicesRef = useRef(onListRemoteDevices);
  listDevicesRef.current = onListRemoteDevices;
  useEffect(() => {
    listDevicesRef.current();
  }, []);

  // R1-001：手机配对成功（remote.paired）经 store 推进 devicesRevision；
  // revision 变化时重拉设备列表。挂载时的首次拉取由上方 effect 负责，
  // 这里只响应变化，不重复拉取。
  const seenDevicesRevisionRef = useRef(vm.devicesRevision ?? 0);
  useEffect(() => {
    const revision = vm.devicesRevision ?? 0;
    if (revision === seenDevicesRevisionRef.current) return;
    seenDevicesRevisionRef.current = revision;
    listDevicesRef.current();
  }, [vm.devicesRevision]);

  // 挂载时查询公网隧道状态。
  const queryTunnelStatusRef = useRef(onQueryTunnelStatus);
  queryTunnelStatusRef.current = onQueryTunnelStatus;
  useEffect(() => {
    queryTunnelStatusRef.current?.();
  }, []);

  // 驱动配对码倒计时
  useEffect(() => {
    if (!vm.issuedAtEpochMs || !vm.code) return;
    setNow(Date.now());
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, [vm.issuedAtEpochMs, vm.code]);

  const ttlSeconds = vm.ttlSeconds ?? 300;
  const elapsedSeconds =
    vm.issuedAtEpochMs !== null ? Math.floor((now - vm.issuedAtEpochMs) / 1000) : 0;
  const remainingSeconds = Math.max(0, ttlSeconds - elapsedSeconds);
  const isExpired = vm.issuedAtEpochMs !== null && remainingSeconds <= 0;

  // 隧道五态
  const tunnel = vm.tunnel ?? {
    state: "off",
    publicUrl: null,
    hostname: null,
    error: null,
  };
  const isTunnelReady = tunnel.state === "ready" && Boolean(tunnel.publicUrl);

  // 局域网暴露警示：后端处于 --lan 模式且未开公网隧道时常驻提示
  const isLanMode = vm.serveAddress?.mode === "lan" || vm.serveMode === "lan";
  const showLanWarning = isLanMode && !isTunnelReady;

  // 二维码与配对链接生成：
  // 1. 公网隧道就绪（ready）时直接采用公网隧道 URL（https://*.trycloudflare.com）
  // 2. 否则按 Sidecar serve 监听地址生成；地址不可用时提示
  const serveAddress = vm.serveAddress;
  const pairingUrl = vm.code
    ? isTunnelReady && tunnel.publicUrl
      ? buildPairingUrl(vm.code, tunnel.publicUrl)
      : serveAddress
      ? buildPairingUrl(
          vm.code,
          serveAddress.host,
          serveAddress.port,
          serveAddress.tls ?? false,
        )
      : ""
    : "";

  const formatCountdown = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}分${secs < 10 ? "0" : ""}${secs}秒`;
  };

  return (
    <section className="settings-page" data-testid="remote-pairing-panel">
      <p className="settings-hint">
        将手机作为远程控制端连回 PC。配对经 Sidecar 鉴权完成，配对码一次性且短期有效；同时仅一枚配对码有效。
      </p>

      {/* 局域网暴露警示 */}
      {showLanWarning ? (
        <div
          className="field-warning"
          role="alert"
          data-testid="lan-exposure-warning"
          style={{
            padding: "8px 12px",
            borderRadius: "6px",
            background: "color-mix(in oklch, var(--warning, #ca8a04) 12%, transparent)",
            border: "1px solid color-mix(in oklch, var(--warning, #ca8a04) 35%, transparent)",
            marginBottom: "12px",
            fontSize: "13px",
          }}
        >
          当前处于局域网共享模式，请确保处于可信网络
        </div>
      ) : null}

      {vm.loading ? (
        <p className="settings-hint" role="status">
          处理中…
        </p>
      ) : null}

      {vm.error ? (
        <p className="field-error" role="alert">
          {vm.error}
        </p>
      ) : null}

      {/* 公网接入控制区 */}
      <h3 className="settings-subhead">公网接入</h3>
      <div className="settings-status-card" data-testid="tunnel-control-section" style={{ gap: "10px", marginBottom: "16px" }}>
        <div className="settings-row" style={{ alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <span className="field-label" style={{ fontWeight: 600 }}>Cloudflare Quick Tunnel</span>
            <p className="settings-hint" style={{ fontSize: "12px", marginTop: "2px" }}>
              无需公网 IP 或配置端口映射，直接建立安全 HTTPS/WSS 隧道供手机端在移动蜂窝网络下安全访问。
            </p>
          </div>
          <div>
            {tunnel.state === "ready" ? (
              <button
                type="button"
                className="btn btn-outline"
                data-testid="tunnel-stop-btn"
                disabled={vm.loading || tunnel.loading}
                onClick={onTunnelStop}
              >
                关闭公网接入
              </button>
            ) : tunnel.state === "downloading" ? (
              <button
                type="button"
                className="btn btn-primary"
                data-testid="tunnel-downloading-btn"
                disabled
              >
                下载中…
              </button>
            ) : tunnel.state === "starting" ? (
              <button
                type="button"
                className="btn btn-primary"
                data-testid="tunnel-starting-btn"
                disabled
              >
                启动中…
              </button>
            ) : tunnel.state === "failed" ? (
              <button
                type="button"
                className="btn btn-primary"
                data-testid="tunnel-retry-btn"
                disabled={vm.loading || tunnel.loading}
                onClick={onTunnelStart}
              >
                重试公网接入
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                data-testid="tunnel-start-btn"
                disabled={vm.loading || tunnel.loading}
                onClick={onTunnelStart}
              >
                开启公网接入
              </button>
            )}
          </div>
        </div>

        {/* 隧道五态详情展示 */}
        <div data-testid="tunnel-status-indicator" style={{ fontSize: "12px" }}>
          {tunnel.state === "ready" ? (
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span
                style={{
                  fontSize: "11px",
                  padding: "1px 6px",
                  borderRadius: "999px",
                  background: "var(--accent-soft)",
                  color: "var(--accent)",
                }}
              >
                已就绪
              </span>
              <span>
                公网地址：<code>{tunnel.publicUrl}</code>
              </span>
            </div>
          ) : tunnel.state === "downloading" ? (
            <p className="settings-hint" role="status" style={{ color: "var(--accent)" }}>
              正在下载 Cloudflare 隧道组件…
            </p>
          ) : tunnel.state === "starting" ? (
            <p className="settings-hint" role="status" style={{ color: "var(--accent)" }}>
              正在启动公网隧道…
            </p>
          ) : tunnel.state === "failed" ? (
            <p className="field-error" role="alert" data-testid="tunnel-error">
              公网隧道启动失败：{tunnel.error || "未知原因"}
            </p>
          ) : (
            <p className="settings-hint">未开启公网接入，仅可通过本地局域网或回环连接。</p>
          )}
        </div>
      </div>

      <h3 className="settings-subhead">手机配对</h3>

      {/* 配对码及二维码展示区 */}
      {vm.code && !isExpired ? (
        <div className="settings-status-card" style={{ gap: "12px" }}>
          <div className="settings-row" style={{ alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span className="field-label">六位配对码</span>
              <div style={{ marginTop: "4px" }}>
                <code
                  data-testid="pairing-code"
                  style={{
                    fontSize: "24px",
                    fontWeight: 700,
                    letterSpacing: "4px",
                    color: "var(--accent)",
                  }}
                >
                  {vm.code}
                </code>
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <span className="field-label">剩余有效时间</span>
              <p
                data-testid="pairing-countdown"
                className="settings-hint"
                style={{ marginTop: "4px", fontWeight: 600, color: remainingSeconds < 60 ? "var(--danger)" : "var(--text-primary)" }}
              >
                {formatCountdown(remainingSeconds)}
              </p>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px", padding: "12px 0" }}>
            {pairingUrl ? (
              <>
                <QrCode value={pairingUrl} size={180} label="手机配对二维码" />
                <p className="settings-hint" style={{ fontSize: "12px", textAlign: "center" }}>
                  用手机浏览器扫描二维码，或打开网页后输入配对码
                </p>
                <p className="settings-hint" style={{ fontSize: "12px", textAlign: "center" }}>
                  接入地址：<code>{isTunnelReady ? tunnel.publicUrl : serveAddress ? `${serveAddress.host}:${serveAddress.port}` : ""}</code>
                  {isTunnelReady ? (
                    <span style={{ marginLeft: "6px", color: "var(--accent)" }}>（公网隧道）</span>
                  ) : null}
                </p>
              </>
            ) : (
              <p className="field-error" data-testid="pairing-qr-unavailable" role="alert" style={{ fontSize: "12px" }}>
                {serveUnavailableMessage(vm)}
              </p>
            )}
          </div>

          <p className="settings-hint" style={{ fontSize: "12px" }}>
            同时仅一枚配对码有效，生成新码将立即作废旧码与二维码。
          </p>

          <div className="settings-row">
            <button
              type="button"
              className="btn btn-outline"
              disabled={vm.loading}
              onClick={onIssuePairingCode}
            >
              作废旧码并生成新码
            </button>
          </div>
        </div>
      ) : isExpired ? (
        <div className="settings-status-card settings-status-expired" role="alert" style={{ gap: "12px" }}>
          <p className="field-error" style={{ fontWeight: 600 }}>
            已过期，请重新生成
          </p>
          <p className="settings-hint">
            为保障连接安全，配对码超过有效时限后自动失效，旧配对码已无法使用。同时仅一枚配对码有效。
          </p>
          <div className="settings-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={vm.loading}
              onClick={onIssuePairingCode}
            >
              作废旧码并生成新码
            </button>
          </div>
        </div>
      ) : (
        <div className="settings-row">
          <button
            type="button"
            className="btn btn-primary"
            disabled={vm.loading}
            onClick={onIssuePairingCode}
          >
            生成配对码
          </button>
        </div>
      )}

      {/* 设备列表 */}
      <h3 className="settings-subhead">已配对设备（{vm.devices.length}）</h3>

      {vm.devices.length === 0 ? (
        <p className="settings-hint">暂无已配对设备。通过上方配对码连接手机端后，设备将显示在此处。</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }} data-testid="remote-device-list">
          {vm.devices.map((device) => (
            <article
              key={device.deviceName}
              className="settings-voice-speaker"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "12px",
                opacity: device.revoked ? 0.6 : 1,
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "4px", minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <strong style={{ fontSize: "14px" }}>{device.deviceName}</strong>
                  {device.revoked ? (
                    <span
                      style={{
                        fontSize: "11px",
                        padding: "1px 6px",
                        borderRadius: "999px",
                        background: "var(--fill-hover)",
                        color: "var(--danger)",
                        border: "1px solid var(--danger)",
                      }}
                    >
                      已撤销
                    </span>
                  ) : (
                    <span
                      style={{
                        fontSize: "11px",
                        padding: "1px 6px",
                        borderRadius: "999px",
                        background: "var(--accent-soft)",
                        color: "var(--accent)",
                      }}
                    >
                      已授权
                    </span>
                  )}
                </div>
                <div className="settings-hint" style={{ fontSize: "12px", display: "flex", gap: "12px", flexWrap: "wrap" }}>
                  <span>配对时间：{device.issuedAt || "未知"}</span>
                  <span>最近使用：{device.lastUsedAt || "未知"}</span>
                  <span>到期时间：{device.expiresAt || "未知"}</span>
                </div>
              </div>

              <div>
                {!device.revoked ? (
                  <button
                    type="button"
                    className="btn btn-danger-outline"
                    disabled={vm.loading}
                    onClick={() => setRevokingDeviceName(device.deviceName)}
                  >
                    撤销
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}

      {/* 撤销确认弹窗 */}
      {revokingDeviceName ? (
        <div
          className="settings-confirm"
          role="alertdialog"
          aria-modal="true"
          aria-label="撤销设备授权确认"
          style={{ flexDirection: "column", alignItems: "stretch", gap: "8px", marginTop: "12px" }}
        >
          <div style={{ fontWeight: 600 }}>
            确认撤销设备「{revokingDeviceName}」的连接授权？
          </div>
          <p className="settings-hint" style={{ fontSize: "12px" }}>
            撤销将清除该设备的全部授权 Token，该设备将立即失去连接并无法再操作。
          </p>
          <div className="settings-confirm-actions" style={{ marginTop: "4px" }}>
            <button
              type="button"
              className="btn btn-danger-outline"
              disabled={vm.loading}
              onClick={() => {
                const target = revokingDeviceName;
                setRevokingDeviceName(null);
                if (target) onRevokeRemoteDevice(target);
              }}
            >
              确认撤销
            </button>
            <button
              type="button"
              className="btn btn-outline"
              disabled={vm.loading}
              onClick={() => setRevokingDeviceName(null)}
            >
              取消
            </button>
          </div>
        </div>
      ) : null}

      <p className="settings-hint" style={{ marginTop: "16px", fontSize: "12px" }}>
        提示：Sidecar 需以 <code>--serve</code> 参数运行以开启局域网 WebSocket 监听服务；未开启时手机端将无法连接。
      </p>
    </section>
  );
}
