/* 诊断视图的取值格式化：null（未观测/未提供）与 0（真实零值）严格区分。
   禁止用字符数估算 token；这里只做展示格式化。 */

export const NO_DATA = "无数据";

export function formatMetricNumber(value: number | null): string {
  return value === null ? NO_DATA : String(value);
}

export function formatDurationMs(value: number | null): string {
  if (value === null) return NO_DATA;
  if (value < 1000) return `${value} ms`;
  const seconds = value / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
}

export function formatTimestamp(value: string | null): string {
  if (value === null || value === "") return NO_DATA;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function formatOptionalText(value: string | null): string {
  return value === null || value === "" ? NO_DATA : value;
}

/** 字符范围：0 是真实起点，未提供的端点显示「无数据」。 */
export function formatCharRange(start: number | null, end: number | null): string {
  if (start === null && end === null) return NO_DATA;
  return `${formatMetricNumber(start)} – ${formatMetricNumber(end)}`;
}

export function formatMemoryInjected(value: boolean | null): string {
  if (value === null) return "未报告";
  return value ? "已注入" : "未注入";
}

export const TURN_KIND_LABEL: Record<string, string> = {
  character_turn: "角色回合",
  assistant_task: "助手任务",
};

export const TURN_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  accepted: "已接受",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function formatTurnKind(value: string): string {
  return TURN_KIND_LABEL[value] ?? value;
}

export function formatTurnStatus(value: string): string {
  return TURN_STATUS_LABEL[value] ?? value;
}
