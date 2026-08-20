import { useEffect, useRef, useState } from "react";
import type { RemotePairingViewModel } from "../../../contracts/view-models";
import { QrCode } from "../../primitives/QrCode";

interface RemotePairingPanelProps {
  vm: RemotePairingViewModel;
  onIssuePairingCode: () => void;
  onListRemoteDevices: () => void;
  onRevokeRemoteDevice: (deviceName: string) => void;
}

/**
 * 组装手机端接入地址 URL。
 * 形如 http://<局域网地址>:1421/?ws=ws://<局域网地址>:8765/ws&code=<配对码>
 */
export function buildPairingUrl(code: string, host = "127.0.0.1"): string {
  return `http://${host}:1421/?ws=ws://${host}:8765/ws&code=${encodeURIComponent(code)}`;
}

/**
 * 设置中心「远程设备」页。
 *
 * 提供手机远程接入配对码生成、二维码展示、倒计时与过期控制、
 * 已配对设备列表展示与设备 token 撤销确认。
 */
export function RemotePairingPanel(props: RemotePairingPanelProps) {
  const { vm, onIssuePairingCode, onListRemoteDevices, onRevokeRemoteDevice } = props;
  const [now, setNow] = useState(() => Date.now());
  const [revokingDeviceName, setRevokingDeviceName] = useState<string | null>(null);

  // 挂载时拉取设备列表。回调在 AppShell 是内联箭头，引用随每次渲染变化；
  // 用 ref 持有，避免 effect 依赖不稳定引用造成「拉取 → setState → 重渲染 → 重拉」死循环。
  const listDevicesRef = useRef(onListRemoteDevices);
  listDevicesRef.current = onListRemoteDevices;
  useEffect(() => {
    listDevicesRef.current();
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

  const ttlSeconds = vm.ttlSeconds || 300;
  const elapsedSeconds =
    vm.issuedAtEpochMs !== null ? Math.floor((now - vm.issuedAtEpochMs) / 1000) : 0;
  const remainingSeconds = Math.max(0, ttlSeconds - elapsedSeconds);
  const isExpired = vm.issuedAtEpochMs !== null && remainingSeconds <= 0;

  const lanHost =
    (typeof window !== "undefined" && window.location && window.location.hostname) ||
    "127.0.0.1";
  const pairingUrl = vm.code ? buildPairingUrl(vm.code, lanHost) : "";

  const formatCountdown = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}分${secs < 10 ? "0" : ""}${secs}秒`;
  };

  return (
    <section className="settings-page" data-testid="remote-pairing-panel">
      <p className="settings-hint">
        将手机作为远程控制端连回 PC。配对经 Sidecar 鉴权完成，配对码一次性且短期有效。
      </p>

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
            <QrCode value={pairingUrl} size={180} label="手机配对二维码" />
            <p className="settings-hint" style={{ fontSize: "12px", textAlign: "center" }}>
              用手机浏览器扫描二维码，或打开网页后输入配对码
            </p>
          </div>

          <p className="settings-hint" style={{ fontSize: "12px" }}>
            局域网地址以 Sidecar --serve 实际监听为准，请核对桌面端启动提示。
          </p>

          <div className="settings-row">
            <button
              type="button"
              className="btn btn-outline"
              disabled={vm.loading}
              onClick={onIssuePairingCode}
            >
              重新生成配对码
            </button>
          </div>
        </div>
      ) : isExpired ? (
        <div className="settings-status-card settings-status-expired" role="alert" style={{ gap: "12px" }}>
          <p className="field-error" style={{ fontWeight: 600 }}>
            已过期，请重新生成
          </p>
          <p className="settings-hint">
            为保障连接安全，配对码超过有效时限后自动失效，旧配对码已无法使用。
          </p>
          <div className="settings-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={vm.loading}
              onClick={onIssuePairingCode}
            >
              重新生成配对码
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
