import type { RemoteDevice } from "@shared/contracts/protocol";
import { formatLocalDateTime } from "./formatTime";
import "./DeviceListPanel.css";

/**
 * V0.3.9 V06：远程设备列表（remote.list_devices / remote.revoke 已有协议）。
 *
 * 契约事实：
 * - RemoteDevice = { device_name, issued_at, last_used_at, revoked }（protocol.ts）；
 * - remote.revoke 按设备名撤销该设备的全部 token（pairing.revoke）；
 * - 「是否当前设备」由 device_name 与本机配对时写入的 deviceName 相等判定，
 *   不新增字段、不猜测；两者任一缺失即不标记。
 *
 * 呈现纪律：devices === null 表示尚未取得列表（如实说明），空数组才是「真的没有设备」；
 * 读取/撤销失败显示原始错误文本（error.code + message），不吞异常、不合成成功。
 */

export interface DeviceListPanelProps {
  /** remote.list_devices 结果；null = 尚未取得。 */
  devices: RemoteDevice[] | null;
  /** 本机设备名（配对时写入 phm.remote.deviceName）；未知为 null。 */
  currentDeviceName: string | null;
  loading: boolean;
  /** 读取失败原文（含 error.code）；无错误为 null。 */
  error: string | null;
  /** 正在撤销的设备名；无进行中的撤销为 null。 */
  revokingDeviceName: string | null;
  /** 撤销失败原文；无错误为 null。 */
  revokeError: string | null;
  onRefresh: () => void;
  onRevoke: (deviceName: string) => void;
}

export function DeviceListPanel({
  devices,
  currentDeviceName,
  loading,
  error,
  revokingDeviceName,
  revokeError,
  onRefresh,
  onRevoke,
}: DeviceListPanelProps) {
  return (
    <section
      className="card device-panel"
      aria-label="远程设备"
      data-testid="device-list-panel"
    >
      <div className="device-panel-header">
        <h3 className="device-panel-title">远程设备</h3>
        <button
          type="button"
          className="device-refresh-btn"
          onClick={onRefresh}
          disabled={loading}
          data-testid="btn-refresh-devices"
        >
          {loading ? "读取中…" : "刷新"}
        </button>
      </div>

      {error ? (
        <p className="device-error" role="alert" data-testid="device-list-error">
          {error}
        </p>
      ) : null}

      {devices === null ? (
        <p className="hint" data-testid="device-list-unknown">
          {loading ? "正在读取设备列表…" : "尚未取得设备列表。"}
        </p>
      ) : devices.length === 0 ? (
        <p className="hint" data-testid="device-list-empty">
          还没有已配对的设备。
        </p>
      ) : (
        <ul className="device-list" data-testid="device-list">
          {devices.map((device) => {
            const isCurrent =
              currentDeviceName !== null && device.device_name === currentDeviceName;
            const revoking = revokingDeviceName === device.device_name;
            return (
              <li
                key={`${device.device_name}-${device.issued_at}`}
                className={`device-row${device.revoked ? " is-revoked" : ""}`}
                data-testid={`device-row-${device.device_name}`}
              >
                <div className="device-info">
                  <span className="device-name">
                    {device.device_name}
                    {isCurrent ? (
                      <span
                        className="device-tag is-current"
                        data-testid={`device-current-${device.device_name}`}
                      >
                        当前设备
                      </span>
                    ) : null}
                    {device.revoked ? (
                      <span
                        className="device-tag is-revoked"
                        data-testid={`device-revoked-${device.device_name}`}
                      >
                        已撤销
                      </span>
                    ) : null}
                  </span>
                  <span className="device-meta" data-testid={`device-times-${device.device_name}`}>
                    <span>配对：{formatLocalDateTime(device.issued_at) ?? "未知"}</span>
                    <span>最后活跃：{formatLocalDateTime(device.last_used_at) ?? "未知"}</span>
                  </span>
                </div>
                <button
                  type="button"
                  className="device-revoke-btn"
                  onClick={() => onRevoke(device.device_name)}
                  disabled={device.revoked || revoking}
                  data-testid={`btn-revoke-${device.device_name}`}
                >
                  {device.revoked ? "已撤销" : revoking ? "撤销中…" : "撤销"}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {revokeError ? (
        <p className="device-error" role="alert" data-testid="device-revoke-error">
          {revokeError}
        </p>
      ) : null}
    </section>
  );
}
