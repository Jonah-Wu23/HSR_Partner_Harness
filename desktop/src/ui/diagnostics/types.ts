import type { TurnMetric } from "../../contracts/protocol";

/* V0.3.9 V03 诊断视图的适配层。
   diagnostics.prompt_assembly 与 metrics.query 在 contract-v1 里冻结为命令，
   但 contracts/protocol.ts 尚未给出结果类型（逻辑轨 L06/L07 提供）。
   这里按契约 §5 的字段口径定义本地视图类型，并做严格适配：
   缺字段一律保持 null 并在界面显示「无数据」；结构不符时抛出真实错误，
   由调用方把原始错误交给抽屉展示，不吞异常、不合成成功。
   逻辑轨冻结结果类型后，本文件替换为直接引用协议类型。 */

/** 装配模块（diagnostics.prompt_assembly 单项）。 */
export interface PromptAssemblyModule {
  /** 模块名（角色框架、世界书 before/after、HSR 扩展、聊天摘要、配对记忆…）。 */
  name: string;
  /** 字符范围起点；0 是真实零值，未提供为 null。 */
  char_start: number | null;
  /** 字符范围终点；未提供为 null。 */
  char_end: number | null;
  /** 内容 hash；未提供为 null。 */
  hash: string | null;
  /** 模块摘要；未提供为 null。 */
  summary: string | null;
  /** 该模块是否注入了记忆；未提供为 null（界面显示「未报告」）。 */
  memory_injected: boolean | null;
  /** 隐藏原文：只有用户显式请求后才存在，其余情况为 null。 */
  hidden_content: string | null;
}

export interface PromptAssemblyView {
  conversation_id: string | null;
  modules: PromptAssemblyModule[];
  /** 服务端既有诊断说明；缺省为空数组。 */
  diagnostics: string[];
  generated_at: string | null;
}

export interface MetricsQueryResult {
  metrics: TurnMetric[];
  next_cursor: string | null;
}

/** contract-v1 §5 要求的 TurnMetric 键集合；缺键即协议违规，适配层直接报错。 */
const TURN_METRIC_KEYS = [
  "metric_id",
  "account_id",
  "project_id",
  "conversation_id",
  "pair_id",
  "character_ref",
  "turn_kind",
  "turn_id",
  "task_id",
  "engine_turn_id",
  "provider",
  "model",
  "engine_type",
  "reasoning_effort",
  "status",
  "started_at",
  "first_event_at",
  "completed_at",
  "duration_ms",
  "input_tokens",
  "output_tokens",
  "total_tokens",
  "tool_rounds",
  "compression_count",
  "approval_count",
  "failure_type",
  "failure_message",
  "origin",
  "remote_device_key",
  "remote_device_name",
] as const;

function describeValue(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (Array.isArray(value)) return `array(${value.length})`;
  return typeof value;
}

function asRecord(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${what}：期望对象，实际收到 ${describeValue(value)}`);
  }
  return value as Record<string, unknown>;
}

function readNullableString(
  record: Record<string, unknown>,
  key: string,
  what: string,
): string | null {
  const value = record[key];
  if (value === undefined || value === null) return null;
  if (typeof value === "string") return value;
  throw new Error(`${what}.${key}：期望字符串或 null，实际收到 ${describeValue(value)}`);
}

function readNullableNumber(
  record: Record<string, unknown>,
  key: string,
  what: string,
): number | null {
  const value = record[key];
  if (value === undefined || value === null) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  throw new Error(`${what}.${key}：期望数字或 null，实际收到 ${describeValue(value)}`);
}

function readNullableBoolean(
  record: Record<string, unknown>,
  key: string,
  what: string,
): boolean | null {
  const value = record[key];
  if (value === undefined || value === null) return null;
  if (typeof value === "boolean") return value;
  throw new Error(`${what}.${key}：期望布尔或 null，实际收到 ${describeValue(value)}`);
}

/** 适配 diagnostics.prompt_assembly 的原始结果；结构不符抛出真实错误。 */
export function adaptPromptAssembly(raw: unknown): PromptAssemblyView {
  const record = asRecord(raw, "diagnostics.prompt_assembly 结果");
  const modulesRaw = record.modules;
  if (!Array.isArray(modulesRaw)) {
    const keys = Object.keys(record).join(", ");
    throw new Error(
      `diagnostics.prompt_assembly 结果缺少 modules 数组（实际字段：${keys || "无"}）`,
    );
  }
  const modules = modulesRaw.map((item, index) => {
    const what = `modules[${index}]`;
    const module = asRecord(item, what);
    const name = module.name;
    if (typeof name !== "string" || name.trim() === "") {
      const keys = Object.keys(module).join(", ");
      throw new Error(`${what}.name 缺失或不是非空字符串（实际字段：${keys || "无"}）`);
    }
    return {
      name,
      char_start: readNullableNumber(module, "char_start", what),
      char_end: readNullableNumber(module, "char_end", what),
      hash: readNullableString(module, "hash", what),
      summary: readNullableString(module, "summary", what),
      memory_injected: readNullableBoolean(module, "memory_injected", what),
      hidden_content: readNullableString(module, "hidden_content", what),
    } satisfies PromptAssemblyModule;
  });

  const diagnosticsRaw = record.diagnostics;
  let diagnostics: string[] = [];
  if (diagnosticsRaw !== undefined && diagnosticsRaw !== null) {
    if (!Array.isArray(diagnosticsRaw) || diagnosticsRaw.some((item) => typeof item !== "string")) {
      throw new Error(
        `diagnostics.prompt_assembly 结果 diagnostics：期望字符串数组，实际收到 ${describeValue(diagnosticsRaw)}`,
      );
    }
    diagnostics = diagnosticsRaw as string[];
  }

  return {
    conversation_id: readNullableString(record, "conversation_id", "diagnostics.prompt_assembly 结果"),
    modules,
    diagnostics,
    generated_at: readNullableString(record, "generated_at", "diagnostics.prompt_assembly 结果"),
  };
}

/** 适配 metrics.query 的原始结果；缺键或类型不符抛出真实错误。 */
export function adaptMetricsQueryResult(raw: unknown): MetricsQueryResult {
  const record = asRecord(raw, "metrics.query 结果");
  const metricsRaw = record.metrics;
  if (!Array.isArray(metricsRaw)) {
    const keys = Object.keys(record).join(", ");
    throw new Error(`metrics.query 结果缺少 metrics 数组（实际字段：${keys || "无"}）`);
  }
  const metrics = metricsRaw.map((item, index) => {
    const what = `metrics[${index}]`;
    const metric = asRecord(item, what);
    const missing = TURN_METRIC_KEYS.filter((key) => !(key in metric));
    if (missing.length > 0) {
      // 契约 §5：未观测字段必须为 null 且键仍存在；缺键是协议违规，如实暴露。
      throw new Error(`${what} 缺少契约字段：${missing.join(", ")}`);
    }
    return metric as unknown as TurnMetric;
  });
  return {
    metrics,
    next_cursor: readNullableString(record, "next_cursor", "metrics.query 结果"),
  };
}
