import type { NotExecutedCategory, NotExecutedItemPayload } from "../../contracts/protocol";

/* 兼容报告 not_executed 条目按后端给出的 category 分组。
   导入流程、导出预览与角色详情的兼容性弹窗共用。 */

export interface NotExecutedGroup {
  category: NotExecutedCategory;
  label: string;
  items: string[];
}

// 键的顺序即分组呈现顺序。
const CATEGORY_LABELS: Record<NotExecutedCategory, string> = {
  world_book: "世界书存而不运行字段",
  macro: "未展开宏",
  runtime_trigger: "非 turn 触发（存而不运行）",
  command_panels: "声明式指令面板",
};

/** 按 category 分组，组内保持后端顺序，不改写条目文本。 */
export function groupNotExecuted(items: readonly NotExecutedItemPayload[]): NotExecutedGroup[] {
  return (Object.keys(CATEGORY_LABELS) as NotExecutedCategory[])
    .map((category) => ({
      category,
      label: CATEGORY_LABELS[category],
      items: items.filter((item) => item.category === category).map((item) => item.text),
    }))
    .filter((group) => group.items.length > 0);
}
