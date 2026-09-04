export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type ValueKind =
  | "string"
  | "number"
  | "boolean"
  | "stringList"
  | "objectList"
  | "object"
  | "raw";

/**
 * 按值本身的类型决定呈现形态，不做任何语义猜测：
 * 字符串 / 数字 / 布尔 / 字符串列表 / 对象列表 / 对象分组 / 其余一律 raw JSON。
 */
export function classifyValue(value: unknown): ValueKind {
  if (typeof value === "string") return "string";
  if (typeof value === "number") return Number.isFinite(value) ? "number" : "raw";
  if (typeof value === "boolean") return "boolean";
  if (Array.isArray(value)) {
    if (value.every((item) => typeof item === "string")) return "stringList";
    if (value.every((item) => isPlainObject(item))) return "objectList";
    return "raw";
  }
  if (isPlainObject(value)) return "object";
  return "raw";
}

export function jsonToText(value: unknown): string {
  const text: string | undefined = JSON.stringify(value, null, 2);
  return text ?? "null";
}

export function valueTypeLabel(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "数组";
  if (typeof value === "string") return "字符串";
  if (typeof value === "number") return "数字";
  if (typeof value === "boolean") return "布尔值";
  if (isPlainObject(value)) return "对象";
  return "未知类型";
}
