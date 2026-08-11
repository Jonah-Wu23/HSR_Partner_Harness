/** 相对时间与聊天分组的小工具，纯展示用途。 */

const dayFormatter = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" });
const fullFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "numeric",
  day: "numeric",
});

export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const time = new Date(iso);
  if (Number.isNaN(time.getTime())) return "";
  const diffMs = now.getTime() - time.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24 && time.getDate() === now.getDate()) return `${hours} 小时前`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (
    time.getFullYear() === yesterday.getFullYear() &&
    time.getMonth() === yesterday.getMonth() &&
    time.getDate() === yesterday.getDate()
  ) {
    return "昨天";
  }
  if (time.getFullYear() === now.getFullYear()) {
    return dayFormatter.format(time);
  }
  return fullFormatter.format(time);
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}
