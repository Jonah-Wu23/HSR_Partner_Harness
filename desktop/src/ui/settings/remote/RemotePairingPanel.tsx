import type { RemotePairingViewModel } from "../../../contracts/view-models";
import { QrCode } from "../../primitives/QrCode";

interface RemotePairingPanelProps {
  vm: RemotePairingViewModel;
  onIssuePairingCode: () => void;
  onListRemoteDevices: () => void;
  onRevokeRemoteDevice: (deviceName: string) => void;
}

/**
 * V0.3.3 设置中心「远程设备」页（骨架空壳，由 W3 填充）。
 *
 * TODO(W3)：配对码生成（onIssuePairingCode）与 ttlSeconds 倒计时、过期后
 * 可重新生成；二维码用 QrCode 组件渲染（payload 组装手机接入信息，
 * 形如 http://<局域网地址>:<端口>/?code=<配对码>，地址来源在面板注明
 * 「以 Sidecar 实际监听地址为准」）；设备列表（onListRemoteDevices 挂载时加载）、
 * 撤销需确认弹窗（onRevokeRemoteDevice 按设备名撤销其全部 token）；
 * 远程服务未启动（Sidecar 未以 --serve 运行）时如实说明，不得伪造可连接状态。
 */
export function RemotePairingPanel(props: RemotePairingPanelProps) {
  const { vm } = props;
  return (
    <section className="settings-page" data-testid="remote-pairing-panel">
      <p className="settings-hint">
        骨架空壳：等待 W3 实现（见文件头 TODO）。配对经 Sidecar remote.*
        命令完成；配对码一次性、短期有效。
      </p>
      {vm.loading ? <p className="settings-hint">处理中…</p> : null}
      {vm.error ? (
        <p className="field-error" role="alert">
          {vm.error}
        </p>
      ) : null}
      {vm.code ? (
        <div className="settings-row">
          <code>{vm.code}</code>
          {/* TODO(W3)：value 换成完整接入信息，不是裸配对码 */}
          <QrCode value={vm.code} label="配对二维码" />
        </div>
      ) : null}
      <p className="settings-hint">已配对设备 {vm.devices.length} 台。</p>
    </section>
  );
}
