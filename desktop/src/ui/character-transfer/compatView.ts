/* 兼容报告 not_executed 条目的分组：按后端条目格式归为三类，其余进「其他保留项」。
   导入流程、导出预览与角色详情的兼容性弹窗共用。 */

export type NotExecutedGroupKey =
  | "worldBookStoredFields"
  | "unexpandedMacros"
  | "nonTurnTrigger"
  | "other";

export interface NotExecutedGroup {
  key: NotExecutedGroupKey;
  label: string;
  items: string[];
}

const NOT_EXECUTED_GROUPS: Array<{ key: NotExecutedGroupKey; label: string }> = [
  // `character_book.entries[i].probability（存而不运行）` 一类
  { key: "worldBookStoredFields", label: "世界书存而不运行字段" },
  // `macro:{{setvar::…}} @ data.personality（未展开，N 处）` 一类
  { key: "unexpandedMacros", label: "未展开宏" },
  // `hsr.event_system.…runtime_trigger.kind=time（存而不运行）` 一类
  { key: "nonTurnTrigger", label: "非 turn 触发（存而不运行）" },
  // 其余条目，如 data.extensions.hsr.command_panels
  { key: "other", label: "其他保留项" },
];

/** 按后端条目格式对 not_executed 分组，不改写条目文本。 */
export function groupNotExecuted(items: readonly string[]): NotExecutedGroup[] {
  const buckets = new Map<NotExecutedGroupKey, string[]>();
  for (const item of items) {
    const key = classifyNotExecutedItem(item);
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.push(item);
    } else {
      buckets.set(key, [item]);
    }
  }
  return NOT_EXECUTED_GROUPS.filter((group) => buckets.has(group.key)).map((group) => ({
    key: group.key,
    label: group.label,
    items: buckets.get(group.key) ?? [],
  }));
}

function classifyNotExecutedItem(item: string): NotExecutedGroupKey {
  if (item.startsWith("macro:")) return "unexpandedMacros";
  if (item.includes("runtime_trigger")) return "nonTurnTrigger";
  if (item.startsWith("character_book.entries")) return "worldBookStoredFields";
  return "other";
}
