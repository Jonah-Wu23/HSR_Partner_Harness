/* 世界书与 mufy 编辑器测试共用：用深拷贝加深冻结的输入锁定编辑器不原地修改数据。 */

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** 深冻结：任何对既有数据的原地修改都会在严格模式下抛 TypeError。 */
export function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    for (const child of Object.values(value as Record<string, unknown>)) {
      deepFreeze(child);
    }
    Object.freeze(value);
  }
  return value;
}
