/**
 * V0.3.9 V06/V08：时间戳本地化展示（租约到期、设备时间）。
 *
 * 只做展示格式转换：空值返回 null（由调用方决定如何呈现「无值」），
 * 无法解析时原样返回输入字符串——不猜测、不替换为当前时间。
 */
export function formatLocalDateTime(value: string | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number): string => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}
