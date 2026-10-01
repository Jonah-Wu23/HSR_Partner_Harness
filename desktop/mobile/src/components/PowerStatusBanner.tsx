import type { PowerStatusPayload } from "@shared/contracts/protocol";
import "./PowerStatusBanner.css";

/**
 * 手机端电源状态条，数据来自 power.get_status 与 power.status_changed（两者同形）。
 * - 尚未取得状态，或 supported=false（非 Windows）时不渲染；
 * - at_risk=true：警示「电脑可能休眠」，展示 reason 原文与 AC/DC 睡眠超时（0 秒为「从不」）；
 * - at_risk=false 且未开启远程服务：弱化展示 reason 原文；
 * - at_risk=false 且已开启远程服务：不渲染。
 */

export type { PowerStatusPayload };

export interface PowerStatusBannerProps {
  status: PowerStatusPayload | null;
  /** 提供时在警示态渲染「知道了」按钮；状态更新由接线层经 props 控制。 */
  onDismiss?: () => void;
}

function formatSleepSeconds(seconds: number | null): string {
  if (seconds === null) return "未知";
  // 0 表示从不睡眠。
  if (seconds === 0) return "从不";
  return `${seconds} 秒`;
}

export function PowerStatusBanner({ status, onDismiss }: PowerStatusBannerProps) {
  if (!status || !status.supported) {
    return null;
  }

  if (status.at_risk) {
    return (
      <aside
        className="power-banner is-at-risk"
        role="status"
        aria-live="polite"
        data-testid="power-status-banner"
        data-tone="at-risk"
      >
        <div className="power-banner-title" data-testid="power-status-title">
          电脑可能休眠
        </div>
        <p className="power-banner-reason" data-testid="power-status-reason">
          {status.reason}
        </p>
        <dl className="power-banner-detail" data-testid="power-status-detail">
          {status.plan_name ? (
            <div className="power-detail-row">
              <dt>电源计划</dt>
              <dd>{status.plan_name}</dd>
            </div>
          ) : null}
          <div className="power-detail-row">
            <dt>交流供电（AC）睡眠超时</dt>
            <dd>{formatSleepSeconds(status.ac_sleep_timeout_seconds)}</dd>
          </div>
          <div className="power-detail-row">
            <dt>电池供电（DC）睡眠超时</dt>
            <dd>{formatSleepSeconds(status.dc_sleep_timeout_seconds)}</dd>
          </div>
        </dl>
        <p className="power-banner-hint" data-testid="power-status-hint">
          如需手机持续接收通知，请在电脑的 Windows「设置 → 系统 → 电源」中延长睡眠时间。
        </p>
        {onDismiss ? (
          <button
            type="button"
            className="power-banner-btn"
            onClick={onDismiss}
            data-testid="btn-power-dismiss"
          >
            知道了
          </button>
        ) : null}
      </aside>
    );
  }

  if (!status.remote_serve_enabled) {
    return (
      <aside
        className="power-banner is-muted"
        role="status"
        aria-live="polite"
        data-testid="power-status-banner"
        data-tone="muted"
      >
        <span className="power-banner-reason" data-testid="power-status-reason">
          {status.reason}
        </span>
      </aside>
    );
  }

  return null;
}
