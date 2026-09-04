import type { PowerStatusPayload } from "@shared/contracts/protocol";
import "./PowerStatusBanner.css";

/**
 * V0.3.7 手机端电源状态条（V11 接线）。
 *
 * 数据契约：docs/plans/V0.3.7-契约冻结.md §1.5 `power.get_status` result / §2.1
 * `power.status_changed` payload（两者完全同形）。类型取自共享 contracts 的
 * PowerStatusPayload（冻结 §10），由 mobileStore 从事件流原样存入。
 *
 * 呈现规则（全部来自 payload 事实，不本地推导、不伪造状态）：
 * - status 为空（尚未取得数据）→ 不渲染；
 * - supported=false（非 Windows 平台）→ 不渲染（契约如实返回 unsupported，无风险可提示）；
 * - at_risk=true → 醒目警示「电脑可能休眠」，reason 原文展示，附 AC/DC 睡眠超时秒数
 *   （0 秒 = 「从不」，冻结 §8）与不代改设置的指引；
 * - at_risk=false 且 remote_serve_enabled=false → 弱化展示 reason 原文，说明当前为何
 *   不会有休眠提醒；
 * - at_risk=false 且 remote_serve_enabled=true → 不渲染（正常态，提示收敛，对齐 V10 语义）。
 */

export type { PowerStatusPayload };

export interface PowerStatusBannerProps {
  status: PowerStatusPayload | null;
  /** 提供时在警示态渲染「知道了」按钮；状态更新由接线层经 props 控制。 */
  onDismiss?: () => void;
}

function formatSleepSeconds(seconds: number | null): string {
  if (seconds === null) return "未知";
  // 冻结 §8：0 表示「从不」。
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
          本应用只做提示，不会修改电脑的电源设置。
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
