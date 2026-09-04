import type { HarnessActions } from "../../contracts/actions";
import { useDesktopStore, type DesktopState } from "../../stores/desktopStore";
import { formatCheckedAt, formatSleepTimeout } from "./powerFormat";
import { usePowerStatusQuery } from "./usePowerStatus";
import "./power.css";

interface PowerStatusSectionProps {
  /** 挂载时的主动 power.get_status 查询；设置页由 AppShell 传入。 */
  actions?: HarnessActions;
}

const selectPowerStatus = (state: DesktopState) => state.powerStatus;
const selectPowerError = (state: DesktopState) => state.powerError;
const selectPowerQueryInFlight = (state: DesktopState) => state.powerQueryInFlight;

/**
 * 设置中心「远程设备」页的电源状态小节（V10）：常驻只读展示当前电源计划、
 * AC/DC 睡眠超时、风险阈值、远程服务状态与判定理由。
 * 查询失败如实显示错误原文；非 Windows 如实显示不支持，不伪造数值。
 * 应用只提示与指引，永不代改电源设置（契约冻结 §2.1）。
 */
export function PowerStatusSection({ actions }: PowerStatusSectionProps) {
  usePowerStatusQuery(actions);
  const status = useDesktopStore(selectPowerStatus);
  const error = useDesktopStore(selectPowerError);
  const inFlight = useDesktopStore(selectPowerQueryInFlight);

  return (
    <section className="power-status" data-testid="power-status-section">
      <h3 className="settings-subhead">电源状态</h3>
      <p className="settings-hint">
        电脑进入睡眠会让手机端断开。这里只读展示 Sidecar 读取到的电源状态；
        应用只提醒，不会代改电源设置。
      </p>

      {error ? (
        <p className="field-error" role="alert" data-testid="power-status-error">
          电源状态读取失败：{error}
        </p>
      ) : null}

      {!status && !error ? (
        <p className="settings-hint" role="status">
          {inFlight ? "正在读取电源状态…" : "尚未读取电源状态。"}
        </p>
      ) : null}

      {status && !status.supported ? (
        <p className="settings-hint" role="status" data-testid="power-status-unsupported">
          {status.reason || "当前平台不支持电源状态检测"}
          {status.platform ? `（platform: ${status.platform}）` : ""}
        </p>
      ) : null}

      {status && status.supported ? (
        <>
          <dl className="power-status-facts" data-testid="power-status-facts">
            <div>
              <dt>电源计划</dt>
              <dd>{status.plan_name || "未读取到名称"}</dd>
            </div>
            <div>
              <dt>接通电源（AC）睡眠超时</dt>
              <dd>{formatSleepTimeout(status.ac_sleep_timeout_seconds)}</dd>
            </div>
            <div>
              <dt>使用电池（DC）睡眠超时</dt>
              <dd>{formatSleepTimeout(status.dc_sleep_timeout_seconds)}</dd>
            </div>
            <div>
              <dt>风险判定阈值</dt>
              <dd>{status.threshold_seconds} 秒</dd>
            </div>
            <div>
              <dt>远程服务</dt>
              <dd>{status.remote_serve_enabled ? "已开启" : "未开启"}</dd>
            </div>
            <div>
              <dt>读取时间</dt>
              <dd>{formatCheckedAt(status.checked_at)}</dd>
            </div>
          </dl>
          <p
            className={`settings-hint${status.at_risk ? " power-status-at-risk" : ""}`}
            role="status"
            data-testid="power-status-reason"
          >
            {status.at_risk ? "存在休眠风险：" : "判定："}
            {status.reason}
          </p>
        </>
      ) : null}
    </section>
  );
}
