import { isPlainObject } from "../mufy/mufyValues";

/**
 * 世界书（character_book）编辑器的契约常量与纯函数。
 * 语义对齐 docs/plans/V0.3.7-契约冻结.md §3（激活语义）与 §3.11（存而不运行清单）。
 * 这里只做数据形态判断与展示，不做任何语义猜测；未触及字段一律通过 spread 原样保留。
 */

export const DEFAULT_SCAN_DEPTH = 2;
export const DEFAULT_TOKEN_BUDGET = 2048;
export const DEFAULT_DEPTH = 4;
export const DEFAULT_ROLE = "system";

export const SUPPORTED_POSITIONS = ["before_char", "after_char", "atDepth"] as const;
export type SupportedPosition = (typeof SUPPORTED_POSITIONS)[number];

export const ROLES = ["system", "user", "assistant"] as const;

export const POSITION_LABELS: Record<string, string> = {
  before_char: "角色定义前",
  after_char: "角色定义后",
  atDepth: "对话深度注入",
  ANTop: "作者注释顶部",
  ANBottom: "作者注释底部",
  EMTop: "作者注释上方",
  EMBottom: "作者注释下方",
  outlet: "outlet 插槽",
};

export const SELECTIVE_LOGICS: Array<{ value: number; key: string; label: string }> = [
  { value: 0, key: "AND_ANY", label: "AND_ANY：任一次关键字命中即激活" },
  { value: 1, key: "NOT_ALL", label: "NOT_ALL：并非全部次关键字命中即激活" },
  { value: 2, key: "NOT_ANY", label: "NOT_ANY：全部次关键字未命中才激活" },
  { value: 3, key: "AND_ALL", label: "AND_ALL：全部次关键字命中才激活" },
];

/** 条目级「存而不运行」字段：key → 展示名。位置为条目顶层。 */
const ENTRY_NOT_RUN_KEYS: Array<[string, string]> = [
  ["probability", "probability（触发概率）"],
  ["useProbability", "useProbability（概率开关）"],
  ["priority", "priority（旧版权级，运行时只用 insertion_order）"],
  ["group", "group（互斥组）"],
  ["groupOverride", "groupOverride（互斥组覆盖）"],
  ["groupWeight", "groupWeight（互斥组权重）"],
  ["sticky", "sticky（粘滞）"],
  ["cooldown", "cooldown（冷却）"],
  ["delay", "delay（延迟）"],
  ["automation_id", "automation_id（自动化脚本）"],
  ["scanDepth", "scanDepth（条目级扫描深度）"],
  ["scan_depth", "scan_depth（条目级扫描深度）"],
];

/** 条目 extensions 内「存而不运行」字段：key → 展示名。 */
const EXTENSIONS_NOT_RUN_KEYS: Array<[string, string]> = [
  ["probability", "probability（触发概率）"],
  ["useProbability", "useProbability（概率开关）"],
  ["group", "group（互斥组）"],
  ["groupOverride", "groupOverride（互斥组覆盖）"],
  ["groupWeight", "groupWeight（互斥组权重）"],
  ["sticky", "sticky（粘滞）"],
  ["cooldown", "cooldown（冷却）"],
  ["delay", "delay（延迟）"],
  ["minActivations", "minActivations（最小激活数）"],
  ["automationId", "automationId（自动化脚本）"],
  ["ignoreBudget", "ignoreBudget（预算豁免）"],
  ["scanDepth", "scanDepth（条目级扫描深度）"],
  ["excludeRecursion", "excludeRecursion（递归排除）"],
  ["includeRecursion", "includeRecursion（递归包含）"],
  ["preventRecursion", "preventRecursion（递归阻止）"],
  ["delayUntilRecursion", "delayUntilRecursion（递归延迟）"],
];

export interface NotRunField {
  /** 稳定 id，用于 data-testid。 */
  id: string;
  label: string;
  where: string;
  /** 原样保留的值（只读展示）。 */
  value: unknown;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function valueText(value: unknown): string {
  if (typeof value === "string") return value;
  const text = JSON.stringify(value, null, 2);
  return text ?? "null";
}

export function displayPositionRaw(raw: unknown): string {
  if (typeof raw === "string") return raw;
  if (isFiniteNumber(raw)) return String(raw);
  return valueText(raw);
}

/** 支持的位置归一：字符串 before_char/after_char/atDepth 与数值 0/1/4；其余（含缺省）返回 null。 */
export function normalizePosition(raw: unknown): SupportedPosition | null {
  if (raw === "before_char" || raw === 0) return "before_char";
  if (raw === "after_char" || raw === 1) return "after_char";
  if (raw === "atDepth" || raw === 4) return "atDepth";
  return null;
}

export function getExtensions(entry: Record<string, unknown>): Record<string, unknown> | null {
  return isPlainObject(entry.extensions) ? entry.extensions : null;
}

function roleFromValue(raw: unknown): string | null {
  if (typeof raw === "string" && (ROLES as readonly string[]).includes(raw)) return raw;
  if (raw === 0) return "system";
  if (raw === 1) return "user";
  if (raw === 2) return "assistant";
  return null;
}

/** extensions.depth 为有限数字时返回它，否则 null（展示层回缺省 4）。 */
export function readDepth(ext: Record<string, unknown>): number | null {
  return isFiniteNumber(ext.depth) ? ext.depth : null;
}

/** extensions.role 为 system/user/assistant（含数值 0/1/2 映射）时返回规范名，否则 null。 */
export function readRole(ext: Record<string, unknown>): string | null {
  return "role" in ext ? roleFromValue(ext.role) : null;
}

export function positionSummary(entry: Record<string, unknown>): string {
  const normalized = normalizePosition(entry.position);
  if (normalized === null) {
    return entry.position === undefined
      ? "角色定义前（缺省）"
      : `不支持的位置 ${displayPositionRaw(entry.position)}（不注入）`;
  }
  if (normalized === "atDepth") {
    const ext = getExtensions(entry) ?? {};
    return `对话深度 ${readDepth(ext) ?? DEFAULT_DEPTH} · ${readRole(ext) ?? DEFAULT_ROLE}`;
  }
  return POSITION_LABELS[normalized];
}

const REGEX_FORM = /^\/(.*)\/([gimsuy]*)$/;

/**
 * 关键字正则合法性检查（对齐契约 §3.3）：
 * `/pattern/flags` 形态编译失败、或 use_regex 开启时裸关键字编译失败 → 警告。
 * 只警告不阻断，不改写任何关键字。
 */
export function entryRegexWarnings(entry: Record<string, unknown>): string[] {
  const warnings: string[] = [];
  const useRegex = entry.use_regex === true;
  const caseSensitive = entry.case_sensitive === true;
  const lists: Array<[string, unknown]> = [
    ["主关键字", entry.keys],
    ["次关键字", entry.secondary_keys],
  ];
  for (const [label, raw] of lists) {
    if (!Array.isArray(raw)) continue;
    for (const item of raw) {
      if (typeof item !== "string" || item === "") continue;
      const match = REGEX_FORM.exec(item);
      if (match) {
        try {
          new RegExp(match[1], match[2]);
        } catch {
          warnings.push(`${label}「${item}」不是合法正则，运行时将退化为字面包含匹配`);
        }
      } else if (useRegex) {
        try {
          new RegExp(item, caseSensitive ? "" : "i");
        } catch {
          warnings.push(`${label}「${item}」不是合法正则（use_regex 已开启），运行时将退化为字面包含匹配`);
        }
      }
    }
  }
  return warnings;
}

/** 条目内「保留但不运行」清单（契约 §3.11）。 */
export function collectEntryNotRunFields(entry: Record<string, unknown>): NotRunField[] {
  const fields: NotRunField[] = [];
  const add = (id: string, label: string, where: string, value: unknown) =>
    fields.push({ id, label, where, value });

  for (const [key, label] of ENTRY_NOT_RUN_KEYS) {
    if (key in entry) add(`entry-${key}`, label, "条目字段", entry[key]);
  }

  const ext = getExtensions(entry);
  if (ext) {
    for (const [key, label] of EXTENSIONS_NOT_RUN_KEYS) {
      if (key in ext) add(`ext-${key}`, label, "extensions", ext[key]);
    }
    for (const key of Object.keys(ext)) {
      if (key.startsWith("matchPersona") || key.startsWith("matchCharacter")) {
        add(`ext-${key}`, `${key}（用户/角色描述扫描开关）`, "extensions", ext[key]);
      }
    }
    if ("selectiveLogic" in ext) {
      const raw = ext.selectiveLogic;
      if (typeof raw !== "number" || !SELECTIVE_LOGICS.some((logic) => logic.value === raw)) {
        add("ext-selectiveLogic-invalid", "selectiveLogic 不是 0-3（运行时按 AND_ANY 处理）", "extensions", raw);
      }
    }
    if ("depth" in ext && !isFiniteNumber(ext.depth)) {
      add("ext-depth-invalid", "extensions.depth 不是数字（运行时按缺省 4 处理）", "extensions", ext.depth);
    }
    if ("role" in ext && roleFromValue(ext.role) === null) {
      add("ext-role-invalid", "extensions.role 不是 system/user/assistant（运行时按 system 处理）", "extensions", ext.role);
    }
    if (normalizePosition(entry.position) !== "atDepth" && ("depth" in ext || "role" in ext)) {
      add("ext-depth-role-dormant", "depth / role（仅 atDepth 位置生效，当前不生效）", "extensions", {
        depth: ext.depth,
        role: ext.role,
      });
    }
  }

  if (typeof entry.content === "string" && (entry.content.startsWith("@@activate") || entry.content.startsWith("@@dont_activate"))) {
    add("content-decorator", "@@activate / @@dont_activate 装饰器（content 前缀）", "content", entry.content);
  }

  const normalized = normalizePosition(entry.position);
  if (normalized === null && entry.position !== undefined) {
    add(
      "position",
      `position=${displayPositionRaw(entry.position)}（不支持的位置，不注入、不静默改写）`,
      "位置",
      entry.position,
    );
  }

  return fields;
}

/** 书级「保留但不运行」清单（契约 §3.11：recursive_scanning、extensions.world）。 */
export function collectBookNotRunFields(book: Record<string, unknown>): NotRunField[] {
  const fields: NotRunField[] = [];
  if ("recursive_scanning" in book) {
    fields.push({
      id: "book-recursive_scanning",
      label: "recursive_scanning（递归激活，存储不递归）",
      where: "书级字段",
      value: book.recursive_scanning,
    });
  }
  if (isPlainObject(book.extensions) && "world" in book.extensions) {
    fields.push({
      id: "book-ext-world",
      label: "extensions.world（外链世界书）",
      where: "书级 extensions",
      value: book.extensions.world,
    });
  }
  return fields;
}

const KNOWN_ENTRY_KEYS = new Set([
  "keys",
  "secondary_keys",
  "content",
  "comment",
  "name",
  "enabled",
  "insertion_order",
  "position",
  "constant",
  "selective",
  "case_sensitive",
  "use_regex",
  "id",
  "extensions",
  ...ENTRY_NOT_RUN_KEYS.map(([key]) => key),
]);

const KNOWN_EXTENSION_KEYS = new Set([
  "selectiveLogic",
  "depth",
  "role",
  ...EXTENSIONS_NOT_RUN_KEYS.map(([key]) => key),
]);

export function entryUnknownKeys(entry: Record<string, unknown>): string[] {
  return Object.keys(entry).filter((key) => !KNOWN_ENTRY_KEYS.has(key));
}

export function entryUnknownExtensionKeys(ext: Record<string, unknown>): string[] {
  return Object.keys(ext).filter(
    (key) => !KNOWN_EXTENSION_KEYS.has(key) && !key.startsWith("matchPersona") && !key.startsWith("matchCharacter"),
  );
}

/** 字符串数组形态判断：缺省 → 空列表；存在但不是字符串数组 → null（原样保留、不启用编辑）。 */
export function asStringList(value: unknown): string[] | null {
  if (value === undefined || value === null) return [];
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) return value as string[];
  return null;
}

export function createEmptyEntry(): Record<string, unknown> {
  return {
    keys: [],
    secondary_keys: [],
    content: "",
    comment: "",
    enabled: true,
    insertion_order: 100,
    position: "before_char",
    constant: false,
    selective: false,
    case_sensitive: false,
    use_regex: false,
    extensions: {},
  };
}
