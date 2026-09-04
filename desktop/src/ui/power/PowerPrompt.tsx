import type { HarnessActions } from "../../contracts/actions";
import { desktopStore, useDesktopStore, type DesktopState } from "../../stores/desktopStore";
import { formatSleepTimeout, shouldShowPowerPrompt } from "./powerFormat";
import { usePowerStatusQuery } from "./usePowerStatus";
import "./power.css";

interface PowerPromptProps {
  /** 用于挂载时的主动 power.get_status 查询；AppShell 传入。 */
  actions?: HarnessActions;
}

/** 事件与查询共用的最新载荷；可见性判定见 shouldShowPowerPrompt。 */
const selectPromptStatus = (state: DesktopState) => state.powerStatus;

/**
 * V0.3.7 V10 桌面端电源提示（非打扰）：远程服务开启且电脑即将休眠时出现在右下角，
 * 展示 Sidecar 判定原文与 AC/DC 睡眠超时，提供「保持唤醒」指引。
 * 应用只提示与指引，永不代改电源设置（契约冻结 §2.1）。
 *
 * supported=false、读取失败、用户关闭（本次 at_risk 持续期内）均不显示。
 * 数据经 store 电源切片（power.status_changed 事件 + 主动 powerGetStatus）；
 * contracts 视图模型已冻结，与 Composer 一致直接订阅 store。
 */
export function PowerPrompt({ actions }: PowerPromptProps) {
  usePowerStatusQuery(actions);
  const status = useDesktopStore(selectPromptStatus);
  const dismissed = useDesktopStore((state) => state.powerPromptDismissed);

  if (!shouldShowPowerPrompt(status, dismissed)) return null;

  const close = () => desktopStore.getState().dismissPowerPrompt();

  return (
    <aside className="power-prompt" role="status" aria-live="polite" data-testid="power-prompt">
      <div className="power-prompt-head">
        <strong>电脑可能即将休眠</strong>
        <button
          type="button"
          className="power-prompt-close"
          aria-label="关闭电源提示"
          onClick={close}
        >
          ×
        </button>
      </div>
      <p className="power-prompt-reason">{status.reason}</p>
      <dl className="power-prompt-facts">
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
      </dl>
      <p className="power-prompt-guide">
        保持唤醒需在 Windows 设置中自行调整：打开「设置 → 系统 → 电源和电池（或电源和睡眠）
        → 屏幕和睡眠」，把接通电源时的睡眠时间调长或设为「从不」。
        本应用只做提醒，不会代你修改电源设置。
      </p>
    </aside>
  );
}
