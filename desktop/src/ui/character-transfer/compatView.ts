import type { CompatReportPayload } from "../../contracts/protocol";

/* ------------------------------------------------------------------ *
 * V0.3.7 兼容报告视图工具（契约见 docs/plans/V0.3.7-契约冻结.md §11/§3.11/§5.2/§6.1）。
 * 纯函数、无 React 依赖；not_executed 分组语义按冻结 §11 三类 + 其他保留项，
 * 导入流程、导出预览与角色详情页共用同一套分组。
 * ------------------------------------------------------------------ */

/** not_executed 分组类别：前三类来自冻结 §11 的条目格式，其余进「其他保留项」。 */
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
  // §11：`character_book.entries[i].probability（存而不运行）` 风格（世界书存而不运行字段）
  { key: "worldBookStoredFields", label: "世界书存而不运行字段" },
  // §11：`macro:{{setvar::…}} @ data.personality（未展开，N 处）`（非白名单宏）
  { key: "unexpandedMacros", label: "未展开宏" },
  // §11：`hsr.event_system.…runtime_trigger.kind=time（存而不运行）`（非 turn 触发）
  { key: "nonTurnTrigger", label: "非 turn 触发（存而不运行）" },
  // 兜底：既有条目（如 data.extensions.hsr.command_panels）等其余未执行项，不丢弃任何条目
  { key: "other", label: "其他保留项" },
];

/** 按冻结 §11 的条目格式对 not_executed 分组；分类只做协议格式识别，不改写条目文本。 */
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

/* ------------------------------------------------------------------ *
 * 从卡 JSON 派生兼容性视图（纯函数）。
 *
 * 用途：导入报告只在导入当下返回；角色详情页随时回看时，用本函数从
 * card.get 返回的完整 v3 JSON 静态派生可判定的兼容性视图。
 *
 * 边界（如实声明，不伪造导入时结论）：
 * - applied / preserved / normalized_from_root / errors 是导入时变换与失败的事实，
 *   从卡 JSON 无法可靠还原，恒为空数组；
 * - 非法正则关键字的判定依赖 Python re 语法，JS 侧无法可靠复刻，不在此判定
 *   （导入时的报告才是权威）；
 * - 本函数只覆盖「从卡内容即可静态判定」的存而不运行项与越界警告。
 * ------------------------------------------------------------------ */

const MACRO_TOKEN = /\{\{[^{}]*\}\}/g;
/** §5.2 白名单：{{char}} / {{user}}，大小写不敏感（对齐 ST 宏惯例）。 */
const MACRO_WHITELIST = new Set(["{{char}}", "{{user}}"]);

/** §3.11 存而不运行的世界书条目字段（含 ST 扩展字段，逐字段逐条目列出）。 */
const ENTRY_STORED_NOT_RUN_FIELDS = [
  "probability",
  "useProbability",
  "recursive_scanning",
  "recursive",
  "group",
  "groupOverride",
  "groupWeight",
  "sticky",
  "cooldown",
  "delay",
  "minActivations",
  "automationId",
  "scanDepth",
  "ignoreBudget",
  "matchWholeWords",
] as const;

/** §3.6 支持的位置值；其余位置（EM/AN/outlet 等）存而不运行、条目不注入。 */
const SUPPORTED_POSITIONS: ReadonlySet<string | number> = new Set([
  "before_char",
  "after_char",
  "atDepth",
  0,
  1,
  4,
]);

/** §3.4 selectiveLogic 合法值 0-3（缺省 0 = AND_ANY）。 */
const SELECTIVE_LOGIC_VALUES: ReadonlySet<number> = new Set([0, 1, 2, 3]);

export function deriveCompatViewFromCard(card: Record<string, unknown>): CompatReportPayload {
  const data = readObject(card.data) ?? card;
  const notExecuted: string[] = [];
  const warnings: string[] = [];

  deriveWorldBookItems(data, notExecuted, warnings);
  deriveUnexpandedMacros(data, notExecuted);
  deriveNonTurnTriggers(data, notExecuted);

  return {
    applied: [],
    preserved: [],
    not_executed: notExecuted,
    normalized_from_root: [],
    warnings,
    errors: [],
  };
}

function readObject(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function deriveWorldBookItems(
  data: Record<string, unknown>,
  notExecuted: string[],
  warnings: string[],
): void {
  const book = readObject(data.character_book);
  if (!book) return;
  const entries = Array.isArray(book.entries) ? book.entries : [];
  // §11：同字段多条目合并为 entries[...] 计数形式
  const fieldHits = new Map<string, number[]>();

  entries.forEach((rawEntry, index) => {
    const entry = readObject(rawEntry);
    if (!entry) return;
    const extensions = readObject(entry.extensions) ?? {};

    for (const field of ENTRY_STORED_NOT_RUN_FIELDS) {
      if (field in entry || field in extensions) {
        fieldHits.set(field, [...(fieldHits.get(field) ?? []), index]);
      }
    }
    // extensions.world 外链世界书（存而不运行：只运行卡内嵌 character_book）；空串视为未挂载
    const world = entry.world ?? extensions.world;
    if (typeof world === "string" ? world.trim() !== "" : world !== undefined && world !== null) {
      fieldHits.set("world", [...(fieldHits.get("world") ?? []), index]);
    }
    // 位置值不在支持集合 → 条目不注入（§3.6）
    const position = entry.position ?? extensions.position;
    if (
      position !== undefined &&
      !SUPPORTED_POSITIONS.has(position as string | number)
    ) {
      notExecuted.push(
        `character_book.entries[${index}].position=${String(position)}（存而不运行，条目不注入）`,
      );
    }
    // @@activate / @@dont_activate 装饰器（§3.11）
    if (typeof entry.content === "string") {
      const trimmed = entry.content.trimStart();
      if (trimmed.startsWith("@@activate") || trimmed.startsWith("@@dont_activate")) {
        notExecuted.push(`character_book.entries[${index}].content（@@ 装饰器，存而不运行）`);
      }
    }
    // selectiveLogic 越界值（§11 warnings；越界按 0 处理是运行时行为）
    if (
      "selectiveLogic" in extensions &&
      typeof extensions.selectiveLogic === "number" &&
      !SELECTIVE_LOGIC_VALUES.has(extensions.selectiveLogic)
    ) {
      warnings.push(
        `character_book.entries[${index}].extensions.selectiveLogic=${String(
          extensions.selectiveLogic,
        )}（越界，运行时按 0 处理）`,
      );
    }
  });

  for (const [field, indexes] of fieldHits) {
    if (indexes.length === 1) {
      notExecuted.push(`character_book.entries[${indexes[0]}].${field}（存而不运行）`);
    } else {
      notExecuted.push(
        `character_book.entries[...].${field}（存而不运行，共 ${indexes.length} 条）`,
      );
    }
  }
}

function deriveUnexpandedMacros(data: Record<string, unknown>, notExecuted: string[]): void {
  // 合并口径与导入报告一致：同宏同字段多处合并计数（§5.3）
  const hits = new Map<string, { token: string; field: string; count: number }>();
  const record = (fieldPath: string, text: unknown): void => {
    if (typeof text !== "string") return;
    for (const token of text.match(MACRO_TOKEN) ?? []) {
      if (MACRO_WHITELIST.has(token.toLowerCase())) continue;
      const key = `${token}\u0000${fieldPath}`;
      const hit = hits.get(key);
      if (hit) {
        hit.count += 1;
      } else {
        hits.set(key, { token, field: fieldPath, count: 1 });
      }
    }
  };

  record("data.description", data.description);
  record("data.personality", data.personality);
  record("data.scenario", data.scenario);
  record("data.first_mes", data.first_mes);
  record("data.system_prompt", data.system_prompt);
  record("data.post_history_instructions", data.post_history_instructions);
  if (Array.isArray(data.alternate_greetings)) {
    data.alternate_greetings.forEach((greeting, index) =>
      record(`data.alternate_greetings[${index}]`, greeting),
    );
  }
  const depthPrompt = readObject(readObject(data.extensions)?.depth_prompt);
  if (depthPrompt) record("data.extensions.depth_prompt.prompt", depthPrompt.prompt);

  const book = readObject(data.character_book);
  if (book && Array.isArray(book.entries)) {
    book.entries.forEach((rawEntry, index) => {
      const entry = readObject(rawEntry);
      if (entry) record(`data.character_book.entries[${index}].content`, entry.content);
    });
  }

  for (const { token, field, count } of hits.values()) {
    notExecuted.push(`macro:${token} @ ${field}（未展开${count > 1 ? `，${count} 处` : ""}）`);
  }
}

function deriveNonTurnTriggers(data: Record<string, unknown>, notExecuted: string[]): void {
  const hsr = readObject(readObject(data.extensions)?.hsr);
  const eventSystem = hsr?.event_system;
  if (!eventSystem) return;
  walkRuntimeTriggers(eventSystem, "hsr.event_system.", notExecuted);
}

function walkRuntimeTriggers(node: unknown, prefix: string, notExecuted: string[]): void {
  const obj = readObject(node);
  if (obj) {
    if ("runtime_trigger" in obj) {
      const trigger = readObject(obj.runtime_trigger);
      const kind = trigger?.kind;
      // §6.1：只执行 kind === "turn"；其余（time 等 / 未声明）存而不运行
      if (kind !== "turn") {
        const kindText = kind === undefined ? "缺失" : String(kind);
        notExecuted.push(`${prefix}runtime_trigger.kind=${kindText}（存而不运行）`);
      }
    }
    for (const [key, value] of Object.entries(obj)) {
      if (key === "runtime_trigger") continue;
      walkRuntimeTriggers(value, `${prefix}${key}.`, notExecuted);
    }
    return;
  }
  if (Array.isArray(node)) {
    const base = prefix.endsWith(".") ? prefix.slice(0, -1) : prefix;
    node.forEach((item, index) => walkRuntimeTriggers(item, `${base}[${index}].`, notExecuted));
  }
}
