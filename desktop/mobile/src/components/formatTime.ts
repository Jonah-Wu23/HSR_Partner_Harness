const DATE_TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
};

const FORMATTERS = {
  minute: new Intl.DateTimeFormat("zh-CN", DATE_TIME_OPTIONS),
  second: new Intl.DateTimeFormat("zh-CN", { ...DATE_TIME_OPTIONS, second: "2-digit" }),
};

/**
 * ISO 时间戳按本地时区展示（如 2026/09/09 18:00:00）。空值返回 null，
 * 由调用方决定如何呈现；无法解析时原样返回服务端给出的字符串。
 */
export function formatLocalDateTime(
  value: string | null,
  precision: keyof typeof FORMATTERS = "second",
): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return FORMATTERS[precision].format(date);
}
