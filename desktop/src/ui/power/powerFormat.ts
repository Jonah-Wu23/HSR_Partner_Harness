import type { PowerStatusPayload } from "../../contracts/protocol";

/** 电源状态的纯展示工具：只做单位换算与契约字段的直读，不做语义猜测。 */

/** 提示出现条件（契约冻结 §1.5/§2.1 + V10 边界）：
    平台支持 且 远程服务开启 且 处于休眠风险，且用户未在本次持续期内关闭提示。 */
export function shouldShowPowerPrompt(
  status: PowerStatusPayload | null,
  dismissed: boolean,
): status is PowerStatusPayload {
  return Boolean(
    status && status.supported && status.remote_serve_enabled && status.at_risk && !dismissed,
  );
}

/** 睡眠超时秒数的只读展示；0 表示「从不」，null/异常值如实显示「未知」。 */
export function formatSleepTimeout(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return "未知";
  }
  if (seconds === 0) return "从不";
  if (seconds % 3600 === 0) return `${seconds} 秒（${seconds / 3600} 小时）`;
  if (seconds % 60 === 0) return `${seconds} 秒（${seconds / 60} 分钟）`;
  return `${seconds} 秒`;
}

/** checked_at（ISO8601 本地时间）转可读字符串；解析失败如实返回原文。 */
export function formatCheckedAt(iso: string): string {
  const time = new Date(iso);
  if (Number.isNaN(time.getTime())) return iso;
  return time.toLocaleString();
}
